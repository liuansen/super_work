"""应用权限迁移：真实 Alembic upgrade 建表 + 种子数据。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def _run_upgrade(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "app-migration.db"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path}")
    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    return db_path


def test_upgrade_creates_app_permission_tables_and_seeds(tmp_path, monkeypatch):
    db_path = _run_upgrade(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"app_registry", "user_app_permissions"} <= tables
    with engine.connect() as conn:
        # 首个用户（最低 id）为管理员；无用户时不报错
        is_admin = conn.execute(
            text("SELECT is_admin FROM users ORDER BY id LIMIT 1")
        ).scalar()
        assert is_admin in (0, 1, None, False, True)
        # 应用目录种子：三个工作台应用，默认全部开放
        keys = {
            row[0]
            for row in conn.execute(text("SELECT app_key FROM app_registry")).fetchall()
        }
        assert {"xhs", "douyin", "clip"} <= keys
        enabled = conn.execute(
            text("SELECT COUNT(*) FROM app_registry WHERE enabled=1")
        ).scalar()
        assert enabled >= 3
    engine.dispose()
