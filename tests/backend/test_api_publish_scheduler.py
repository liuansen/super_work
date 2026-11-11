"""发布重试/取消、到期任务调度、任务领取与对账测试。

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

def test_publish_job_retry_and_cancel_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        retry_response = client.post("/api/publish/jobs/1/retry")
        cancel_response = client.post("/api/publish/jobs/1/cancel")

        assert retry_response.status_code == 401
        assert cancel_response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_retry_resets_failed_job_and_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob, Task

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-retry-owner"
    )
    intruder_token = _register_and_get_access_token("publish-retry-intruder")
    db = next(app.dependency_overrides[get_db]())
    try:
        failed_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Failed title",
            body="Failed body",
            status="failed",
            external_note_id="old-note",
            publish_error="creator denied",
            published_at=datetime.utcnow(),
        )
        db.add(failed_job)
        db.commit()
        db.refresh(failed_job)
        job_id = failed_job.id
    finally:
        db.close()

    try:
        forbidden_response = client.post(
            f"/api/publish/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert forbidden_response.status_code == 404

        retry_response = client.post(
            f"/api/publish/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert retry_response.status_code == 200
        retried = retry_response.json()
        assert retried["status"] == "pending"
        assert retried["publish_error"] == ""
        assert retried["external_note_id"] == ""
        assert retried["published_at"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish_retry").one()
            assert task.user_id == 1
            assert task.status == "pending"
            assert task.progress == 0
            assert task.payload["publish_job_id"] == job_id
            assert db.get(PublishJob, job_id).status == "pending"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_cancel_transitions_pending_or_scheduled_and_rejects_locked(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob, Task

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-cancel-owner"
    )
    db = next(app.dependency_overrides[get_db]())
    try:
        pending_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Pending title",
            body="Pending body",
            status="pending",
        )
        scheduled_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Scheduled title",
            body="Scheduled body",
            publish_mode="scheduled",
            status="scheduled",
            scheduled_at=datetime.utcnow(),
        )
        published_job = PublishJob(
            user_id=1,
            platform_account_id=creator_account_id,
            platform="xhs",
            title="Published title",
            body="Published body",
            status="published",
        )
        db.add_all([pending_job, scheduled_job, published_job])
        db.commit()
        db.refresh(pending_job)
        db.refresh(scheduled_job)
        db.refresh(published_job)
        pending_id = pending_job.id
        scheduled_id = scheduled_job.id
        published_id = published_job.id
    finally:
        db.close()

    try:
        pending_response = client.post(
            f"/api/publish/jobs/{pending_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        scheduled_response = client.post(
            f"/api/publish/jobs/{scheduled_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        locked_response = client.post(
            f"/api/publish/jobs/{published_id}/cancel",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert pending_response.status_code == 200
        assert pending_response.json()["status"] == "cancelled"
        assert scheduled_response.status_code == 200
        assert scheduled_response.json()["status"] == "cancelled"
        assert locked_response.status_code == 400
        assert locked_response.json()["detail"] == "Publish job cannot be cancelled"

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(PublishJob, pending_id).status == "cancelled"
            assert db.get(PublishJob, scheduled_id).status == "cancelled"
            assert db.get(PublishJob, published_id).status == "published"
            assert db.query(Task).filter(Task.task_type == "creator_publish_cancel").count() == 2
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_run_due_tasks_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/tasks/run-due?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_run_due_tasks_executes_current_user_due_scheduled_publish_jobs(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.core.time import shanghai_now
    from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task

    class FakeDuePublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "due-note-001"}

    db_dependency, owner_token, owner_account_id = _create_creator_account_with_cookie(
        tmp_path, "due-publish-owner"
    )
    intruder_token = _register_and_get_access_token("due-publish-intruder")
    db = next(app.dependency_overrides[get_db]())
    try:
        now = shanghai_now()
        intruder_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="creator",
            external_user_id="intruder-creator",
            nickname="Intruder creator",
            status="active",
        )
        db.add(intruder_account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=intruder_account.id,
                encrypted_cookies=encrypt_text('{"web_session":"intruder-session","a1":"intruder-a1"}'),
            )
        )

        due_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="Due title",
            body="Due body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now - timedelta(minutes=5),
        )
        future_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="Future title",
            body="Future body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now + timedelta(hours=2),
        )
        intruder_due_job = PublishJob(
            user_id=2,
            platform_account_id=intruder_account.id,
            platform="xhs",
            title="Intruder due title",
            body="Intruder due body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=now - timedelta(minutes=5),
        )
        db.add_all([due_job, future_job, intruder_due_job])
        db.flush()
        db.add_all(
            [
                PublishAsset(
                    publish_job_id=due_job.id,
                    asset_type="image",
                    file_path="storage/media/due.png",
                    upload_status="uploaded",
                    creator_media_id="media-due",
                    creator_upload_info='{"fileIds":"file-due","width":1080,"height":1440}',
                ),
                PublishAsset(
                    publish_job_id=future_job.id,
                    asset_type="image",
                    file_path="storage/media/future.png",
                    upload_status="uploaded",
                    creator_media_id="media-future",
                    creator_upload_info='{"fileIds":"file-future","width":1080,"height":1440}',
                ),
                PublishAsset(
                    publish_job_id=intruder_due_job.id,
                    asset_type="image",
                    file_path="storage/media/intruder.png",
                    upload_status="uploaded",
                    creator_media_id="media-intruder",
                    creator_upload_info='{"fileIds":"file-intruder","width":1080,"height":1440}',
                ),
            ]
        )
        db.commit()
        due_job_id = due_job.id
        future_job_id = future_job.id
        intruder_job_id = intruder_due_job.id
    finally:
        db.close()

    FakeDuePublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeDuePublishAdapter
    try:
        intruder_response = client.post(
            "/api/tasks/run-due?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["executed_count"] == 1

        owner_response = client.post(
            "/api/tasks/run-due?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert owner_response.status_code == 200
        payload = owner_response.json()
        assert payload["executed_count"] == 1
        assert payload["failed_count"] == 0
        assert payload["items"][0]["id"] == due_job_id
        assert payload["items"][0]["status"] == "published"
        assert len(FakeDuePublishAdapter.calls) == 2
        owner_call = FakeDuePublishAdapter.calls[-1]
        assert owner_call["cookies"] == "web_session=creator-session; a1=creator-a1"
        assert owner_call["note_info"]["title"] == "Due title"
        assert owner_call["note_info"]["postTime"] is None

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(PublishJob, due_job_id).status == "published"
            assert db.get(PublishJob, due_job_id).external_note_id == "due-note-001"
            assert db.get(PublishJob, future_job_id).status == "pending"
            assert db.get(PublishJob, intruder_job_id).status == "published"
            tasks = db.query(Task).filter(Task.task_type == "creator_publish_scheduler").all()
            assert len(tasks) == 2
            assert {task.user_id for task in tasks} == {1, 2}
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_run_due_publish_jobs_for_all_users_executes_each_due_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task
    from backend.app.services.scheduler_service import run_due_publish_jobs_for_all_users

    class FakeAllUsersDuePublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": f"note-{len(self.calls)}"}

    db_dependency, owner_token, owner_account_id = _create_creator_account_with_cookie(
        tmp_path, "all-users-due-owner"
    )
    _register_and_get_access_token("all-users-due-second")
    db = next(app.dependency_overrides[get_db]())
    try:
        second_account = PlatformAccount(
            user_id=2,
            platform="xhs",
            sub_type="creator",
            external_user_id="second-creator",
            nickname="Second creator",
            status="active",
        )
        db.add(second_account)
        db.flush()
        db.add(
            AccountCookieVersion(
                platform_account_id=second_account.id,
                encrypted_cookies=encrypt_text('{"web_session":"second-session","a1":"second-a1"}'),
            )
        )
        first_job = PublishJob(
            user_id=1,
            platform_account_id=owner_account_id,
            platform="xhs",
            title="First due",
            body="First body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=datetime.utcnow() - timedelta(minutes=10),
        )
        second_job = PublishJob(
            user_id=2,
            platform_account_id=second_account.id,
            platform="xhs",
            title="Second due",
            body="Second body",
            publish_mode="scheduled",
            status="pending",
            scheduled_at=datetime.utcnow() - timedelta(minutes=8),
        )
        db.add_all([first_job, second_job])
        db.flush()
        db.add_all(
            [
                PublishAsset(
                    publish_job_id=first_job.id,
                    asset_type="image",
                    file_path="storage/media/first.png",
                    upload_status="uploaded",
                    creator_media_id="first-media",
                    creator_upload_info='{"fileIds":"first-file"}',
                ),
                PublishAsset(
                    publish_job_id=second_job.id,
                    asset_type="image",
                    file_path="storage/media/second.png",
                    upload_status="uploaded",
                    creator_media_id="second-media",
                    creator_upload_info='{"fileIds":"second-file"}',
                ),
            ]
        )
        db.commit()
        first_job_id = first_job.id
        second_job_id = second_job.id
    finally:
        db.close()

    FakeAllUsersDuePublishAdapter.calls = []
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            result = run_due_publish_jobs_for_all_users(
                db=db,
                now=datetime.utcnow(),
                platform="xhs",
                adapter_factory=FakeAllUsersDuePublishAdapter,
            )

            assert result["executed_count"] == 2
            assert result["failed_count"] == 0
            assert {item["id"] for item in result["items"]} == {first_job_id, second_job_id}
            assert db.get(PublishJob, first_job_id).status == "published"
            assert db.get(PublishJob, second_job_id).status == "published"
            assert db.query(Task).filter(Task.task_type == "creator_publish_scheduler").count() == 2
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_due_publish_scheduler_registers_interval_job():
    from backend.app.services.scheduler_service import build_due_publish_scheduler, shutdown_due_publish_scheduler

    scheduler = build_due_publish_scheduler(interval_seconds=17, job_func=lambda: None)

    try:
        jobs = scheduler.get_jobs()
        # 未传 monitoring_job_func 时不得把发布函数重复注册成第二个 job id
        assert {job.id for job in jobs} == {
            "due_publish_runner",
            "auto_tasks_runner",
            "cookie_health_checker",
            # review P2 新增：滞留任务周期对账 + 媒体目录清理
            "stale_task_reconciler",
            "media_pruner",
            # 优化项：SQLite 每日在线备份
            "sqlite_backup",
            # 剪辑工坊：过期会话与临时文件清理
            "clip_cleanup",
        }
        job_intervals = {job.id: job.trigger.interval.total_seconds() for job in jobs}
        assert job_intervals["due_publish_runner"] == 17
        assert job_intervals["auto_tasks_runner"] == 60
        assert job_intervals["cookie_health_checker"] == 7200
        assert job_intervals["stale_task_reconciler"] == 600
        assert job_intervals["media_pruner"] == 21600
        assert job_intervals["sqlite_backup"] == 86400
        assert job_intervals["clip_cleanup"] == 21600
    finally:
        shutdown_due_publish_scheduler(scheduler)

def test_publish_job_claim_is_atomic_and_reconcile_resets_stale(tmp_path):
    """P1 回归：条件 UPDATE 领取防止并发重复发布；启动对账复位滞留任务。"""
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import PublishJob
    from backend.app.services.scheduler_service import (
        _claim_publish_job,
        reconcile_stale_publish_jobs,
    )

    db_dependency = _override_database(tmp_path)
    try:
        token = _register_and_get_access_token("claim-owner")
        from sqlalchemy import insert

        db = next(app.dependency_overrides[get_db]())
        try:
            db.execute(insert(PublishJob).values(
                user_id=1, platform="xhs", title="Claim", body="b",
                publish_mode="immediate", status="pending",
            ))
            db.commit()
            job_id = db.scalars(select(PublishJob).where(PublishJob.title == "Claim")).first().id

            # 第一次领取成功，第二次（并发方）失败
            assert _claim_publish_job(db, job_id) is True
            assert _claim_publish_job(db, job_id) is False
            job = db.get(PublishJob, job_id)
            assert job.status == "publishing"
            assert job.publish_started_at is not None

            # 刚领取的任务不在对账范围（未超时）
            result = reconcile_stale_publish_jobs(db=db)
            assert result["reset_publish_jobs"] == 0
            assert db.get(PublishJob, job_id).status == "publishing"

            # 超时后（模拟 31 分钟前领取）被复位为 failed
            job.publish_started_at = shanghai_now() - timedelta(minutes=31)
            db.commit()
            result = reconcile_stale_publish_jobs(db=db)
            assert result["reset_publish_jobs"] == 1
            reset = db.get(PublishJob, job_id)
            assert reset.status == "failed"
            assert "中断" in reset.publish_error
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
