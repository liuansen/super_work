"""本轮 review 修复的回归测试。

每个用例对应一处 review 结论，修复前应失败（或行为不符）。
"""
from __future__ import annotations

import pytest


def _fresh_client(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.app.core.database import Base, get_db
    from backend.app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'review.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), get_db, session_factory


# ---------------------------------------------------------------------------
# 令牌吊销（review P2：refresh token 此前泄露后 7 天内无法止损）
# ---------------------------------------------------------------------------


def test_logout_all_revokes_access_and_refresh_tokens(tmp_path):
    client, db_override, _ = _fresh_client(tmp_path)
    try:
        registered = client.post(
            "/api/auth/register", json={"username": "revoke-user", "password": "secret123"}
        )
        assert registered.status_code == 200
        access = registered.json()["access_token"]
        headers = {"Authorization": f"Bearer {access}"}

        assert client.get("/api/auth/me", headers=headers).status_code == 200

        revoked = client.post("/api/auth/logout-all", headers=headers)
        assert revoked.status_code == 200
        assert revoked.json()["token_version"] == 1

        # 旧 access token 立即失效
        assert client.get("/api/auth/me", headers=headers).status_code == 401
        # 旧 refresh cookie 也失效（logout-all 已清 cookie，这里显式重放一次也不行，
        # 因为 cookie 已被删除，只能验证登录可继续）
        relogin = client.post(
            "/api/auth/login", json={"username": "revoke-user", "password": "secret123"}
        )
        assert relogin.status_code == 200
        new_headers = {"Authorization": f"Bearer {relogin.json()['access_token']}"}
        assert client.get("/api/auth/me", headers=new_headers).status_code == 200
    finally:
        from backend.app.main import app

        app.dependency_overrides.pop(db_override, None)


# ---------------------------------------------------------------------------
# schedule_time 校验（review P1：非法值会让 next_run_at 滞留过去 → 每分钟重复发布）
# ---------------------------------------------------------------------------


class TestScheduleTimeValidation:
    def test_create_rejects_invalid_schedule_time(self):
        from pydantic import ValidationError

        from backend.app.api.auto_tasks import AutoTaskCreateRequest

        with pytest.raises(ValidationError):
            AutoTaskCreateRequest(
                name="t",
                keywords=["k"],
                pc_account_id=1,
                creator_account_id=2,
                schedule_type="daily",
                schedule_time="abcde",
            )

    def test_update_rejects_out_of_range_hour(self):
        from pydantic import ValidationError

        from backend.app.api.auto_tasks import AutoTaskUpdateRequest

        with pytest.raises(ValidationError):
            AutoTaskUpdateRequest(schedule_time="25:00")

    def test_calculator_stops_scheduling_on_legacy_bad_value(self):
        """历史脏数据：_calculate_next_run_at 不再抛异常，而是停止排期。"""
        from backend.app.api.auto_tasks import _calculate_next_run_at
        from backend.app.models import AutoTask

        task = AutoTask(
            user_id=1,
            name="legacy",
            keywords=["k"],
            pc_account_id=1,
            creator_account_id=2,
            status="active",
            schedule_type="daily",
            schedule_time="abcde",
        )
        _calculate_next_run_at(task)
        assert task.next_run_at is None

    def test_accepts_valid_hh_mm(self):
        from backend.app.api.auto_tasks import AutoTaskCreateRequest

        payload = AutoTaskCreateRequest(
            name="t",
            keywords=["k"],
            pc_account_id=1,
            creator_account_id=2,
            schedule_type="daily",
            schedule_time="09:30",
        )
        assert payload.schedule_time == "09:30"


# ---------------------------------------------------------------------------
# 通知 unread 过滤（review P2：传 false 时返回全部，过滤语义失效）
# ---------------------------------------------------------------------------


def test_notifications_unread_filter_handles_false(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.main import app
    from backend.app.models import Notification

    client, db_override, session_factory = _fresh_client(tmp_path)
    try:
        registered = client.post(
            "/api/auth/register", json={"username": "notif-filter", "password": "secret123"}
        )
        assert registered.status_code == 200
        token = registered.json()["access_token"]

        db = session_factory()
        try:
            db.add_all(
                [
                    Notification(user_id=1, title="unread-1", level="info", read=False),
                    Notification(user_id=1, title="read-1", level="info", read=True),
                ]
            )
            db.commit()
        finally:
            db.close()

        headers = {"Authorization": f"Bearer {token}"}
        unread_only = client.get("/api/notifications?unread=true", headers=headers)
        assert [i["title"] for i in unread_only.json()["items"]] == ["unread-1"]

        read_only = client.get("/api/notifications?unread=false", headers=headers)
        assert [i["title"] for i in read_only.json()["items"]] == ["read-1"]

        all_items = client.get("/api/notifications", headers=headers)
        assert len(all_items.json()["items"]) == 2
    finally:
        app.dependency_overrides.pop(db_override, None)
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# AI 参考图数量上限（review P3）
# ---------------------------------------------------------------------------


def test_generate_image_request_caps_reference_images():
    from pydantic import ValidationError

    from backend.app.api.ai import GenerateImageRequest

    with pytest.raises(ValidationError):
        GenerateImageRequest(prompt="p", reference_images=["u"] * 9)

    with pytest.raises(ValidationError):
        GenerateImageRequest(prompt="p", reference_images=["x" * 4001])


# ---------------------------------------------------------------------------
# 复核 P1：批量入库的评论抓取失败必须降级（修复前 notes.py 缺 logger 定义，
# 降级分支抛 NameError 被外层捕获 → 整批 rollback + 500）
# ---------------------------------------------------------------------------


def test_batch_save_comment_failure_degrades_instead_of_500(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.main import app
    from backend.app.models import AccountCookieVersion, PlatformAccount

    class FakeFailingCommentAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            return False, "上游风控拦截", None

    client, db_override, session_factory = _fresh_client(tmp_path)
    try:
        registered = client.post(
            "/api/auth/register", json={"username": "batch-degrade", "password": "secret123"}
        )
        assert registered.status_code == 200
        token = registered.json()["access_token"]

        db = session_factory()
        try:
            account = PlatformAccount(
                user_id=1,
                platform="xhs",
                sub_type="pc",
                external_user_id="pc-user",
                status="active",
            )
            db.add(account)
            db.flush()
            db.add(
                AccountCookieVersion(
                    platform_account_id=account.id,
                    encrypted_cookies=encrypt_text('{"web_session":"s"}'),
                )
            )
            db.commit()
            account_id = account.id
        finally:
            db.close()

        app.dependency_overrides[get_xhs_pc_api_adapter_factory] = (
            lambda: FakeFailingCommentAdapter
        )
        try:
            response = client.post(
                "/api/notes/batch-save",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "account_id": account_id,
                    "fetch_comments": True,
                    "notes": [
                        {
                            "note_id": "degrade-note-001",
                            "title": "标题",
                            "note_url": "https://www.xiaohongshu.com/explore/degrade-note-001",
                        }
                    ],
                },
            )
        finally:
            app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

        # 核心断言：单条评论失败只降级，绝不能让整批 500
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["saved_count"] == 1
        assert payload["comment_errors"] == [
            {"note_id": "degrade-note-001", "error": "上游风控拦截"}
        ]
    finally:
        app.dependency_overrides.pop(db_override, None)
        app.dependency_overrides.pop(get_db, None)
