"""任务、调度状态、通知与少量纯函数回归测试。

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

def test_tasks_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/tasks?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_tasks_api_lists_only_current_user_tasks_and_filters_platform(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("task-owner")
    intruder_token = _register_and_get_access_token("task-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="ai_rewrite",
                        status="completed",
                        progress=100,
                        payload={"draft_id": 11},
                    ),
                    Task(
                        user_id=1,
                        platform="douyin",
                        task_type="crawl",
                        status="pending",
                        progress=0,
                        payload={"keyword": "demo"},
                    ),
                    Task(
                        user_id=2,
                        platform="xhs",
                        task_type="publish",
                        status="failed",
                        progress=100,
                        payload={"error": "nope"},
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        owner_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        owner_payload = owner_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["platform"] == "xhs"
        assert owner_payload["items"][0]["task_type"] == "ai_rewrite"
        assert owner_payload["items"][0]["payload"] == {"draft_id": 11}

        intruder_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total"] == 1
        assert intruder_response.json()["items"][0]["task_type"] == "publish"
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_scheduler_status_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/tasks/scheduler/status")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_scheduler_status_reports_config_and_recent_owned_scheduler_tasks(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("scheduler-status-owner")
    _register_and_get_access_token("scheduler-status-other")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="monitoring_refresh",
                        status="completed",
                        progress=100,
                        payload={"scheduler": True, "target_id": 1},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="ai_rewrite",
                        status="completed",
                        progress=100,
                        payload={"draft_id": 10},
                    ),
                    Task(
                        user_id=1,
                        platform="xhs",
                        task_type="monitoring_refresh",
                        status="pending",
                        progress=0,
                        payload={"target_id": 2},
                    ),
                    Task(
                        user_id=2,
                        platform="xhs",
                        task_type="creator_publish_scheduler",
                        status="completed",
                        progress=100,
                        payload={"publish_job_id": 99},
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/tasks/scheduler/status",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["enabled"] is False
        assert payload["running"] is False
        assert payload["interval_seconds"] == 60
        assert payload["jobs"] == []
        assert [task["task_type"] for task in payload["recent_tasks"]] == ["monitoring_refresh"]
        assert payload["recent_tasks"][0]["payload"] == {"scheduler": True, "target_id": 1}
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_tasks_detail_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("task-detail-owner")
    intruder_token = _register_and_get_access_token("task-detail-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            task = Task(
                user_id=1,
                platform="xhs",
                task_type="ai_rewrite",
                status="completed",
                progress=100,
                payload={"draft_id": 22},
            )
            db.add(task)
            db.commit()
            task_id = task.id
        finally:
            db.close()

        owner_response = client.get(
            f"/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json()["id"] == task_id
        assert owner_response.json()["payload"] == {"draft_id": 22}

        intruder_response = client.get(
            f"/api/tasks/{task_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_task_execution_fields_and_retry_with_exhausted_status(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import Task

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("task-fields-user")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            now = shanghai_now()
            parent = Task(
                user_id=1, platform="xhs", task_type="monitoring_crawl",
                status="completed", progress=100,
                started_at=now, finished_at=now,
            )
            child = Task(
                user_id=1, platform="xhs", task_type="note_crawl",
                status="failed", progress=0, error_type="network",
                retry_count=2, max_retries=3,
                started_at=now, finished_at=now,
            )
            db.add(parent)
            db.flush()
            child.parent_task_id = parent.id
            db.add(child)
            db.commit()
            parent_id, child_id = parent.id, child.id
        finally:
            db.close()

        detail = client.get(f"/api/tasks/{parent_id}", headers={"Authorization": f"Bearer {token}"})
        assert detail.status_code == 200
        body = detail.json()
        assert body["started_at"] is not None
        assert body["finished_at"] is not None
        assert body["duration_ms"] is not None
        assert body["duration_ms"] >= 0
        assert len(body["children"]) == 1
        assert body["children"][0]["id"] == child_id
        assert body["children"][0]["error_type"] == "network"

        child_detail = client.get(f"/api/tasks/{child_id}", headers={"Authorization": f"Bearer {token}"})
        assert child_detail.json()["parent_task_id"] == parent_id
        assert child_detail.json()["retry_count"] == 2
        assert child_detail.json()["max_retries"] == 3

        retry = client.post(f"/api/tasks/{child_id}/retry", headers={"Authorization": f"Bearer {token}"})
        assert retry.status_code == 200
        assert retry.json()["status"] == "pending"
        assert retry.json()["retry_count"] == 3
        assert retry.json()["error_type"] is None

        db2 = next(app.dependency_overrides[get_db]())
        try:
            t = db2.get(Task, child_id)
            t.status = "exhausted"
            t.error_type = "network"
            db2.commit()
        finally:
            db2.close()

        exhausted_retry = client.post(f"/api/tasks/{child_id}/retry", headers={"Authorization": f"Bearer {token}"})
        assert exhausted_retry.status_code == 200
        assert exhausted_retry.json()["status"] == "pending"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/drafts/1/send-to-publish", json={"platform_account_id": 1})

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notifications_crud_and_trigger_helpers(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Notification, Task
    from backend.app.services.notification_service import notify_task_failed, notify_task_exhausted

    db_dependency = _override_database(tmp_path)
    token = _register_and_get_access_token("notif-user")
    other_token = _register_and_get_access_token("notif-other")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            task = Task(user_id=1, platform="xhs", task_type="ai_rewrite", status="failed", error_type="network")
            db.add(task)
            db.flush()
            n1 = notify_task_failed(db, task)
            task.status = "exhausted"
            n2 = notify_task_exhausted(db, task)
            other_n = Notification(user_id=2, title="other", level="info")
            db.add(other_n)
            db.commit()
        finally:
            db.close()

        unauth = client.get("/api/notifications")
        assert unauth.status_code == 401

        listing = client.get("/api/notifications", headers={"Authorization": f"Bearer {token}"})
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 2
        levels = {items[0]["level"], items[1]["level"]}
        assert levels == {"warning", "error"}

        unread_only = client.get("/api/notifications?unread=true", headers={"Authorization": f"Bearer {token}"})
        assert len(unread_only.json()["items"]) == 2

        mark = client.post(f"/api/notifications/{items[0]['id']}/read", headers={"Authorization": f"Bearer {token}"})
        assert mark.status_code == 200
        assert mark.json()["read"] is True

        unread_after = client.get("/api/notifications?unread=true", headers={"Authorization": f"Bearer {token}"})
        assert len(unread_after.json()["items"]) == 1

        mark_all = client.post("/api/notifications/read-all", headers={"Authorization": f"Bearer {token}"})
        assert mark_all.status_code == 200
        assert mark_all.json()["marked"] == 1

        other_listing = client.get("/api/notifications", headers={"Authorization": f"Bearer {other_token}"})
        assert len(other_listing.json()["items"]) == 1

        cross_mark = client.post(f"/api/notifications/{items[0]['id']}/read", headers={"Authorization": f"Bearer {other_token}"})
        assert cross_mark.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_ai_generate_titles_keeps_leading_digits():
    """P2 回归：标题清洗不能把开头的数字一并剥掉（"3天瘦5斤"→"天瘦5斤"）。"""
    from backend.app.services.ai_service import _ORDERED_LIST_PREFIX_RE

    cases = {
        "1. 3天瘦5斤": "3天瘦5斤",
        "2、TOP10 必买": "TOP10 必买",
        "3) 5分钟早餐": "5分钟早餐",
        "7天自律计划": "7天自律计划",
        "- 干货分享": "干货分享",
    }
    for raw, expected in cases.items():
        assert _ORDERED_LIST_PREFIX_RE.sub("", raw).strip() == expected, raw

def test_scheduled_at_with_offset_normalized_to_beijing_naive():
    """P1 回归：带时区偏移的定时时间统一转为 naive 北京时间。"""
    from datetime import datetime

    from backend.app.api.publish import PublishJobUpdateRequest

    payload = PublishJobUpdateRequest(scheduled_at=datetime.fromisoformat("2026-11-11T20:00:00+08:00"))
    assert payload.scheduled_at == datetime(2026, 11, 11, 20, 0)

    # UTC 12:00 == 北京 20:00
    payload_utc = PublishJobUpdateRequest(scheduled_at=datetime.fromisoformat("2026-11-11T12:00:00+00:00"))
    assert payload_utc.scheduled_at == datetime(2026, 11, 11, 20, 0)

    # naive 值按北京时间原样保留
    payload_naive = PublishJobUpdateRequest(scheduled_at=datetime(2026, 11, 11, 20, 0))
    assert payload_naive.scheduled_at == datetime(2026, 11, 11, 20, 0)
