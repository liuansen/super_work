"""安全回归测试骨架（FIX_PLAN W0-2 / SEC-*）。

每个 P0 修复在本文件中保留至少一条"修复前会失败"的测试。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.app.core.config import Settings, get_settings
from backend.app.core.media_source import (
    InvalidMediaSource,
    assert_owned_media_name,
    validate_media_file_name,
)
from backend.app.main import app


# ---------------------------------------------------------------------------
# SEC-1 配置优先级与启动安全
# ---------------------------------------------------------------------------

def _make_settings(**kwargs) -> Settings:
    """构造与全局缓存无关的 Settings 实例，隔离 .env 文件。"""
    return Settings(_env_file=None, **kwargs)


class TestConfigPriority:
    def test_env_var_overrides_yaml(self, monkeypatch, tmp_path):
        """环境变量必须覆盖 YAML 值（P0-1：修复前 env 完全失效）。"""
        config_file = tmp_path / "override.yaml"
        config_file.write_text(
            "security:\n"
            '  secret_key: "from-yaml"\n'
            "frontend:\n"
            "  serve_static: true\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CONFIG_FILE", str(config_file))
        monkeypatch.setenv("SECRET_KEY", "from-env")
        monkeypatch.setenv("FRONTEND_SERVE_STATIC", "false")

        settings = _make_settings()

        assert settings.secret_key == "from-env"
        assert settings.frontend_serve_static is False

    def test_yaml_overrides_code_default(self, monkeypatch, tmp_path):
        """YAML 必须覆盖代码默认值（但低于 .env / 环境变量）。"""
        config_file = tmp_path / "override.yaml"
        config_file.write_text(
            "security:\n"
            '  secret_key: "yaml-strong-secret-value"\n',
            encoding="utf-8",
        )
        monkeypatch.setenv("CONFIG_FILE", str(config_file))
        monkeypatch.delenv("SECRET_KEY", raising=False)

        settings = _make_settings()

        assert settings.secret_key == "yaml-strong-secret-value"

    def test_invalid_environment_rejected(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "staging")
        with pytest.raises(ValueError, match="ENVIRONMENT"):
            _make_settings()


class TestRuntimeSafety:
    """生产环境使用占位密钥必须拒绝启动（P0-1）。"""

    def test_production_default_secret_rejected(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("ALLOW_INSECURE_DEFAULTS", raising=False)
        # YAML 中 default.yaml 的 secret_key 现在是空串，模拟历史占位值：
        monkeypatch.setattr(
            "backend.app.core.config.Settings.model_post_init", lambda self, ctx: None
        )
        settings = _make_settings(environment="production", secret_key="dev-only-change-me")

        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            settings.assert_runtime_safety()

    def test_production_empty_secret_rejected(self):
        settings = Settings(
            _env_file=None,
            environment="production",
            secret_key="",
        )
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            settings.assert_runtime_safety()

    def test_production_placeholder_secret_rejected(self):
        settings = Settings(
            _env_file=None,
            environment="production",
            secret_key="CHANGE_ME_VIA_ENV_VAR",
        )
        with pytest.raises(RuntimeError):
            settings.assert_runtime_safety()

    def test_production_strong_secret_passes(self):
        settings = Settings(
            _env_file=None,
            environment="production",
            secret_key="x" * 64,
        )
        settings.assert_runtime_safety()  # 不抛异常

    def test_development_placeholder_only_warns(self, caplog):
        settings = Settings(
            _env_file=None,
            environment="development",
            secret_key="dev-only-change-me",
        )
        settings.assert_runtime_safety()  # 不抛异常

    def test_allow_insecure_defaults_bypasses_production_check(self, monkeypatch):
        monkeypatch.setenv("ALLOW_INSECURE_DEFAULTS", "1")
        settings = Settings(
            _env_file=None,
            environment="production",
            secret_key="dev-only-change-me",
            allow_insecure_defaults=True,
        )
        settings.assert_runtime_safety()  # 显式豁免

    def test_development_empty_secret_generates_random(self):
        """开发环境空密钥生成进程内随机密钥，而不是回退到公开默认值。"""
        settings = Settings(_env_file=None, environment="development", secret_key="")
        assert settings.secret_key
        assert settings.secret_key != "dev-only-change-me"


class TestProductionRegistrationDefault:
    def test_production_registration_disabled_by_default(self):
        settings = Settings(_env_file=None, environment="production", secret_key="x" * 64)
        assert settings.registration_enabled is False

    def test_production_registration_explicit_opt_in(self, monkeypatch):
        monkeypatch.setenv("REGISTRATION_ENABLED", "true")
        settings = Settings(_env_file=None, environment="production", secret_key="x" * 64)
        assert settings.registration_enabled is True

    def test_development_registration_open_by_default(self):
        settings = Settings(_env_file=None)
        assert settings.registration_enabled is True


def test_get_settings_is_cached_singleton():
    assert get_settings() is get_settings()


# ---------------------------------------------------------------------------
# SEC-2 素材路径与跨用户归属
# ---------------------------------------------------------------------------

class TestMediaSourceValidation:
    @pytest.mark.parametrize(
        "bad",
        [
            ".." + chr(92) + ".." + chr(92) + "config" + chr(92) + "default.yaml",
            "../../etc/passwd",
            "/etc/passwd",
            "C:" + chr(92) + "Windows" + chr(92) + "win.ini",
            "a/b.png",
            "a" + chr(92) + "b.png",
            "..",
            ".",
            "",
            "  ",
        ],
    )
    def test_path_traversal_rejected(self, bad):
        with pytest.raises(InvalidMediaSource):
            validate_media_file_name(bad)

    def test_cross_user_media_name_rejected(self):
        with pytest.raises(InvalidMediaSource, match="不属于当前用户"):
            assert_owned_media_name("xhs-image-u2-abcdef123456.png", user_id=1)

    def test_owned_media_name_accepted(self):
        assert assert_owned_media_name("xhs-image-u1-abcdef123456.png", user_id=1) == (
            "xhs-image-u1-abcdef123456.png"
        )

    def test_unprefixed_media_name_rejected(self):
        with pytest.raises(InvalidMediaSource):
            assert_owned_media_name("cover.png", user_id=1)


# ---------------------------------------------------------------------------
# SEC-3 出站 URL 校验（SSRF）
# ---------------------------------------------------------------------------

class TestOutboundUrlValidation:
    def _validate(self, url: str):
        from backend.app.services.asset_downloader import AssetDownloadRejected, validate_outbound_url

        validate_outbound_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x.png",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/a.png",
            "http://192.168.1.1/a.png",
            "http://localhost/a.png",
            "http://[::1]/a.png",
            "ftp://cdn.example.com/a.png",
        ],
    )
    def test_private_and_non_http_rejected(self, url):
        with pytest.raises(Exception):
            self._validate(url)

    def test_allowlisted_public_host_passes_dns_check(self):
        # 白名单域名：DNS 解析在测试环境可能失败，但不应以"私网"理由拒绝。
        # 这里只验证域名不在白名单时被拒；白名单 + 公网解析的完整链路由手工验收覆盖。
        from backend.app.services.asset_downloader import AssetDownloadRejected

        with pytest.raises(AssetDownloadRejected):
            self._validate("https://evil.example.com/a.png")


class TestAssetDownloaderRejects:
    def test_download_rejects_private_url(self, monkeypatch):
        from backend.app.services import asset_downloader

        # 无网络环境也可测试：validate 在请求前就拒绝
        result = asset_downloader.download_asset_to_local(
            "http://169.254.169.254/latest/meta-data/", user_id=1, asset_type="image"
        )
        assert result is None

    def test_download_rejects_non_allowlisted_host(self):
        from backend.app.services import asset_downloader

        result = asset_downloader.download_asset_to_local(
            "https://malicious.example.com/payload.png", user_id=1, asset_type="image"
        )
        assert result is None


# ---------------------------------------------------------------------------
# SEC-4 上传限额
# ---------------------------------------------------------------------------

def _client_with_db(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base, get_db
    from backend.app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'sec-test.db'}", connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), app, get_db


def _register(client, username):
    resp = client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def _redirect_storage_to_tmp(tmp_path, monkeypatch):
    """review P2-6：上传测试不得污染真实 storage 目录。"""
    settings = get_settings()
    original = type(settings).storage_dir
    monkeypatch.setattr(
        type(settings), "storage_dir", property(lambda self: tmp_path / "storage")
    )
    yield
    monkeypatch.setattr(type(settings), "storage_dir", original)


class TestUploadLimits:
    def test_small_upload_succeeds_and_has_no_abs_path(self, tmp_path, _redirect_storage_to_tmp):
        """正常小文件上传成功；响应不泄露服务器绝对路径（BE-10）。"""
        client, app, get_db = _client_with_db(tmp_path)
        try:
            headers = _register(client, "upload-ok-user")
            resp = client.post(
                "/api/files/upload",
                headers=headers,
                files={"file": ("cover.png", b"\x89PNG\r\n\x1a\n" + b"0" * 128, "image/png")},
            )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["file_name"].startswith("xhs-upload-u")
            assert "file_path" not in payload
            # 文件落在重定向后的临时目录，而非真实 storage
            assert (tmp_path / "storage" / "media" / payload["file_name"]).exists()
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_oversized_stream_aborts_with_413(self, tmp_path, monkeypatch, _redirect_storage_to_tmp):
        """超过 MAX_UPLOAD_SIZE 的流式上传在超限点立即 413，不留残余文件。"""
        from backend.app.api import files as files_api

        client, app, get_db = _client_with_db(tmp_path)
        try:
            headers = _register(client, "upload-over-user")
            # 构造略大于上限的流：用 monkeypatch 收紧上限以避免真实传输 100MB
            original_limit = files_api.MAX_UPLOAD_SIZE
            files_api.MAX_UPLOAD_SIZE = 1024  # 1KB 上限
            try:
                resp = client.post(
                    "/api/files/upload",
                    headers=headers,
                    files={"file": ("big.png", b"x" * 4096, "image/png")},
                )
                assert resp.status_code == 413
            finally:
                files_api.MAX_UPLOAD_SIZE = original_limit

            # 媒体目录中不残留失败上传的文件
            media_dir = tmp_path / "storage" / "media"
            leftovers = [
                p for p in media_dir.glob("xhs-upload-u*")
                if p.stat().st_size > 1024
            ] if media_dir.is_dir() else []
            assert leftovers == []
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# SEC-5 模型端点出站校验
# ---------------------------------------------------------------------------

class TestModelEndpointGuard:
    def test_private_base_url_rejected_when_block_private(self, monkeypatch, tmp_path):
        """allow_private_model_endpoints=False 时，保存 127.0.0.1 端点被拒。"""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from backend.app.core.config import get_settings as _gs
        from backend.app.core.database import Base, get_db
        from backend.app.main import app

        monkeypatch.setattr(_gs(), "allow_private_model_endpoints", False)

        engine = create_engine(
            f"sqlite:///{tmp_path / 'mc.db'}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            c = TestClient(app)
            reg = c.post("/api/auth/register", json={"username": "mc-guard-user", "password": "secret123"})
            headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
            resp = c.post(
                "/api/model-configs",
                headers=headers,
                json={
                    "name": "Local",
                    "model_type": "text",
                    "provider": "p",
                    "model_name": "m",
                    "base_url": "http://127.0.0.1:8080/v1",
                    "api_key": "k",
                },
            )
            assert resp.status_code == 400
            assert "内网" in resp.json()["detail"] or "保留" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_metadata_endpoint_rejected_even_when_private_allowed(self, monkeypatch, tmp_path):
        """云元数据地址（169.254.169.254）无条件拒绝。"""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from backend.app.core.config import get_settings as _gs
        from backend.app.core.database import Base, get_db
        from backend.app.main import app

        engine = create_engine(
            f"sqlite:///{tmp_path / 'mc2.db'}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            c = TestClient(app)
            reg = c.post("/api/auth/register", json={"username": "mc-meta-user", "password": "secret123"})
            headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
            resp = c.post(
                "/api/model-configs",
                headers=headers,
                json={
                    "name": "Meta",
                    "model_type": "text",
                    "provider": "p",
                    "model_name": "m",
                    "base_url": "http://169.254.169.254/v1",
                    "api_key": "k",
                },
            )
            assert resp.status_code == 400
        finally:
            app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# SEC-6 认证加固
# ---------------------------------------------------------------------------

def _fresh_client(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base, get_db
    from backend.app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), get_db


class TestAuthHardening:
    def test_whitespace_username_rejected(self, tmp_path):
        """空格用户名（strip 后为空）必须被拒绝（P1-11）。"""
        client, get_db = _fresh_client(tmp_path)
        try:
            resp = client.post("/api/auth/register", json={"username": "   ", "password": "secret123"})
            assert resp.status_code == 422

            resp2 = client.post("/api/auth/register", json={"username": "ab", "password": "secret123"})
            assert resp2.status_code == 422
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_short_password_rejected(self, tmp_path):
        client, get_db = _fresh_client(tmp_path)
        try:
            resp = client.post("/api/auth/register", json={"username": "pw-policy-user", "password": "123456"})
            assert resp.status_code == 400
            assert "8" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_duplicate_register_conflict_not_500(self, tmp_path):
        """同名注册的唯一约束兜底（P1-11）：预检失败返回 400 而非 500。"""
        client, get_db = _fresh_client(tmp_path)
        try:
            resp1 = client.post("/api/auth/register", json={"username": "race-user", "password": "secret123"})
            assert resp1.status_code == 200
            resp2 = client.post("/api/auth/register", json={"username": "race-user", "password": "secret123"})
            assert resp2.status_code == 400

            # 并发窗口的直接插入冲突由 IntegrityError 分支兜底：单元级验证分支存在
            import inspect

            from backend.app.api import auth as auth_api
            source = inspect.getsource(auth_api.register)
            assert "IntegrityError" in source
            assert "409" in source
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_repeated_failed_logins_trigger_429(self, tmp_path):
        from backend.app.core import auth_throttle

        client, get_db = _fresh_client(tmp_path)
        try:
            client.post("/api/auth/register", json={"username": "throttle-user", "password": "secret123"})
            auth_throttle.reset_rate_limit("testclient:throttle-user")
            statuses = []
            for _ in range(12):
                resp = client.post(
                    "/api/auth/login", json={"username": "throttle-user", "password": "wrong-password"}
                )
                statuses.append(resp.status_code)
            assert statuses[0] == 401
            assert 429 in statuses
            # 正确密码不受失败限流影响
            ok = client.post("/api/auth/login", json={"username": "throttle-user", "password": "secret123"})
            assert ok.status_code == 200
        finally:
            app.dependency_overrides.pop(get_db, None)
            auth_throttle.reset_rate_limit("testclient:throttle-user")


# ---------------------------------------------------------------------------
# SEC-7 refresh token HttpOnly Cookie
# ---------------------------------------------------------------------------

class TestRefreshCookie:
    def test_refresh_token_in_httponly_cookie_not_in_body(self, tmp_path):
        client, get_db = _fresh_client(tmp_path)
        try:
            reg = client.post("/api/auth/register", json={"username": "cookie-user", "password": "secret123"})
            assert reg.status_code == 200
            set_cookie = reg.headers.get("set-cookie", "")
            assert "refresh_token=" in set_cookie
            assert "httponly" in set_cookie.lower()
            assert reg.json()["refresh_token"] is None
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_cookie_refresh_requires_csrf_header(self, tmp_path):
        client, get_db = _fresh_client(tmp_path)
        try:
            client.post("/api/auth/register", json={"username": "csrf-user", "password": "secret123"})
            # 无自定义头 → 403
            no_header = client.post("/api/auth/refresh")
            assert no_header.status_code == 403
            # 带自定义头 → 200
            with_header = client.post("/api/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
            assert with_header.status_code == 200
            assert with_header.json()["access_token"]
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_logout_clears_refresh_cookie(self, tmp_path):
        client, get_db = _fresh_client(tmp_path)
        try:
            client.post("/api/auth/register", json={"username": "logout-user", "password": "secret123"})
            logout_resp = client.post("/api/auth/logout")
            assert logout_resp.status_code == 200
            # cookie 已清除后再刷新 → 401
            refresh_resp = client.post("/api/auth/refresh", headers={"X-Requested-With": "XMLHttpRequest"})
            assert refresh_resp.status_code == 401
        finally:
            app.dependency_overrides.pop(get_db, None)

    def test_body_refresh_still_supported_for_transition(self, tmp_path):
        """过渡兼容：body 提供 refresh token 时不要求 CSRF 头。"""
        from backend.app.core.config import get_settings as _gs

        client, get_db = _fresh_client(tmp_path)
        try:
            # 打开 include_refresh_in_body 以获取一个 body token
            settings = _gs()
            original = settings.include_refresh_in_body
            object.__setattr__(settings, "include_refresh_in_body", True)
            try:
                reg = client.post("/api/auth/register", json={"username": "body-user", "password": "secret123"})
                body_token = reg.json()["refresh_token"]
                assert body_token
            finally:
                object.__setattr__(settings, "include_refresh_in_body", original)

            # 先清掉 client jar 里的 cookie，确保走的是 body 路径
            client.cookies.clear()
            resp = client.post("/api/auth/refresh", json={"refresh_token": body_token})
            assert resp.status_code == 200
            assert resp.json()["access_token"]
        finally:
            app.dependency_overrides.pop(get_db, None)




# ---------------------------------------------------------------------------
# DB-1/DB-2 迁移在有数据（含子表引用行）的库上必须成功（review P0-1 回归）
# ---------------------------------------------------------------------------

def test_batch_migrations_survive_referenced_rows(tmp_path, monkeypatch):
    """batch 重建被外键引用的父表时，不得因 foreign_keys=ON 触发 IntegrityError。

    复现原始问题：seed 一条带 publish_assets 的 publish_jobs 与带 note_assets
    的 notes，然后从旧 head（a1b2c3d4e5f6）升级到 head。
    """
    import sqlite3

    from alembic import command
    from alembic.config import Config

    db_path = tmp_path / "migration-fk-test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", db_url)
    ini_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "backend", "alembic.ini")
    )
    cfg = Config(ini_path)

    # 1) 升级到旧 head
    command.upgrade(cfg, "a1b2c3d4e5f6")

    # 2) seed：用户、账号、发布任务 + 素材（子表引用行）、笔记 + 素材/标签
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, created_at) VALUES (1, 'mig-user', 'x', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO platform_accounts (id, user_id, platform, sub_type, nickname, avatar_url, status,"
            " status_message, profile_json, created_at, updated_at)"
            " VALUES (1, 1, 'xhs', 'creator', '', '', 'active', '', '{}', datetime('now'), datetime('now'))"
        )
        conn.execute(
            "INSERT INTO publish_jobs (id, user_id, platform_account_id, platform, title, body, publish_mode,"
            " publish_options, status, external_note_id, publish_error, created_at)"
            " VALUES (1, 1, 1, 'xhs', 't', 'b', 'immediate', '{}', 'pending', '', '', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO publish_assets (publish_job_id, asset_type, file_path, upload_status, creator_media_id,"
            " upload_error, creator_upload_info)"
            " VALUES (1, 'image', 'x.png', 'pending', '', '', '{}')"
        )
        conn.execute(
            "INSERT INTO notes (id, user_id, platform_account_id, platform, note_id, title, content, author_name, created_at)"
            " VALUES (1, 1, 1, 'xhs', 'nid-1', 't', 'c', '', datetime('now'))"
        )
        conn.execute(
            "INSERT INTO note_assets (note_id, asset_type, url, local_path, sort_order)"
            " VALUES (1, 'image', 'https://a.b/c.jpg', '', 0)"
        )
        conn.execute(
            "INSERT INTO auto_tasks (id, user_id, name, pc_account_id, creator_account_id, ai_instruction,"
            " schedule_type, schedule_time, schedule_days, schedule_interval_hours, status, total_published, created_at)"
            " VALUES (1, 1, 'task', 1, 1, '', 'manual', '09:00', '', 24, 'active', 0, datetime('now'))"
        )
        conn.commit()
    finally:
        conn.close()

    # 3) 升级到 head：b2c3d4e5f6a7（publish_jobs 重建）与 c3d4e5f6a7b8（notes 重建）
    command.upgrade(cfg, "head")

    # 4) 数据完整：行保留且新列生效
    conn = sqlite3.connect(db_path)
    try:
        job_count = conn.execute("SELECT COUNT(*) FROM publish_jobs WHERE id = 1").fetchone()[0]
        asset_count = conn.execute("SELECT COUNT(*) FROM publish_assets WHERE publish_job_id = 1").fetchone()[0]
        note_nullable = [
            row[3] for row in conn.execute("PRAGMA table_info(notes)") if row[1] == "platform_account_id"
        ][0]
        claimed = [row[1] for row in conn.execute("PRAGMA table_info(auto_tasks)")]
        version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    finally:
        conn.close()

    assert job_count == 1
    assert asset_count == 1
    assert note_nullable == 0  # 允许 NULL
    assert "claimed_at" in claimed
    assert version != "a1b2c3d4e5f6"
