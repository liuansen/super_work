"""账号列表、Cookie 导入、账号检查与删除测试。

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

def test_account_delete_requires_owner_and_removes_account(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount

    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("delete-account-owner")
        intruder_token = _register_and_get_access_token("delete-account-intruder")
        db = next(app.dependency_overrides[get_db]())
        try:
            account = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="pc",
                external_user_id="delete-user",
                nickname="Delete Me",
                status="active",
            )
            db.add(account)
            db.commit()
            db.refresh(account)
            account_id = account.id
        finally:
            db.close()

        intruder_response = client.delete(
            f"/api/accounts/{account_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        owner_response = client.delete(
            f"/api/accounts/{account_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json() == {"id": account_id, "status": "deleted"}

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert accounts_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_pc_qrcode_requires_platform_login(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.post("/api/xhs/login-sessions/pc/qrcode")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)

def test_accounts_list_requires_platform_login(tmp_path):
    get_db = _override_database(tmp_path)
    try:
        response = client.get("/api/accounts?platform=xhs")
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)

def test_account_cookie_import_creates_account_and_health_check_updates_status(tmp_path):
    from backend.app.api.accounts import get_creator_account_adapter, get_pc_account_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.core.time import shanghai_now
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    fake_adapter = FakeCookieAccountAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FailingCreatorExchangeAdapter()
    try:
        access_token = _register_and_get_access_token("cookie-operator")
        before_create = shanghai_now()

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        after_create = shanghai_now()
        assert import_response.status_code == 200
        imported = import_response.json()
        assert imported["nickname"] == "cookie-cat"
        assert imported["status"] == "active"

        db = next(app.dependency_overrides[get_db]())
        try:
            account = db.query(PlatformAccount).one()
            assert account.external_user_id == "cookie-user-1"
            assert before_create <= account.created_at <= after_create
            assert before_create <= account.updated_at <= after_create
            cookie_version = db.query(AccountCookieVersion).one()
            assert cookie_version.platform_account_id == account.id
            assert decrypt_text(cookie_version.encrypted_cookies) == "a1=cookie-a1; web_session=session"
        finally:
            db.close()

        accounts_response = client.get(
            "/api/accounts?platform=xhs",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert accounts_response.status_code == 200
        assert accounts_response.json()["total"] == 1

        check_response = client.post(
            f"/api/accounts/{imported['id']}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert check_response.status_code == 200
        checked = check_response.json()
        assert checked["status"] == "active"
        assert checked["nickname"] == "cookie-cat"
        assert fake_adapter.calls >= 2
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)

def test_account_cookie_import_for_pc_can_optionally_sync_creator_account(tmp_path):
    from backend.app.api.accounts import get_creator_account_adapter, get_pc_account_adapter
    from backend.app.core.database import get_db
    from backend.app.core.security import decrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    fake_pc_adapter = FakeCookieAccountAdapter()
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_pc_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FakeCreatorLoginAdapter()
    try:
        access_token = _register_and_get_access_token("cookie-auto-creator-operator")

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "platform": "xhs",
                "sub_type": "pc",
                "cookie_string": "a1=cookie-a1; web_session=session",
                "sync_creator": True,
            },
        )
        assert import_response.status_code == 200

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
            creator_cookie = (
                db.query(AccountCookieVersion)
                .filter(AccountCookieVersion.platform_account_id == creator_account.id)
                .order_by(AccountCookieVersion.id.desc())
                .one()
            )
            assert decrypt_text(creator_cookie.encrypted_cookies) == '{"a1":"cookie-a1","customer_session":"session-456"}'
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)

def test_account_check_refreshes_xhs_self_profile_metrics(tmp_path):
    from backend.app.api.accounts import (
        get_creator_account_adapter,
        get_pc_account_adapter,
        get_xhs_self_profile_adapter,
    )

    db_dependency = _override_database(tmp_path)
    fake_adapter = FakeCookieAccountAdapter()
    FakeSelfProfileAdapter.calls = []
    app.dependency_overrides[get_pc_account_adapter] = lambda: fake_adapter
    app.dependency_overrides[get_creator_account_adapter] = lambda: FailingCreatorExchangeAdapter()
    app.dependency_overrides[get_xhs_self_profile_adapter] = lambda: FakeSelfProfileAdapter()
    try:
        access_token = _register_and_get_access_token("profile-metrics-operator")
        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        account_id = import_response.json()["id"]

        check_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert check_response.status_code == 200
        checked = check_response.json()
        assert checked["status"] == "active"
        assert checked["nickname"] == "cookie-cat-live"
        assert checked["avatar_url"] == "https://example.test/live-avatar.webp"
        assert checked["profile"]["followers"] == "90"
        assert checked["profile"]["following"] == "28"
        assert checked["profile"]["likes"] == "340"
        assert checked["profile"]["red_id"] == "red-cookie-1"
        assert FakeSelfProfileAdapter.calls == ["a1=cookie-a1; web_session=session", "a1=cookie-a1; web_session=session"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
        app.dependency_overrides.pop(get_creator_account_adapter, None)
        app.dependency_overrides.pop(get_xhs_self_profile_adapter, None)

def test_account_check_enforces_ownership_and_marks_expired_on_adapter_failure(tmp_path):
    from backend.app.api.accounts import get_pc_account_adapter

    db_dependency = _override_database(tmp_path)
    app.dependency_overrides[get_pc_account_adapter] = lambda: FakeCookieAccountAdapter()
    try:
        owner_token = _register_and_get_access_token("owner-operator")
        intruder_token = _register_and_get_access_token("intruder-operator")

        import_response = client.post(
            "/api/accounts/import-cookie",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "sub_type": "pc", "cookie_string": "a1=cookie-a1; web_session=session"},
        )
        account_id = import_response.json()["id"]

        forbidden_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert forbidden_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_pc_account_adapter, None)

    app.dependency_overrides[get_pc_account_adapter] = lambda: FailingCookieAccountAdapter()
    try:
        expired_response = client.post(
            f"/api/accounts/{account_id}/check",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert expired_response.status_code == 200
        assert expired_response.json()["status"] == "expired"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_pc_account_adapter, None)
