"""健康检查、平台注册表、前端源码约束、基础模块导入与数据库初始化测试。

本文件由原 tests/backend/test_api.py 机械拆分而来；测试逻辑、断言、
mock 与 fixture 行为均未改动。
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from api_helpers import *  # noqa: F401,F403

def test_health_endpoint_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "spider-xhs"}

def test_platforms_endpoint_exposes_product_registry():
    response = client.get("/api/platforms")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 6
    assert payload["items"][0]["id"] == "xhs"
    assert payload["items"][0]["enabled"] is True
    # CLN-2：抖音已如实启用；下一个未启用平台才是 coming_soon
    assert payload["items"][1]["status"] == "enabled"
    coming_soon = [item for item in payload["items"] if item["status"] == "coming_soon"]
    assert len(coming_soon) == 4

def test_xhs_analytics_overview_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/xhs/analytics/overview")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_backend_foundation_modules_import():
    from backend.app.core.config import get_settings
    from backend.app.core.database import Base
    from backend.app.models import PlatformAccount, Note, Task, User

    settings = get_settings()
    assert settings.app_name == "Spider_XHS"
    assert Base is not None
    assert User.__tablename__ == "users"
    assert PlatformAccount.__tablename__ == "platform_accounts"
    assert Note.__tablename__ == "notes"
    assert Task.__tablename__ == "tasks"

def test_accounts_page_does_not_auto_check_accounts_on_load():
    source = open("frontend/src/pages/platforms/xhs/accounts-page.tsx", encoding="utf-8").read()

    assert "refreshMissingProfiles" not in source
    assert "void refreshMissingProfiles(loadedAccounts)" not in source

def test_accounts_page_uses_antd_components_and_shows_check_state():
    source = open("frontend/src/pages/platforms/xhs/accounts-page.tsx", encoding="utf-8").read()

    assert "antd" in source
    assert "checkingAccountIds" in source or "checkingId" in source or "isChecking" in source
    assert "检查" in source

def test_xhs_direct_request_env_does_not_mutate_process_env(monkeypatch):
    """代理隔离已下沉到 HTTP 会话层（trust_env=False）。

    旧的实现会全局删除 os.environ 里的代理变量，影响其他并发线程；
    现在该上下文管理器必须是无副作用的。
    """
    from backend.app.adapters.xhs.request_env import direct_xhs_request_env

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:10809")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:10809")

    with direct_xhs_request_env():
        assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:10809"
        assert os.environ["HTTP_PROXY"] == "http://127.0.0.1:10809"

    assert os.environ["HTTPS_PROXY"] == "http://127.0.0.1:10809"

def test_browser_http_client_does_not_inherit_env_proxy():
    """XHS 传输层默认不继承环境代理（线程安全的代理隔离方式）。"""
    import inspect

    from xhs_utils.xhs_core.http import BrowserHttpClient

    source = inspect.getsource(BrowserHttpClient.__init__)
    assert "trust_env=trust_env" in source
    assert "trust_env: bool = False" in source

def test_xhs_adapters_isolate_sdk_calls_from_broken_system_proxy():
    adapter_paths = [
        "backend/app/adapters/xhs/creator_login_adapter.py",
        "backend/app/adapters/xhs/creator_api_adapter.py",
        "backend/app/adapters/xhs/pc_login_adapter.py",
        "backend/app/adapters/xhs/pc_api_adapter.py",
    ]

    for path in adapter_paths:
        source = open(path, encoding="utf-8").read()
        assert "direct_xhs_request_env" in source

def test_crawler_page_exports_spider_style_excel():
    source = open("frontend/src/pages/platforms/xhs/crawler-page.tsx", encoding="utf-8").read()

    assert "noteExcelHeaders" in source
    assert "笔记id" in source
    assert "图片地址url列表" in source
    assert "application/vnd.ms-excel;charset=utf-8" in source

def test_crawler_page_uses_antd_table():
    source = open("frontend/src/pages/platforms/xhs/crawler-page.tsx", encoding="utf-8").read()

    assert "antd" in source
    assert "Table" in source

def test_discovery_uses_antd_components_and_preserves_core_logic():
    source = open("frontend/src/pages/platforms/xhs/discovery-page.tsx", encoding="utf-8").read()

    assert "antd" in source
    assert "async function ensureNoteDetail" in source or "ensureNoteDetail" in source
    assert "保存" in source
    assert "评论" in source
    assert "原文" in source

def test_discovery_preserves_note_detail_and_media_logic():
    source = open("frontend/src/pages/platforms/xhs/discovery-page.tsx", encoding="utf-8").read()

    assert "function getNoteVideoUrl" in source
    assert "function getNoteKindLabel" in source
    assert "detailMediaIndex" in source
    assert "视频" in source
    assert "图文" in source

def test_library_page_preserves_delete_and_media_logic():
    source = open("frontend/src/pages/platforms/xhs/library-page.tsx", encoding="utf-8").read()
    api_source = open("frontend/src/lib/api.ts", encoding="utf-8").read()

    assert "deleteSavedNote" in api_source
    assert "handleDeleteNote" in source
    assert "删除" in source
    assert "function getSavedNoteCoverUrl" in source
    assert 'referrerPolicy="no-referrer"' in source

def test_discovery_cards_show_note_media_type():
    source = open("frontend/src/pages/platforms/xhs/discovery-page.tsx", encoding="utf-8").read()

    assert "function getNoteKindLabel" in source
    assert "视频" in source
    assert "图文" in source

def test_rewrite_page_preserves_mode_switch():
    source = open("frontend/src/pages/platforms/xhs/rewrite-page.tsx", encoding="utf-8").read()

    assert "rewrite" in source
    assert "generate" in source
    assert "改写" in source
    assert "生成" in source
    assert "antd" in source

def test_publish_page_uses_antd_components():
    source = open("frontend/src/pages/platforms/xhs/publish-page.tsx", encoding="utf-8").read()

    assert "antd" in source
    assert "发布" in source

def test_openai_compatible_text_client_decodes_utf8_json_when_response_headers_are_wrong(monkeypatch):
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    class DummyConfig:
        base_url = "https://api.example.test/v1"
        model_name = "gpt-5.4"

    class FakeResponse:
        def __init__(self):
            self.content = (
                b'{"choices":[{"message":{"content":"'
                + "你好，今天很适合去公园散步。".encode("utf-8")
                + b'"}}]}'
            )
            self.encoding = "ISO-8859-1"
            self.apparent_encoding = "utf-8"
            self.headers = {"content-type": "text/event-stream"}

        def raise_for_status(self):
            return None

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("backend.app.services.ai_service.requests.post", fake_post)
    # SEC-5：请求前会做真实 DNS 校验；本测试专注 UTF-8 JSON 解码，跳过出站守卫
    monkeypatch.setattr(
        "backend.app.services.ai_service._assert_public_model_endpoint", lambda base_url: None
    )

    client = OpenAICompatibleTextClient()
    result = client.rewrite_note(
        model_config=DummyConfig(),
        api_key="test-key",
        title="原文标题",
        body="今天天气很好，我们去公园散步。",
        instruction="保留中文自然表达",
    )

    assert result == "你好，今天很适合去公园散步。"

def test_database_initialization_creates_user_table(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    db_url = f"sqlite:///{tmp_path / 'init-test.db'}"
    # DB-2：迁移目标库通过 ALEMBIC_DATABASE_URL 显式指定（默认与应用 settings 共库）
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    cfg = Config(os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "alembic.ini")))
    command.upgrade(cfg, "head")

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    table_names = inspect(test_engine).get_table_names()
    assert "users" in table_names
    assert "platform_accounts" in table_names
    assert "alembic_version" in table_names

def test_alembic_initial_migration_creates_all_product_tables(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config

    db_url = f"sqlite:///{tmp_path / 'alembic-tables-test.db'}"
    # DB-2：迁移目标库通过 ALEMBIC_DATABASE_URL 显式指定
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    cfg = Config(os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "backend", "alembic.ini")))
    command.upgrade(cfg, "head")

    test_engine = create_engine(db_url, connect_args={"check_same_thread": False})
    table_names = set(inspect(test_engine).get_table_names())
    expected = {
        "users", "platform_accounts", "account_cookie_versions", "login_sessions",
        "notes", "note_assets", "note_comments", "tags", "note_tags",
        "model_configs", "ai_drafts", "ai_generated_assets",
        "publish_jobs", "publish_assets", "tasks",
        "monitoring_targets", "monitoring_snapshots",
        "keyword_groups", "api_logs",
    }
    assert expected.issubset(table_names)

def test_database_initialization_normalizes_legacy_gpt_54_model_name(tmp_path):
    from backend.app.core.database import _normalize_model_config_names

    engine = create_engine(f"sqlite:///{tmp_path / 'model-name-migration-test.db'}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE model_configs (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    name VARCHAR(128) NOT NULL,
                    model_type VARCHAR(32) NOT NULL,
                    provider VARCHAR(64) NOT NULL,
                    model_name VARCHAR(128) NOT NULL,
                    base_url TEXT NOT NULL,
                    encrypted_api_key TEXT NOT NULL,
                    is_default BOOLEAN NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO model_configs "
                "(id, user_id, name, model_type, provider, model_name, base_url, encrypted_api_key, is_default) "
                "VALUES (1, 1, 'Text model', 'text', 'openai-compatible', 'gpt5.4', 'https://api.example.test/v1', '', 1)"
            )
        )

    _normalize_model_config_names(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT model_name FROM model_configs WHERE id = 1")).mappings().one()
        assert row["model_name"] == "gpt-5.4"
        assert connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'normalize_legacy_gpt_54_model_name_v1'")
        ).first()

def test_database_initialization_normalizes_existing_sqlite_times_to_shanghai(tmp_path):
    from backend.app.core.database import _normalize_sqlite_datetime_storage

    engine = create_engine(f"sqlite:///{tmp_path / 'time-migration-test.db'}", connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE platform_accounts (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    platform VARCHAR(32) NOT NULL,
                    sub_type VARCHAR(32),
                    external_user_id VARCHAR(128) NOT NULL,
                    nickname VARCHAR(128) NOT NULL,
                    avatar_url TEXT NOT NULL,
                    status VARCHAR(32) NOT NULL,
                    status_message TEXT NOT NULL DEFAULT '',
                    profile_json TEXT NOT NULL DEFAULT '{}',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            text(
                "INSERT INTO platform_accounts "
                "(id, user_id, platform, sub_type, external_user_id, nickname, avatar_url, status, created_at, updated_at) "
                "VALUES (1, 1, 'xhs', 'pc', 'pc-1', 'cat', '', 'active', '2026-04-30 07:50:43', '2026-04-30 07:50:43')"
            )
        )

    _normalize_sqlite_datetime_storage(engine)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT created_at, updated_at FROM platform_accounts WHERE id = 1")
        ).mappings().one()
        assert str(row["created_at"]).startswith("2026-04-30 15:50:43")
        assert str(row["updated_at"]).startswith("2026-04-30 15:50:43")
        assert connection.execute(
            text("SELECT name FROM app_migrations WHERE name = 'sqlite_datetime_asia_shanghai_v1'")
        ).first()
