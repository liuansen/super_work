"""tests/backend 各拆分测试文件共享的辅助函数、假适配器与 TestClient。

由原 tests/backend/test_api.py 顶部内容机械抽取；行为未改动。

``from api_helpers import *`` 可导入本模块 ``__all__`` 中的全部符号
（包含下划线开头的辅助函数）。pytest 的 prepend import 模式会把测试
文件所在目录加入 sys.path，因此无需 ``tests/backend/__init__.py``。
"""
import os
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from backend.app.core.config import get_settings
from backend.app.main import app


client = TestClient(app)


def _parse_sse_response(response):
    import json as _json
    events = []
    done = {}
    for line in response.text.split("\n"):
        if line.startswith("data: "):
            event = _json.loads(line[6:])
            if event.get("type") == "item":
                events.append(event["item"])
            elif event.get("type") == "done":
                done = event
    return {"items": events, **done}

def _override_database(tmp_path):
    from backend.app.core.database import Base, get_db

    engine = create_engine(f"sqlite:///{tmp_path / 'auth-test.db'}", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return get_db

def _register_and_get_access_token(username: str = "operator") -> str:
    response = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]

def _owned_media_fixture(access_token: str, content: bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 64) -> str:
    """在媒体目录创建一个属于该用户的素材文件，返回符合 xhs-*-u{uid}- 前缀的文件名。

    SEC-2 之后发布/草稿素材的本地来源必须携带属主前缀；测试用此辅助
    构造合法素材。
    """
    from backend.app.core.security import decode_token

    user_id = decode_token(access_token)["user_id"]
    media_dir = Path(get_settings().storage_dir) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"xhs-upload-u{user_id}-{uuid4().hex}.png"
    (media_dir / file_name).write_bytes(content)
    return file_name

class FakePcLoginAdapter:
    def create_qrcode(self):
        return {
            "cookies": {"a1": "temp-a1"},
            "qr_id": "qr-123",
            "code": "code-123",
            "qr_url": "https://example.test/qr",
        }

    def check_qrcode_status(self, qr_id, code, cookies):
        assert qr_id == "qr-123"
        assert code == "code-123"
        assert cookies == {"a1": "temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "final-a1", "web_session": "session-123"}}

    def get_user_info(self, cookies):
        assert cookies["web_session"] == "session-123"
        return {
            "external_user_id": "xhs-user-1",
            "nickname": "cat",
            "avatar_url": "https://example.test/avatar.webp",
        }

class FakeCreatorLoginAdapter:
    def create_qrcode(self):
        return {
            "cookies": {"a1": "creator-temp-a1"},
            "qr_id": "creator-qr-123",
            "qr_url": "https://example.test/creator-qr",
        }

    def check_qrcode_status(self, qr_id, cookies):
        assert qr_id == "creator-qr-123"
        assert cookies == {"a1": "creator-temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "creator-final-a1", "customer_session": "session-456"}}

    def get_user_info(self, cookies):
        assert cookies["customer_session"] == "session-456"
        return {
            "external_user_id": "creator-user-1",
            "nickname": "creator-cat",
            "avatar_url": "https://example.test/creator-avatar.webp",
        }

    def exchange_from_user_cookies(self, user_cookies):
        assert user_cookies["a1"] in {"final-a1", "phone-final-a1", "cookie-a1"}
        return {"status": "confirmed", "cookies": {"a1": user_cookies["a1"], "customer_session": "session-456"}}

class FailingCreatorExchangeAdapter(FakeCreatorLoginAdapter):
    def exchange_from_user_cookies(self, user_cookies):
        raise RuntimeError("creator exchange failed")

class FailingQrLoginAdapter:
    def create_qrcode(self):
        raise RuntimeError("proxy refused while creating qrcode")

class FakePhoneLoginAdapter:
    def create_phone_session(self, phone):
        assert phone == "13800138000"
        return {"cookies": {"a1": "phone-temp-a1"}, "message": "sent"}

    def confirm_phone_login(self, phone, code, cookies):
        assert phone == "13800138000"
        assert code == "123456"
        assert cookies == {"a1": "phone-temp-a1"}
        return {"status": "confirmed", "cookies": {"a1": "phone-final-a1", "web_session": "phone-session"}}

    def get_user_info(self, cookies):
        assert cookies["web_session"] == "phone-session"
        return {
            "external_user_id": "phone-user-1",
            "nickname": "phone-cat",
            "avatar_url": "https://example.test/phone-avatar.webp",
        }

class FakeCookieAccountAdapter:
    def __init__(self):
        self.calls = 0

    def get_user_info(self, cookies):
        self.calls += 1
        assert cookies["a1"] == "cookie-a1"
        return {
            "external_user_id": "cookie-user-1",
            "nickname": "cookie-cat",
            "avatar_url": "https://example.test/cookie-avatar.webp",
        }

class FakeSelfProfileAdapter:
    calls = []

    def get_self_profile(self, cookies_text):
        self.__class__.calls.append(cookies_text)
        return {
            "success": True,
            "msg": "ok",
            "data": {
                "basic_info": {
                    "nickname": "cookie-cat-live",
                    "images": "https://example.test/live-avatar.webp",
                    "red_id": "red-cookie-1",
                    "desc": "live profile",
                    "ip_location": "上海",
                },
                "interactions": [
                    {"type": "follows", "name": "关注", "count": "28", "i18n_count": "28"},
                    {"type": "fans", "name": "粉丝", "count": "90", "i18n_count": "90"},
                    {"type": "interaction", "name": "获赞与收藏", "count": "340", "i18n_count": "340"},
                ],
            },
            "code": 0,
        }

class FailingCookieAccountAdapter:
    def get_user_info(self, cookies):
        raise RuntimeError("expired")

class FakeXhsPcSearchAdapter:
    calls = []

    def __init__(self, cookies):
        self.cookies = cookies

    def search_note(self, keyword, page=1, **kwargs):
        self.__class__.calls.append({"cookies": self.cookies, "keyword": keyword, "page": page, **kwargs})
        return (
            True,
            "ok",
            {
                "success": True,
                "msg": "ok",
                "data": {
                    "has_more": True,
                    "items": [
                        {
                            "model_type": "note",
                            "xsec_token": "xsec-search-001",
                            "note_card": {
                                "note_id": "note-001",
                                "display_title": "低卡早餐搜索笔记",
                                "desc": "适合工作日的早餐搭配",
                                "type": "normal",
                                "user": {
                                    "user_id": "author-001",
                                    "nickname": "早餐研究员",
                                    "avatar": "https://example.test/avatar.webp",
                                },
                                "cover": {"url_default": "https://example.test/cover.webp"},
                                "interact_info": {
                                    "liked_count": "1234",
                                    "collected_count": "456",
                                    "comment_count": "78",
                                    "share_count": "9",
                                },
                            },
                        }
                    ],
                },
            },
        )

def _create_pc_account_with_cookie(tmp_path, username="search-owner"):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    access_token = _register_and_get_access_token(username)
    db = next(app.dependency_overrides[get_db]())
    try:
        account = PlatformAccount(
            user_id=1,
            platform="xhs",
            sub_type="pc",
            external_user_id="search-user",
            nickname="搜索账号",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"a1":"json-a1","web_session":"json-session"}'),
            )
        )
        db.commit()
        account_id = account.id
    finally:
        db.close()
    return db_dependency, access_token, account_id

def _create_creator_account_with_cookie(tmp_path, username="creator-owner"):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency = _override_database(tmp_path)
    access_token = _register_and_get_access_token(username)
    db = next(app.dependency_overrides[get_db]())
    try:
        account = PlatformAccount(
            user_id=1,
            platform="xhs",
            sub_type="creator",
            external_user_id="creator-user",
            nickname="Creator account",
            status="active",
        )
        db.add(account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=account.id,
                encrypted_cookies=encrypt_text('{"web_session":"creator-session","a1":"creator-a1"}'),
            )
        )
        db.commit()
        account_id = account.id
    finally:
        db.close()
    return db_dependency, access_token, account_id


__all__ = [
    "client",
    "app",
    "_parse_sse_response",
    "_override_database",
    "_register_and_get_access_token",
    "_owned_media_fixture",
    "FakePcLoginAdapter",
    "FakeCreatorLoginAdapter",
    "FailingCreatorExchangeAdapter",
    "FailingQrLoginAdapter",
    "FakePhoneLoginAdapter",
    "FakeCookieAccountAdapter",
    "FakeSelfProfileAdapter",
    "FailingCookieAccountAdapter",
    "FakeXhsPcSearchAdapter",
    "_create_pc_account_with_cookie",
    "_create_creator_account_with_cookie",
    "get_settings",
]
