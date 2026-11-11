"""监控目标 CRUD / 刷新与全用户监控刷新测试。

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

def test_monitoring_targets_crud_are_user_scoped(tmp_path):
    db_dependency = _override_database(tmp_path)
    owner_token = _register_and_get_access_token("monitoring-owner")
    intruder_token = _register_and_get_access_token("monitoring-intruder")
    try:
        anonymous_response = client.get("/api/xhs/monitoring/targets")
        assert anonymous_response.status_code == 401

        create_response = client.post(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "target_type": "keyword",
                "name": "早餐趋势",
                "value": "低卡早餐",
                "config": {"frequency": "daily"},
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["target_type"] == "keyword"
        assert created["name"] == "早餐趋势"
        assert created["value"] == "低卡早餐"
        assert created["status"] == "active"

        owner_list_response = client.get(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        update_response = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐趋势组", "status": "paused"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "早餐趋势组"
        assert update_response.json()["status"] == "paused"

        intruder_update_response = client.patch(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "偷看"},
        )
        assert intruder_update_response.status_code == 404

        delete_response = client.delete(
            f"/api/xhs/monitoring/targets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json() == {"id": created["id"], "status": "deleted"}
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_monitoring_targets_refresh_creates_owned_task(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeMonitoringAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_user_notes(self, user_url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawled-note-001",
                                "display_title": "竞品账号低卡早餐",
                                "desc": "creator-001 的早餐选题",
                                "user": {"nickname": "creator-001"},
                                "interact_info": {"liked_count": 50, "collected_count": 20, "comment_count": 3},
                                "cover": {"url": "https://img.example/cover.png"},
                            }
                        }
                    ],
                    "total": 1,
                    "has_more": False,
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "monitoring-refresh-owner")
    intruder_token = _register_and_get_access_token("monitoring-refresh-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeMonitoringAdapter
    try:
        created = client.post(
            "/api/xhs/monitoring/targets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"target_type": "account", "name": "竞品账号", "value": "creator-001"},
        ).json()

        refresh_response = client.post(
            f"/api/xhs/monitoring/targets/{created['id']}/refresh",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert refresh_response.status_code == 200
        payload = refresh_response.json()
        assert payload["target"]["id"] == created["id"]
        assert payload["task"]["task_type"] == "monitoring_crawl"
        assert payload["task"]["status"] == "completed"
        assert payload["task"]["payload"]["target_id"] == created["id"]
        assert payload["task"]["payload"]["crawled_count"] == 1
        assert payload["snapshot"]["payload"]["matched_count"] >= 1
        assert payload["snapshot"]["payload"]["top_notes"][0]["note_id"] == "crawled-note-001"
        assert payload["target"]["consecutive_failures"] == 0

        tasks_response = client.get(
            "/api/tasks?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tasks_response.status_code == 200
        assert tasks_response.json()["items"][0]["task_type"] == "monitoring_crawl"

        notes_response = client.get(
            f"/api/xhs/monitoring/targets/{created['id']}/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert notes_response.status_code == 200
        assert len(notes_response.json()["items"]) >= 1

        snapshots_response = client.get(
            f"/api/xhs/monitoring/targets/{created['id']}/snapshots",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert snapshots_response.status_code == 200
        assert snapshots_response.json()["items"][0]["payload"]["matched_count"] >= 1

        intruder_response = client.post(
            f"/api/xhs/monitoring/targets/{created['id']}/refresh",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_run_monitoring_refresh_for_all_users_refreshes_active_targets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import MonitoringSnapshot, MonitoringTarget, Note, PlatformAccount, Task
    from backend.app.services.scheduler_service import run_monitoring_refresh_for_all_users

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(
        tmp_path, "scheduled-monitor-owner"
    )
    _register_and_get_access_token("scheduled-monitor-second")
    db = next(app.dependency_overrides[get_db]())
    try:
        second_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="pc",
            external_user_id="second-pc",
            nickname="Second PC",
            status="active",
        )
        db.add(second_account)
        db.flush()
        db.add_all(
            [
                Note(
                    user_id=1,
                    platform_account_id=owner_account_id,
                    platform="xhs",
                    note_id="monitor-auto-owner",
                    title="低卡早餐自动监控",
                    content="适合通勤的低卡早餐",
                    author_name="owner-author",
                    raw_json={"likes": 20, "collects": 5, "comments": 2, "shares": 1},
                ),
                Note(
                    user_id=2,
                    platform_account_id=second_account.id,
                    platform="xhs",
                    note_id="monitor-auto-second",
                    title="低卡早餐第二用户",
                    content="第二用户的低卡早餐",
                    author_name="second-author",
                    raw_json={"likes": 100},
                ),
            ]
        )
        active_owner = MonitoringTarget(
            user_id=1,
            platform="xhs",
            target_type="keyword",
            name="Owner breakfast",
            value="低卡早餐",
            status="active",
        )
        paused_owner = MonitoringTarget(
            user_id=1,
            platform="xhs",
            target_type="keyword",
            name="Paused breakfast",
            value="低卡早餐",
            status="paused",
        )
        active_second = MonitoringTarget(
            user_id=2,
            platform="xhs",
            target_type="keyword",
            name="Second breakfast",
            value="低卡早餐",
            status="active",
        )
        db.add_all([active_owner, paused_owner, active_second])
        db.commit()
        active_owner_id = active_owner.id
        paused_owner_id = paused_owner.id
        active_second_id = active_second.id
    finally:
        db.close()

    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            result = run_monitoring_refresh_for_all_users(db=db, now=datetime.utcnow(), platform="xhs")

            assert result["refreshed_count"] == 2
            assert result["items"][0]["target_id"] in {active_owner_id, active_second_id}
            assert db.get(MonitoringTarget, active_owner_id).last_refreshed_at is not None
            assert db.get(MonitoringTarget, active_second_id).last_refreshed_at is not None
            assert db.get(MonitoringTarget, paused_owner_id).last_refreshed_at is None
            owner_snapshot = db.scalars(
                select(MonitoringSnapshot).where(MonitoringSnapshot.target_id == active_owner_id)
            ).one()
            second_snapshot = db.scalars(
                select(MonitoringSnapshot).where(MonitoringSnapshot.target_id == active_second_id)
            ).one()
            assert owner_snapshot.payload["matched_count"] == 1
            assert owner_snapshot.payload["total_engagement"] == 28
            assert second_snapshot.payload["matched_count"] == 1
            assert second_snapshot.payload["total_engagement"] == 100
            tasks = db.query(Task).filter(Task.task_type == "monitoring_refresh").all()
            assert len(tasks) == 2
            assert {task.user_id for task in tasks} == {1, 2}
            assert all(task.status == "completed" for task in tasks)
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
