"""XHS 采集任务与创作者路由测试。

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

def test_xhs_crawl_routes_are_authenticated_task_backed_and_persist_notes(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Note, NoteAsset, Task

    class FakeCrawlAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def search_note(self, keyword, page=1, **kwargs):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-search-001",
                                "display_title": f"{keyword} search title",
                                "desc": "search content",
                                "user": {"nickname": "search author"},
                                "interact_info": {"liked_count": 12, "collected_count": 3, "comment_count": 2},
                                "cover": {"url": "https://img.example/search.png"},
                            }
                        }
                    ],
                    "total": 1,
                    "has_more": False,
                }
            }

        def get_note_info(self, url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-url-001",
                                "display_title": "url detail title",
                                "desc": "url detail body",
                                "user": {"nickname": "url author"},
                                "interact_info": {"liked_count": 30},
                                "image_list": [{"url": "https://img.example/url-1.png"}],
                            }
                        }
                    ]
                }
            }

        def get_user_notes(self, user_url):
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "crawl-user-001",
                                "display_title": "user note title",
                                "desc": "user note body",
                                "user": {"nickname": "profile author"},
                                "interact_info": {"liked_count": 7},
                                "cover": {"url": "https://img.example/user.png"},
                            }
                        }
                    ],
                    "total": 1,
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "crawl-routes-owner")
    intruder_token = _register_and_get_access_token("crawl-routes-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeCrawlAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/crawl/search-notes",
            json={"account_id": owner_account_id, "keyword": "breakfast"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/crawl/search-notes",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": owner_account_id, "keyword": "breakfast"},
        )
        assert intruder_response.status_code == 404

        search_response = client.post(
            "/api/xhs/crawl/search-notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "keyword": "breakfast", "page": 1},
        )
        assert search_response.status_code == 200
        search_payload = search_response.json()
        assert search_payload["task"]["task_type"] == "crawl"
        assert search_payload["task"]["status"] == "completed"
        assert search_payload["saved_count"] == 1
        assert search_payload["items"][0]["note_id"] == "crawl-search-001"

        url_response = client.post(
            "/api/xhs/crawl/note-urls",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "urls": ["https://www.xiaohongshu.com/explore/crawl-url-001"]},
        )
        assert url_response.status_code == 200
        assert url_response.json()["saved_count"] == 1
        assert url_response.json()["items"][0]["note_id"] == "crawl-url-001"

        user_response = client.post(
            "/api/xhs/crawl/user-notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": owner_account_id, "user_url": "https://www.xiaohongshu.com/user/profile/demo"},
        )
        assert user_response.status_code == 200
        assert user_response.json()["saved_count"] == 1
        assert user_response.json()["items"][0]["note_id"] == "crawl-user-001"

        db = next(app.dependency_overrides[get_db]())
        try:
            tasks = db.query(Task).filter(Task.task_type == "crawl").all()
            notes = db.query(Note).order_by(Note.note_id.asc()).all()
            assets = db.query(NoteAsset).all()
            assert len(tasks) == 3
            assert all(task.user_id == 1 and task.status == "completed" for task in tasks)
            assert [note.note_id for note in notes] == ["crawl-search-001", "crawl-url-001", "crawl-user-001"]
            assert len(assets) == 3
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_data_crawl_marks_partial_failures_and_fetches_comments(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeDataCrawlAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_info(self, url):
            self.__class__.calls.append(("detail", url))
            if "bad" in url:
                return False, "detail failed", {}
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "data-url-001",
                                "display_title": "data crawl detail",
                                "desc": "detail body",
                                "user": {"nickname": "detail author"},
                                "interact_info": {"liked_count": 8, "comment_count": 1},
                                "image_list": [{"url": "https://img.example/data-url.png"}],
                            }
                        }
                    ]
                }
            }

        def get_note_comments(self, url):
            self.__class__.calls.append(("comments", url))
            return True, "ok", {
                "data": {
                    "comments": [
                        {
                            "id": "comment-001",
                            "content": "想看更多",
                            "user_info": {"nickname": "reader"},
                            "like_count": "3",
                        }
                    ]
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "data-crawl-owner")
    FakeDataCrawlAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeDataCrawlAdapter
    try:
        response = client.post(
            "/api/xhs/crawl/data",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "mode": "note_urls",
                "urls": [
                    "https://www.xiaohongshu.com/explore/data-url-001",
                    "https://www.xiaohongshu.com/explore/bad-url",
                ],
                "fetch_comments": True,
            },
        )

        assert response.status_code == 200
        payload = _parse_sse_response(response)
        assert payload["total"] == 2
        assert payload["success_count"] == 1
        assert payload["failed_count"] == 1
        assert payload["items"][0]["status"] == "success"
        assert payload["items"][0]["note"]["note_id"] == "data-url-001"
        assert payload["items"][0]["comment_count"] == 1
        assert payload["items"][0]["comments"][0]["content"] == "想看更多"
        assert payload["items"][1]["status"] == "failed"
        assert payload["items"][1]["error"] == "detail failed"
        assert ("comments", "https://www.xiaohongshu.com/explore/data-url-001") in FakeDataCrawlAdapter.calls
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_data_crawl_search_expands_filters_and_fetches_details(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeSearchDataCrawlAdapter:
        search_calls = []
        detail_calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def search_note(self, keyword, page=1, **kwargs):
            self.__class__.search_calls.append({"keyword": keyword, "page": page, **kwargs})
            return True, "ok", {
                "data": {
                    "has_more": False,
                    "items": [
                        {
                            "xsec_token": "xsec-data-search",
                            "note_card": {
                                "note_id": "data-search-001",
                                "display_title": "search source title",
                                "desc": "search source body",
                                "user": {"nickname": "search author"},
                                "interact_info": {"liked_count": 12},
                                "cover": {"url": "https://img.example/search.png"},
                            },
                        }
                    ],
                }
            }

        def get_note_info(self, url):
            self.__class__.detail_calls.append(url)
            return True, "ok", {
                "data": {
                    "items": [
                        {
                            "note_card": {
                                "note_id": "data-search-001",
                                "display_title": "detail title",
                                "desc": "detail body",
                                "user": {"nickname": "detail author"},
                                "interact_info": {"liked_count": 88},
                                "image_list": [{"url": "https://img.example/detail.png"}],
                            }
                        }
                    ]
                }
            }

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "data-crawl-search-owner")
    FakeSearchDataCrawlAdapter.search_calls = []
    FakeSearchDataCrawlAdapter.detail_calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeSearchDataCrawlAdapter
    try:
        response = client.post(
            "/api/xhs/crawl/data",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "mode": "search",
                "keyword": "低卡早餐",
                "pages": 1,
                "max_notes": 5,
                "sort_type_choice": 2,
                "note_type": 2,
                "note_time": 1,
                "note_range": 3,
                "pos_distance": 1,
                "geo": "31.2304,121.4737",
            },
        )

        assert response.status_code == 200
        payload = _parse_sse_response(response)
        assert payload["success_count"] == 1
        assert payload["items"][0]["note"]["title"] == "detail title"
        assert FakeSearchDataCrawlAdapter.search_calls == [
            {
                "keyword": "低卡早餐",
                "page": 1,
                "sort_type_choice": 2,
                "note_type": 2,
                "note_time": 1,
                "note_range": 3,
                "pos_distance": 1,
                "geo": "31.2304,121.4737",
            }
        ]
        assert FakeSearchDataCrawlAdapter.detail_calls == [
            "https://www.xiaohongshu.com/explore/data-search-001?xsec_token=xsec-data-search&xsec_source=pc_feed"
        ]
    finally:
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_creator_routes_use_owned_creator_account_and_record_tasks(tmp_path):
    from backend.app.api.platforms.xhs.creator import get_creator_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import Task

    class FakeCreatorRoutesAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_topic(self, keyword):
            return True, "ok", {"data": {"items": [{"id": "topic-creator", "name": keyword}]}}

        def get_location_info(self, keyword):
            return True, "ok", {"data": {"items": [{"id": "loc-creator", "name": keyword}]}}

        def upload_media(self, file_path, media_type):
            return {"fileIds": "file-creator-001", "width": 1080, "height": 1440, "media_type": media_type}

        def post_note(self, note_info):
            return {"success": True, "data": {"note_id": "creator-direct-note"}, "note_info": note_info}

        def get_published_notes(self):
            return True, "ok", {"data": {"items": [{"note_id": "published-001", "title": "Published"}]}}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "creator-routes-owner"
    )
    intruder_token = _register_and_get_access_token("creator-routes-intruder")
    app.dependency_overrides[get_creator_api_adapter_factory] = lambda: FakeCreatorRoutesAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/creator/topics/search",
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/creator/topics/search",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert intruder_response.status_code == 404

        topic_response = client.post(
            "/api/xhs/creator/topics/search",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "keyword": "breakfast"},
        )
        assert topic_response.status_code == 200
        assert topic_response.json()["items"][0]["name"] == "breakfast"

        location_response = client.post(
            "/api/xhs/creator/locations/search",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "keyword": "Shanghai"},
        )
        assert location_response.status_code == 200
        assert location_response.json()["items"][0]["id"] == "loc-creator"

        # SEC-2：本地素材必须携带当前用户的 xhs-upload-u{id}- 前缀
        foreign_upload = client.post(
            "/api/xhs/creator/assets/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "file_path": "xhs-upload-u999-cover.png", "media_type": "image"},
        )
        assert foreign_upload.status_code == 400

        upload_response = client.post(
            "/api/xhs/creator/assets/upload",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": creator_account_id, "file_path": "xhs-upload-u1-cover.png", "media_type": "image"},
        )
        assert upload_response.status_code == 200
        assert upload_response.json()["payload"]["fileIds"] == "file-creator-001"
        assert upload_response.json()["task"]["task_type"] == "creator_direct_upload"

        publish_response = client.post(
            "/api/xhs/creator/publish/image",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Direct title",
                "body": "Direct body",
                "image_file_infos": [{"fileIds": "file-creator-001", "width": 1080, "height": 1440}],
            },
        )
        assert publish_response.status_code == 200
        assert publish_response.json()["payload"]["data"]["note_id"] == "creator-direct-note"
        assert publish_response.json()["task"]["task_type"] == "creator_direct_publish"

        video_response = client.post(
            "/api/xhs/creator/publish/video",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Video title",
                "body": "Video body",
                "video_info": {"video_id": "video-001"},
            },
        )
        assert video_response.status_code == 200
        assert video_response.json()["payload"]["note_info"]["media_type"] == "video"

        published_response = client.get(
            f"/api/xhs/creator/published?account_id={creator_account_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert published_response.status_code == 200
        assert published_response.json()["items"][0]["note_id"] == "published-001"

        db = next(app.dependency_overrides[get_db]())
        try:
            tasks = db.query(Task).filter(Task.task_type.in_(["creator_direct_upload", "creator_direct_publish"])).all()
            assert [task.status for task in tasks] == ["completed", "completed", "completed"]
            assert all(task.user_id == 1 for task in tasks)
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(get_creator_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_creator_direct_publish_accepts_optional_publish_parameters(tmp_path):
    from backend.app.api.platforms.xhs.creator import get_creator_api_adapter_factory

    class FakeCreatorOptionalAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def post_note(self, note_info):
            self.calls.append({"cookies": self.cookies, "note_info": note_info})
            return {"success": True, "data": {"note_id": "optional-note"}, "note_info": note_info}

    db_dependency, owner_token, creator_account_id = _create_creator_account_with_cookie(
        tmp_path, "creator-optional-owner"
    )
    FakeCreatorOptionalAdapter.calls = []
    app.dependency_overrides[get_creator_api_adapter_factory] = lambda: FakeCreatorOptionalAdapter
    try:
        image_response = client.post(
            "/api/xhs/creator/publish/image",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": creator_account_id,
                "title": "Direct optional title",
                "image_file_infos": [{"fileIds": "file-optional", "width": 1080, "height": 1440}],
                "topics": ["早餐", "通勤"],
                "location": "上海",
                "is_private": False,
            },
        )

        assert image_response.status_code == 200
        assert FakeCreatorOptionalAdapter.calls == [
            {
                "cookies": "web_session=creator-session; a1=creator-a1",
                "note_info": {
                    "title": "Direct optional title",
                    "desc": "",
                    "media_type": "image",
                    "image_file_infos": [{"fileIds": "file-optional", "width": 1080, "height": 1440}],
                    "type": 0,
                    "postTime": None,
                    "topics": ["早餐", "通勤"],
                    "location": "上海",
                },
            }
        ]
    finally:
        app.dependency_overrides.pop(get_creator_api_adapter_factory, None)
        app.dependency_overrides.pop(db_dependency, None)
