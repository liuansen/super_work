"""迁移：真实 Alembic upgrade 建出抖音表；程序式 Config 指向临时库，移除外部 DATABASE_URL。"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


def _load_migrations_module():
    """加载 backend/alembic/env.py 同款的迁移入口（程序式，不进应用 lifespan）。"""
    return None


def _run_upgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("DATABASE_URL", raising=False)  # 防外部环境变量劫持迁移目标
    db_path = tmp_path / "migration-test.db"
    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    return db_path


def test_upgrade_creates_douyin_tables_on_empty_database(tmp_path, monkeypatch):
    db_path = _run_upgrade(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"douyin_accounts", "douyin_reference_works", "douyin_publish_tasks", "douyin_metric_snapshots"} <= tables
    # 版本表指向新 revision
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert version == "a1b2c3d4e5f6"
    engine.dispose()


def test_upgrade_preserves_existing_xhs_rows(tmp_path, monkeypatch):
    """先建旧 head 的库并写入一行 users，再升级到 head：既有行必须原样保留。"""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "upgrade-existing.db"

    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "60cd5c95fde1")  # 抖音迁移之前的 head

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        connection.execute(
            text("INSERT INTO users (username, password_hash, created_at) "
                 "VALUES ('legacy-user', 'x', '2026-01-01 00:00:00')")
        )
        connection.commit()
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT username FROM users WHERE username = 'legacy-user'")
        ).scalar()
        count = connection.execute(text("SELECT COUNT(*) FROM douyin_accounts")).scalar()
    assert row == "legacy-user"
    assert count == 0  # 新表为空，未动旧数据
    engine.dispose()


DOUYIN_TABLES = (
    "douyin_accounts",
    "douyin_reference_works",
    "douyin_publish_tasks",
    "douyin_metric_snapshots",
)


def _column_schemas(engine):
    inspector = inspect(engine)
    schemas = {}
    for table in DOUYIN_TABLES:
        columns = {}
        for column in inspector.get_columns(table):
            columns[column["name"]] = (
                str(column["type"]).upper(), bool(column.get("nullable", True)),
            )
        schemas[table] = columns
    return schemas


def test_migration_matches_model_metadata(tmp_path, monkeypatch):
    """防漂移：alembic 真实升级建出的表结构与 ORM metadata 建出的必须逐列一致。"""
    from backend.app.core.database import Base

    migrated_path = _run_upgrade(tmp_path, monkeypatch)

    metadata_path = tmp_path / "metadata.db"
    metadata_engine = create_engine(f"sqlite:///{metadata_path}")
    Base.metadata.create_all(bind=metadata_engine)

    migrated = _column_schemas(create_engine(f"sqlite:///{migrated_path}"))
    modeled = _column_schemas(metadata_engine)
    for table in DOUYIN_TABLES:
        assert migrated[table] == modeled[table], f"迁移与模型漂移: {table}"
    metadata_engine.dispose()
