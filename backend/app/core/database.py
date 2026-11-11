from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

_connect_args: dict = {}
_engine_kwargs: dict = {}
if settings.database_url.startswith("sqlite"):
    _connect_args["check_same_thread"] = False
    import os
    db_path = settings.database_url.replace("sqlite:///", "")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
else:
    # review P2：MySQL 默认 wait_timeout 8h，SQLAlchemy 默认不复检也不回收，
    # 池中空闲连接被服务端断开后首个复用请求会抛 "MySQL server has gone away"。
    # 线程池 + 调度器线程共享连接池，需要比默认 5+10 更大的容量。
    _engine_kwargs.update(pool_pre_ping=True, pool_recycle=1800, pool_size=10, max_overflow=20)

engine = create_engine(settings.database_url, connect_args=_connect_args, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    cursor = dbapi_connection.cursor()
    try:
        # WAL：崩溃安全（MEMORY 模式下进程中途被杀会必然损坏数据库文件）
        cursor.execute("PRAGMA journal_mode=WAL")
        # 多线程（FastAPI 线程池 + 调度器线程）并发写时等待而不是立刻报 database is locked
        cursor.execute("PRAGMA busy_timeout=5000")
        # SQLite 默认不启用外键约束
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def init_db(bind=engine) -> None:
    import backend.app.models  # noqa: F401

    _run_alembic_migrations()
    _normalize_model_config_names(bind)
    _normalize_sqlite_datetime_storage(bind)


def _run_alembic_migrations() -> None:
    try:
        from alembic import command
        from alembic.config import Config

        import logging
        import os
        import time

        logger = logging.getLogger(__name__)

        ini_path = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        ini_path = os.path.normpath(ini_path)
        if not os.path.exists(ini_path):
            Base.metadata.create_all(bind=engine)
            return

        alembic_cfg = Config(ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        # 应用内嵌迁移不要应用 alembic.ini 的 logging 配置：
        # 它会把 root logger 重置为 WARN 并换掉 handler，导致应用日志被静默
        alembic_cfg.attributes["skip_logging_config"] = True

        # 多 worker（uvicorn --workers N）并发启动时，避免多个进程同时跑迁移
        lock_path = os.path.join(os.path.dirname(ini_path), ".alembic-migrate.lock")
        lock_fd = None
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    break
                except FileExistsError:
                    if time.monotonic() > deadline:
                        logger.warning("等待迁移锁超时（%.1fs），继续执行迁移检查", 60.0)
                        break
                    time.sleep(0.5)
            inspector = inspect(engine)
            has_tables = bool(inspector.get_table_names())
            has_alembic = "alembic_version" in inspector.get_table_names()

            if has_tables and not has_alembic:
                # DB-2（P1-19）：不再盲目 stamp head——只有当库内 schema 与当前
                # 模型完全一致时才盖戳；否则明确报错要求人工确认版本，
                # 避免把旧库永久跳过迁移、后续以 no such column 暴露。
                from alembic.migration import MigrationContext
                from alembic.autogenerate import compare_metadata

                migration_context = MigrationContext.configure(engine)
                diffs = compare_metadata(migration_context, Base.metadata)
                if diffs:
                    raise RuntimeError(
                        "检测到无 alembic 版本记录的存量数据库，且其 schema 与当前模型存在差异。"
                        "为避免跳过应有的迁移，启动已中止。请人工确认该库的实际版本后执行"
                        " `alembic stamp <对应版本>`，再启动应用执行 `upgrade head`。"
                        f"差异摘要：{diffs[:5]}"
                    )
                logger.info("存量数据库 schema 与当前模型一致，已 stamp 到 head")
                command.stamp(alembic_cfg, "head")
            else:
                command.upgrade(alembic_cfg, "head")
        finally:
            if lock_fd is not None:
                os.close(lock_fd)
                try:
                    os.unlink(lock_path)
                except OSError:
                    pass
    except ImportError:
        Base.metadata.create_all(bind=engine)


def _normalize_model_config_names(bind) -> None:
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())
    if "model_configs" not in table_names:
        return

    with bind.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_migrations ("
                "name VARCHAR(128) PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )
        applied = connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'normalize_legacy_gpt_54_model_name_v1'")
        ).first()
        if applied:
            return
        connection.execute(text("UPDATE model_configs SET model_name = 'gpt-5.4' WHERE model_name = 'gpt5.4'"))
        connection.execute(text("INSERT INTO app_migrations (name) VALUES ('normalize_legacy_gpt_54_model_name_v1')"))


def _normalize_sqlite_datetime_storage(bind) -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    datetime_columns = {
        "users": ["created_at"],
        "platform_accounts": ["created_at", "updated_at"],
        "account_cookie_versions": ["created_at"],
        "login_sessions": ["created_at"],
        "notes": ["created_at"],
        "model_configs": ["created_at"],
        "ai_drafts": ["created_at"],
        "ai_generated_assets": ["created_at"],
        "publish_jobs": ["created_at", "published_at"],
        "tasks": ["created_at"],
        "monitoring_targets": ["created_at", "updated_at", "last_refreshed_at"],
        "monitoring_snapshots": ["created_at"],
        "keyword_groups": ["created_at", "updated_at"],
        "api_logs": ["created_at"],
    }
    with bind.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS app_migrations ("
                "name VARCHAR(128) PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL)"
            )
        )
        applied = connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'sqlite_datetime_asia_shanghai_v1'")
        ).first()

        inspector = inspect(bind)
        table_names = set(inspector.get_table_names())
        if not applied:
            for table_name, column_names in datetime_columns.items():
                if table_name not in table_names:
                    continue
                existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
                for column_name in column_names:
                    if column_name not in existing_columns:
                        continue
                    connection.execute(
                        text(f"UPDATE {table_name} SET {column_name} = datetime({column_name}, '+8 hours') WHERE {column_name} IS NOT NULL")
                    )
            connection.execute(text("INSERT INTO app_migrations (name) VALUES ('sqlite_datetime_asia_shanghai_v1')"))

        scheduled_at_applied = connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'sqlite_publish_scheduled_at_asia_shanghai_v1'")
        ).first()
        if scheduled_at_applied:
            return
        if "publish_jobs" in table_names and "scheduled_at" in {column["name"] for column in inspector.get_columns("publish_jobs")}:
            connection.execute(
                text("UPDATE publish_jobs SET scheduled_at = datetime(scheduled_at, '+8 hours') WHERE scheduled_at IS NOT NULL")
            )
        connection.execute(text("INSERT INTO app_migrations (name) VALUES ('sqlite_publish_scheduled_at_asia_shanghai_v1')"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
