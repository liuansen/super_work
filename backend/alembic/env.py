from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool, text

from backend.app.core.database import Base
import backend.app.models  # noqa: F401

config = context.config
# 应用内嵌迁移（database.init_db）会设置 skip_logging_config：
# 只保留控制台日志，不重配宿主的 logger。手工执行 alembic CLI 时仍按 ini 配置。
if config.config_file_name is not None and not config.attributes.get("skip_logging_config"):
    # review P2：fileConfig 默认 disable_existing_loggers=True。应用内嵌迁移
    # （lifespan -> init_db -> command.upgrade）会因此静默掉 uvicorn access log
    # 与所有应用 logger。这里保留已有 logger，只应用 alembic 自己的配置。
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _get_url() -> str:
    """DB-2（P1-19）：默认与应用共用同一个数据库（settings.database_url）。

    仅显式设置 ALEMBIC_DATABASE_URL 时才覆盖——避免 CLI 迁移与应用
    连接到不同库（旧实现优先读 DATABASE_URL，且 ini 的相对路径随 CWD 漂移）。
    """
    explicit = os.environ.get("ALEMBIC_DATABASE_URL")
    if explicit:
        return explicit
    try:
        from backend.app.core.config import get_settings

        settings_url = get_settings().database_url
        if settings_url:
            return settings_url
    except Exception:
        pass
    return config.get_main_option("sqlalchemy.url")


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _get_url()
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = url

    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool, connect_args=connect_args)

    if url.startswith("sqlite"):

        @event.listens_for(connectable, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        if url.startswith("sqlite"):
            # P0（review）：batch 迁移会 DROP/重建被外键引用的父表，SQLite 在
            # foreign_keys=ON 时对父表的隐式 DELETE 会触发 IntegrityError。
            # 且 PRAGMA foreign_keys 在事务内是 no-op，必须在 BEGIN 之前关闭；
            # 数据完整性由迁移内的显式清理逻辑保证，迁移结束再恢复。
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        with context.begin_transaction():
            context.run_migrations()
        if url.startswith("sqlite"):
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
