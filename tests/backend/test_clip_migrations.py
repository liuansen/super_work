"""剪辑工坊迁移：真实 Alembic upgrade 建出两张表。"""
from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def _run_upgrade(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db_path = tmp_path / "clip-migration.db"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path}")
    config = Config(str(root / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend" / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(config, "head")
    return db_path


def test_upgrade_creates_clip_tables(tmp_path, monkeypatch):
    db_path = _run_upgrade(tmp_path, monkeypatch)
    engine = create_engine(f"sqlite:///{db_path}")
    tables = set(inspect(engine).get_table_names())
    assert {"clip_sessions", "clip_exports"} <= tables
    engine.dispose()
