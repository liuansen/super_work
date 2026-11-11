"""XHS 扫码与手机号登录会话（含并发/幂等/损坏状态）测试。

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

def test_xhs_pc_qrcode_login_session_persists_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token()

        create_response = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["status"] == "pending"
        assert created["qr_url"] == "https://example.test/qr"
        assert created["qr_image_data_url"].startswith("data:image/png;base64,")
        assert isinstance(created["session_id"], int)

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, created["session_id"])
            assert stored_session.platform == "xhs"
            assert stored_session.sub_type == "pc"
            assert stored_session.qr_id == "qr-123"
            assert stored_session.code == "code-123"
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"temp-a1"}'
        finally:
            db.close()

        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert poll_response.status_code == 200
        polled = poll_response.json()
        assert polled["status"] == "confirmed"
        assert polled["account"]["nickname"] == "cat"
        assert polled["creator_account"] is None

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert accounts_response.status_code == 200
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["nickname"] == "cat"
        assert accounts_payload["items"][0]["sub_type"] == "pc"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.platform == "xhs"
            assert account.sub_type == "pc"
            assert account.external_user_id == "xhs-user-1"
            cookie_version = db.query(AccountCookieVersion).one()
            assert cookie_version.platform_account_id == account.id
            assert decrypt_text(cookie_version.encrypted_cookies) == '{"a1":"final-a1","web_session":"session-123"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_pc_qrcode_login_updates_existing_account_for_same_external_user(tmp_path):
    from backend.app.api.accounts import get_pc_account_adapter
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("qr-upsert-operator")

        first_create = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        first_poll = client.get(
            f"/api/xhs/login-sessions/{first_create['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert first_poll.status_code == 200
        assert first_poll.json()["account"]["action"] == "created"

        second_create = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        ).json()
        second_poll = client.get(
            f"/api/xhs/login-sessions/{second_create['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert second_poll.status_code == 200
        assert second_poll.json()["account"]["action"] == "updated"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["updated_at"]
        assert accounts_payload["items"][0]["profile"] == {}

        check_response = client.post(
            f"/api/accounts/{accounts_payload['items'][0]['id']}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert check_response.status_code == 200
        assert check_response.json()["status"] == "active", check_response.json().get("status_message")

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).all()
            assert len(accounts) == 1
            cookie_versions = db.query(AccountCookieVersion).order_by(AccountCookieVersion.id).all()
            assert len(cookie_versions) == 2
            assert cookie_versions[-1].platform_account_id == accounts[0].id
            assert decrypt_text(cookie_versions[-1].encrypted_cookies) == '{"a1":"final-a1","web_session":"session-123"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_creator_qrcode_login_session_persists_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("creator-operator")

        create_response = client.post(
            "/api/xhs/login-sessions/creator/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["status"] == "pending"
        assert created["qr_url"] == "https://example.test/creator-qr"
        assert created["qr_image_data_url"].startswith("data:image/png;base64,")

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, created["session_id"])
            assert stored_session.platform == "xhs"
            assert stored_session.sub_type == "creator"
            assert stored_session.qr_id == "creator-qr-123"
            assert stored_session.code is None
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"creator-temp-a1"}'
        finally:
            db.close()

        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert poll_response.status_code == 200
        polled = poll_response.json()
        assert polled["status"] == "confirmed"
        assert polled["account"]["nickname"] == "creator-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 1
        assert accounts_payload["items"][0]["sub_type"] == "creator"
        assert accounts_payload["items"][0]["nickname"] == "creator-cat"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.sub_type == "creator"
            assert account.external_user_id == "creator-user-1"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_pc_qrcode_reports_adapter_failure_as_bad_gateway(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FailingQrLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("qr-failure-operator")
        response = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 502
        assert "proxy refused" in response.json()["detail"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_pc_qrcode_login_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("pc-auto-creator-operator")

        created = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"sync_creator": True},
        ).json()
        poll_response = client.get(
            f"/api/xhs/login-sessions/{created['session_id']}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert poll_response.status_code == 200
        payload = poll_response.json()
        assert payload["status"] == "confirmed"
        assert payload["account"]["sub_type"] == "pc"
        assert payload["creator_account"]["sub_type"] == "creator"
        assert payload["creator_account"]["nickname"] == "creator-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["total"] == 2
        assert {item["sub_type"] for item in accounts_payload["items"]} == {"pc", "creator"}

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).order_by(PlatformAccount.sub_type.asc()).all()
            assert len(accounts) == 2
            creator_account = next(account for account in accounts if account.sub_type == "creator")
            assert creator_account.external_user_id == "creator-user-1"
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"final-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_pc_phone_login_session_sends_code_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePhoneLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("phone-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/pc/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000"},
        )
        assert send_response.status_code == 200
        sent = send_response.json()
        assert sent["status"] == "pending"
        assert sent["message"] == "sent"

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, sent["session_id"])
            assert stored_session.sub_type == "pc"
            assert stored_session.login_method == "phone"
            assert stored_session.phone_mask == "138****8000"
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"a1":"phone-temp-a1"}'
        finally:
            db.close()

        confirm_response = client.post(
            "/api/xhs/login-sessions/pc/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["nickname"] == "phone-cat"
        assert confirmed["creator_account"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.sub_type == "pc"
            assert account.external_user_id == "phone-user-1"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_pc_phone_login_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePhoneLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("phone-auto-creator-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/pc/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000", "sync_creator": True},
        )
        assert send_response.status_code == 200
        sent = send_response.json()

        db = next(app.dependency_overrides[get_db]())
        try:
            stored_session = db.get(LoginSession, sent["session_id"])
            assert decrypt_text(stored_session.encrypted_temp_cookies) == '{"cookies":{"a1":"phone-temp-a1"},"sync_creator":true}'
        finally:
            db.close()

        confirm_response = client.post(
            "/api/xhs/login-sessions/pc/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["sub_type"] == "pc"
        assert confirmed["creator_account"]["sub_type"] == "creator"
        assert confirmed["creator_account"]["nickname"] == "creator-cat"

        db = next(app.dependency_overrides[get_db]())
        try:
            accounts = db.query(PlatformAccount).order_by(PlatformAccount.sub_type.asc()).all()
            assert len(accounts) == 2
            creator_account = next(account for account in accounts if account.sub_type == "creator")
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"phone-final-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_xhs_creator_phone_login_session_sends_code_and_confirms_account(tmp_path):
    from backend.app.api.login_sessions import get_creator_login_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_creator_login_adapter] = lambda: FakePhoneLoginAdapter()
    try:
        access_token = _register_and_get_access_token("creator-phone-operator")

        send_response = client.post(
            "/api/xhs/login-sessions/creator/phone/send-code",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"phone": "13800138000"},
        )
        assert send_response.status_code == 200
        sent = send_response.json()
        assert sent["status"] == "pending"

        confirm_response = client.post(
            "/api/xhs/login-sessions/creator/phone/confirm",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"session_id": sent["session_id"], "phone": "13800138000", "code": "123456"},
        )
        assert confirm_response.status_code == 200
        confirmed = confirm_response.json()
        assert confirmed["status"] == "confirmed"
        assert confirmed["account"]["nickname"] == "phone-cat"

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        accounts_payload = accounts_response.json()
        assert accounts_payload["items"][0]["sub_type"] == "creator"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_qr_login_poll_is_idempotent_after_user_info_failure(tmp_path):
    """扫码确认后取账号信息失败 → 502；再次轮询不应重复换取二维码，应续跑成功。"""
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.models import LoginSession

    class FlakyUserInfoAdapter:
        check_calls = 0
        userinfo_calls = 0

        def create_qrcode(self):
            return {"cookies": {"a1": "temp-a1"}, "qr_id": "qr-flaky", "code": "code-flaky",
                    "qr_url": "https://example.test/qr-flaky"}

        def check_qrcode_status(self, qr_id, code, cookies):
            type(self).check_calls += 1
            return {"status": "confirmed", "cookies": {"a1": "final-a1", "web_session": "session-flaky"}}

        def get_user_info(self, cookies):
            type(self).userinfo_calls += 1
            if type(self).userinfo_calls == 1:
                raise RuntimeError("upstream user/me busy")
            return {"external_user_id": "flaky-user", "nickname": "flaky-cat", "avatar_url": ""}

    db_dependency = _override_database(tmp_path)
    adapter = FlakyUserInfoAdapter()
    app.dependency_overrides[get_pc_login_adapter] = lambda: adapter
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        token = _register_and_get_access_token("qr-flaky-owner")
        created = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        session_id = created["session_id"]

        first = client.get(
            f"/api/xhs/login-sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert first.status_code == 502
        assert "获取账号信息失败" in first.json()["detail"]

        # 会话不能被错误地置为终态：仍可重试
        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(LoginSession, session_id)
            assert session.status == "scanned"
        finally:
            db.close()

        second = client.get(
            f"/api/xhs/login-sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert second.status_code == 200, second.text
        payload = second.json()
        assert payload["status"] == "confirmed"
        assert payload["account"]["nickname"] == "flaky-cat"
        # 二维码只换取一次
        assert FlakyUserInfoAdapter.check_calls == 1
        assert FlakyUserInfoAdapter.userinfo_calls == 2
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_qr_login_concurrent_poll_does_not_hit_upstream_twice(tmp_path):
    """并发轮询：同一会话已有请求在处理时，另一次轮询直接复用状态，不再打上游。"""
    from backend.app.api.login_sessions import (
        _session_lock,
        get_creator_login_adapter,
        get_pc_login_adapter,
    )

    class CountingAdapter:
        check_calls = 0

        def create_qrcode(self):
            return {"cookies": {"a1": "temp-a1"}, "qr_id": "qr-conc", "code": "code-conc",
                    "qr_url": "https://example.test/qr-conc"}

        def check_qrcode_status(self, qr_id, code, cookies):
            type(self).check_calls += 1
            return {"status": "scanned", "cookies": cookies}

        def get_user_info(self, cookies):
            return {"external_user_id": "conc-user", "nickname": "conc", "avatar_url": ""}

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: CountingAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        token = _register_and_get_access_token("qr-conc-owner")
        created = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        session_id = created["session_id"]

        lock = _session_lock(session_id)
        acquired = lock.acquire(blocking=False)
        assert acquired
        try:
            busy = client.get(
                f"/api/xhs/login-sessions/{session_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            lock.release()
        assert busy.status_code == 200
        assert busy.json().get("polling") is True
        assert CountingAdapter.check_calls == 0

        normal = client.get(
            f"/api/xhs/login-sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert normal.status_code == 200
        assert normal.json()["status"] == "scanned"
        assert CountingAdapter.check_calls == 1
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)

def test_qr_login_poll_with_undecryptable_state_expires_session(tmp_path):
    """密钥变更/数据损坏导致无法解密时，返回 409 并将会话置为 expired（而非 500）。"""
    from backend.app.api.login_sessions import get_creator_login_adapter, get_pc_login_adapter
    from backend.app.core.database import get_db
    from backend.app.models import LoginSession

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_login_adapter] = lambda: FakePcLoginAdapter()
    app.dependency_overrides[get_creator_login_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        token = _register_and_get_access_token("qr-badtoken-owner")
        created = client.post(
            "/api/xhs/login-sessions/pc/qrcode",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        session_id = created["session_id"]

        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(LoginSession, session_id)
            session.encrypted_temp_cookies = "not-a-valid-fernet-token"
            db.commit()
        finally:
            db.close()

        response = client.get(
            f"/api/xhs/login-sessions/{session_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409
        assert "密钥" in response.json()["detail"]

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(LoginSession, session_id).status == "expired"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_login_adapter, None)
        app.dependency_overrides.pop(get_creator_login_adapter, None)
