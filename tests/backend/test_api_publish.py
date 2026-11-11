"""发布任务、发布素材上传与发布执行测试。

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

def test_draft_send_to_publish_creates_job_and_enforces_ownership(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import PublishJob

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-owner")
    intruder_token = _register_and_get_access_token("publish-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Ready title", "body": "Ready body"},
        )
        draft_id = draft_response.json()["id"]

        create_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id, "publish_mode": "immediate"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["platform"] == "xhs"
        assert created["platform_account_id"] == owner_account_id
        assert created["source_draft_id"] == draft_id
        assert created["title"] == "Ready title"
        assert created["body"] == "Ready body"
        assert created["publish_mode"] == "immediate"
        assert created["status"] == "pending"

        intruder_draft_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform_account_id": owner_account_id, "publish_mode": "immediate"},
        )
        assert intruder_draft_response.status_code == 404

        db = next(app.dependency_overrides[get_db]())
        try:
            publish_job = db.query(PublishJob).one()
            assert publish_job.source_draft_id == draft_id
            assert publish_job.platform_account_id == owner_account_id
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_jobs_list_requires_auth_and_filters_current_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.core.security import encrypt_text
    from backend.app.models import AccountCookieVersion, PlatformAccount

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-list-owner")
    intruder_token = _register_and_get_access_token("publish-list-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            intruder_account = PlatformAccount(
                user_id=2,
                platform="xhs",
                sub_type="pc",
                external_user_id="publish-list-intruder",
                nickname="发布测试账号",
                status="active",
            )
            db.add(intruder_account)
            db.flush()
            db.add(
                AccountCookieVersion(
                    platform_account_id=intruder_account.id,
                    encrypted_cookies=encrypt_text('{"a1":"intruder-a1"}'),
                )
            )
            db.commit()
            intruder_account_id = intruder_account.id
        finally:
            db.close()

        owner_draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner publish", "body": "Owner body"},
        )
        owner_draft_id = owner_draft_response.json()["id"]
        owner_create_response = client.post(
            f"/api/drafts/{owner_draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        assert owner_create_response.status_code == 200

        intruder_draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform": "xhs", "title": "Intruder publish", "body": "Intruder body"},
        )
        intruder_draft_id = intruder_draft_response.json()["id"]
        intruder_create_response = client.post(
            f"/api/drafts/{intruder_draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"platform_account_id": intruder_account_id},
        )
        assert intruder_create_response.status_code == 200

        anonymous_response = client.get("/api/publish/jobs?platform=xhs")
        assert anonymous_response.status_code == 401

        owner_list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        owner_payload = owner_list_response.json()
        assert owner_payload["total"] == 1
        assert owner_payload["items"][0]["title"] == "Owner publish"

        intruder_list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        intruder_payload = intruder_list_response.json()
        assert intruder_payload["total"] == 1
        assert intruder_payload["items"][0]["title"] == "Intruder publish"
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_detail_and_update_enforce_ownership(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-detail-owner")
    intruder_token = _register_and_get_access_token("publish-detail-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Draft title", "body": "Draft body"},
        )
        draft_id = draft_response.json()["id"]
        create_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        job_id = create_response.json()["id"]

        owner_detail_response = client.get(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_detail_response.status_code == 200
        assert owner_detail_response.json()["title"] == "Draft title"

        intruder_detail_response = client.get(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_detail_response.status_code == 404

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "title": "Edited publish title",
                "body": "Edited publish body",
                "publish_mode": "scheduled",
                "scheduled_at": "2030-01-02T03:04:05",
            },
        )
        assert update_response.status_code == 200
        updated = update_response.json()
        assert updated["title"] == "Edited publish title"
        assert updated["body"] == "Edited publish body"
        assert updated["publish_mode"] == "scheduled"
        assert updated["scheduled_at"] == "2030-01-02T03:04:05"

        list_response = client.get(
            "/api/publish/jobs?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.json()["items"][0]["title"] == "Edited publish title"

        intruder_update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"title": "stolen"},
        )
        assert intruder_update_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_assets_api_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/publish/jobs/1/assets")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_assets_api_adds_lists_and_deletes_owned_assets(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "publish-assets-owner")
    intruder_token = _register_and_get_access_token("publish-assets-intruder")
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Asset title", "body": "Asset body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": owner_account_id},
        )
        job_id = job_response.json()["id"]

        create_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": _owned_media_fixture(owner_token)},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["publish_job_id"] == job_id
        assert created["asset_type"] == "image"
        assert created["file_path"].startswith("xhs-upload-u")

        list_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["id"] == created["id"]

        intruder_list_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 404

        intruder_delete_response = client.delete(
            f"/api/publish/assets/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_delete_response.status_code == 404

        delete_response = client.delete(
            f"/api/publish/assets/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"

        empty_response = client.get(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert empty_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_asset_upload_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/publish/assets/1/upload")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_asset_upload_uses_creator_cookie_and_updates_asset(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def upload_media(self, file_path, media_type):
            self.calls.append({"cookies": self.cookies, "file_path": file_path, "media_type": media_type})
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001"}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-upload-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Upload title", "body": "Upload body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]

        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert upload_response.status_code == 200
        uploaded = upload_response.json()
        assert uploaded["upload_status"] == "uploaded"
        assert uploaded["creator_media_id"] == "creator-media-001"
        assert uploaded["upload_error"] == ""
        assert FakeCreatorPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "file_path": owned_media,
                "media_type": "image",
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_asset_upload_rejects_cross_user_asset(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user upload must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-upload-cross-owner"
    )
    intruder_token = _register_and_get_access_token("publish-upload-cross-intruder")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner asset", "body": "Owner body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]

        response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post("/api/publish/jobs/1/publish")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_uses_creator_cookie_and_updates_status(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "xhs-note-001", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 200
        published = publish_response.json()
        assert published["status"] == "published"
        assert published["external_note_id"] == "xhs-note-001"
        assert published["publish_error"] == ""
        assert published["published_at"] is not None
        assert FakeCreatorPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Publish title",
                    "desc": "Publish body",
                    "media_type": "image",
                    "image_file_infos": [
                        {
                            "creator_media_id": "creator-media-001",
                            "fileIds": "file-001",
                            "width": 1080,
                            "height": 1440,
                        }
                    ],
                    "type": 1,
                    "postTime": None,
                },
            }
        ]

        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert task.user_id == 1
            assert task.platform == "xhs"
            assert task.status == "completed"
            assert task.progress == 100
            assert task.payload["publish_job_id"] == job_id
            assert task.payload["external_note_id"] == "xhs-note-001"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_passes_optional_creator_parameters(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorOptionalPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "optional-job-note", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-optional", "fileIds": "file-optional", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-optional-owner"
    )
    FakeCreatorOptionalPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorOptionalPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Optional title", "body": ""},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "platform_account_id": creator_account_id,
                "topics": ["早餐"],
                "location": "上海",
                "is_private": False,
            },
        )
        job_id = job_response.json()["id"]
        assert job_response.json()["publish_options"] == {
            "topics": ["早餐"],
            "location": "上海",
            "is_private": False,
            "privacy_type": 0,
        }

        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"topics": ["早餐", "通勤"], "is_private": True, "location": ""},
        )
        assert update_response.status_code == 200
        assert update_response.json()["publish_options"] == {
            "topics": ["早餐", "通勤"],
            "is_private": True,
            "privacy_type": 1,
        }

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 200
        assert FakeCreatorOptionalPublishAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Optional title",
                    "desc": "",
                    "media_type": "image",
                    "image_file_infos": [
                        {
                            "creator_media_id": "creator-media-optional",
                            "fileIds": "file-optional",
                            "width": 1080,
                            "height": 1440,
                        }
                    ],
                    "type": 1,
                    "postTime": None,
                    "topics": ["早餐", "通勤"],
                },
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_records_failed_task(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeFailingCreatorPublishAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            raise RuntimeError("creator publish denied")

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-failed-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeFailingCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 502
        db = next(app.dependency_overrides[get_db]())
        try:
            task = db.query(Task).filter(Task.task_type == "creator_publish").one()
            assert task.status == "failed"
            assert task.progress == 100
            assert task.payload["publish_job_id"] == job_id
            assert task.payload["error"] == "creator publish denied"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_rejects_empty_content_before_adapter(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("invalid publish content must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-preflight-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Valid title", "body": "Valid body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"title": "   ", "body": ""},
        )
        assert update_response.status_code == 200

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 400
        assert publish_response.json()["detail"] == "Publish title is required"
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_rejects_past_scheduled_time_before_adapter(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import PublishAsset, Task

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("past scheduled publish must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-past-schedule-owner"
    )
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Scheduled title", "body": "Scheduled body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        update_response = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "publish_mode": "scheduled",
                "scheduled_at": (shanghai_now() - timedelta(minutes=5)).isoformat(),
            },
        )
        # SCH-6：过去时间的 scheduled 任务在写入阶段即被拒绝（422），
        # 不再等到执行阶段才失败
        assert update_response.status_code == 422

        future_update = client.patch(
            f"/api/publish/jobs/{job_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "publish_mode": "scheduled",
                "scheduled_at": (shanghai_now() + timedelta(hours=2)).isoformat(),
            },
        )
        assert future_update.status_code == 200

        # 端点防御仍在：绕过 API 直接把库里的 scheduled_at 改成过去时间，
        # publish 端点必须在调用适配器前拒绝
        db = next(app.dependency_overrides[get_db]())
        try:
            from backend.app.models import PublishJob

            stored = db.get(PublishJob, job_id)
            stored.scheduled_at = shanghai_now() - timedelta(minutes=5)
            db.commit()
        finally:
            db.close()

        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                PublishAsset(
                    publish_job_id=job_id,
                    asset_type="image",
                    file_path="cover.png",
                    upload_status="uploaded",
                    creator_media_id="creator-media-001",
                    creator_upload_info='{"fileIds":"file-001","width":1080,"height":1440}',
                )
            )
            db.commit()
        finally:
            db.close()

        publish_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert publish_response.status_code == 400
        assert publish_response.json()["detail"] == "Scheduled publish time must be in the future"
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_rejects_already_completed_job(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorPublishAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"note_id": "xhs-note-001", "success": True}

        def upload_media(self, file_path, media_type):
            return {"creator_media_id": "creator-media-001", "fileIds": "file-001", "width": 1080, "height": 1440}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-completed-owner"
    )
    FakeCreatorPublishAdapter.calls = []
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Publish title", "body": "Publish body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]
        owned_media = _owned_media_fixture(owner_token)
        asset_response = client.post(
            f"/api/publish/jobs/{job_id}/assets",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"asset_type": "image", "file_path": owned_media},
        )
        asset_id = asset_response.json()["id"]
        upload_response = client.post(
            f"/api/publish/assets/{asset_id}/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert upload_response.status_code == 200

        first_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert first_response.status_code == 200

        second_response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {owner_token}"},
        )

        assert second_response.status_code == 400
        assert second_response.json()["detail"] == "Publish job is already completed or in progress"
        assert len(FakeCreatorPublishAdapter.calls) == 1
        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.query(Task).filter(Task.task_type == "creator_publish").count() == 1
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_publish_job_publish_rejects_cross_user_job(tmp_path):
    from backend.app.api.publish import get_creator_publish_adapter_factory

    class FakeCreatorPublishAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user publish must not instantiate adapter")

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "publish-action-cross-owner"
    )
    intruder_token = _register_and_get_access_token("publish-action-cross-intruder")
    app.dependency_overrides[get_creator_publish_adapter_factory] = lambda: FakeCreatorPublishAdapter
    try:
        draft_response = client.post(
            "/api/drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "title": "Owner publish", "body": "Owner body"},
        )
        draft_id = draft_response.json()["id"]
        job_response = client.post(
            f"/api/drafts/{draft_id}/send-to-publish",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform_account_id": creator_account_id},
        )
        job_id = job_response.json()["id"]

        response = client.post(
            f"/api/publish/jobs/{job_id}/publish",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(get_creator_publish_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)
