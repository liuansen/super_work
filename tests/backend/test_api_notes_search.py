"""XHS PC 端笔记搜索 / 详情 / 评论适配路由测试。

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

def test_xhs_pc_note_search_uses_owned_account_cookie_and_normalizes_results(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path)
    FakeXhsPcSearchAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcSearchAdapter
    try:
        response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 2},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 1
        assert payload["page"] == 2
        assert payload["has_more"] is True
        assert FakeXhsPcSearchAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "keyword": "低卡早餐",
                "page": 2,
                "sort_type_choice": 0,
                "note_type": 0,
                "note_time": 0,
                "note_range": 0,
                "pos_distance": 0,
                "geo": "",
            }
        ]
        note = payload["items"][0]
        assert note["note_id"] == "note-001"
        assert note["note_url"] == "https://www.xiaohongshu.com/explore/note-001?xsec_token=xsec-search-001&xsec_source=pc_feed"
        assert note["title"] == "低卡早餐搜索笔记"
        assert note["content"] == "适合工作日的早餐搭配"
        assert note["author_name"] == "早餐研究员"
        assert note["author_id"] == "author-001"
        assert note["cover_url"] == "https://example.test/cover.webp"
        assert note["likes"] == 1234
        assert note["collects"] == 456
        assert note["comments"] == 78
        assert note["shares"] == 9
        assert note["type"] == "normal"
        assert note["raw"]["model_type"] == "note"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_xhs_pc_note_search_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    db_dependency, owner_token, account_id = _create_pc_account_with_cookie(tmp_path, "search-owner-2")
    intruder_token = _register_and_get_access_token("search-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcSearchAdapter
    try:
        missing_auth_response = client.post(
            "/api/xhs/pc/search/notes",
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert missing_auth_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert intruder_response.status_code == 404

        owner_response = client.post(
            "/api/xhs/pc/search/notes",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"account_id": account_id, "keyword": "低卡早餐", "page": 1},
        )
        assert owner_response.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_xhs_pc_note_detail_uses_owned_account_cookie_and_normalizes_result(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcDetailAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_info(self, url):
            self.calls.append({"cookies": self.cookies, "url": url})
            return (
                True,
                "ok",
                {
                    "success": True,
                    "data": {
                        "items": [
                            {
                                "note_card": {
                                    "note_id": "detail-note-001",
                                    "title": "Detail title",
                                    "desc": "Detail body",
                                    "type": "video",
                                    "user": {
                                        "user_id": "author-detail",
                                        "nickname": "Detail author",
                                        "avatar": "https://example.test/author.webp",
                                    },
                                    "image_list": [
                                        {
                                            "url_default": "https://example.test/image-preview.webp",
                                            "info_list": [
                                                {"image_scene": "WB_DFT", "url": "https://example.test/image-low.webp"},
                                                {"image_scene": "WB_PRV", "url": "https://example.test/image-high.webp"},
                                            ],
                                        },
                                    ],
                                    "video": {
                                        "media": {
                                            "stream": {
                                                "h264": [
                                                    {
                                                        "master_url": "https://sns-video-hw.xhscdn.com/detail-video-master.mp4",
                                                        "url": "https://sns-video-hw.xhscdn.com/detail-video-fallback.mp4",
                                                    }
                                                ]
                                            }
                                        }
                                    },
                                    "interact_info": {
                                        "liked_count": "100",
                                        "collected_count": "20",
                                        "comment_count": "3",
                                        "share_count": "4",
                                    },
                                    "tag_list": [{"name": "topic-a"}, {"name": "topic-b"}],
                                }
                            }
                        ]
                    },
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "detail-owner")
    FakeXhsPcDetailAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcDetailAdapter
    try:
        response = client.post(
            "/api/xhs/pc/notes/detail",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "url": "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed",
            },
        )

        assert response.status_code == 200
        detail = response.json()
        assert detail["note_id"] == "detail-note-001"
        assert detail["note_url"] == "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed"
        assert detail["title"] == "Detail title"
        assert detail["content"] == "Detail body"
        assert detail["author_id"] == "author-detail"
        assert detail["author_name"] == "Detail author"
        assert detail["cover_url"] == "https://example.test/image-high.webp"
        assert detail["image_urls"] == ["https://example.test/image-high.webp"]
        assert detail["video_url"] == "https://sns-video-hw.xhscdn.com/detail-video-master.mp4"
        assert detail["video_addr"] == "https://sns-video-hw.xhscdn.com/detail-video-master.mp4"
        assert detail["tags"] == ["topic-a", "topic-b"]
        assert detail["likes"] == 100
        assert FakeXhsPcDetailAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "url": "https://www.xiaohongshu.com/explore/detail-note-001?xsec_token=detail-token&xsec_source=pc_feed",
            }
        ]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_xhs_pc_note_detail_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcDetailAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user detail must not instantiate adapter")

    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "detail-cross-owner")
    intruder_token = _register_and_get_access_token("detail-cross-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcDetailAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/pc/notes/detail",
            json={"account_id": account_id, "url": "https://www.xiaohongshu.com/explore/detail-note-001"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/notes/detail",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "url": "https://www.xiaohongshu.com/explore/detail-note-001"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_xhs_pc_note_comments_uses_owned_account_cookie_and_normalizes_result(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            self.calls.append({"cookies": self.cookies, "note_url": note_url})
            return (
                True,
                "ok",
                {
                    "data": {
                        "comments": [
                            {
                                "id": "comment-001",
                                "content": "Top level comment",
                                "like_count": "12",
                                "create_time": "2026-04-29 12:00:00",
                                "user_info": {"user_id": "user-001", "nickname": "Comment author"},
                                "sub_comments": [
                                    {
                                        "id": "comment-001-1",
                                        "content": "Reply content",
                                        "like_count": 3,
                                        "create_time": "2026-04-29 12:01:00",
                                        "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                                    }
                                ],
                            }
                        ]
                    }
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comments-owner")
    FakeXhsPcCommentAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentAdapter
    try:
        response = client.post(
            "/api/xhs/pc/notes/comments",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["total"] == 2
        assert payload["items"] == [
            {
                "comment_id": "comment-001",
                "user_name": "Comment author",
                "user_id": "user-001",
                "content": "Top level comment",
                "like_count": 12,
                "parent_comment_id": None,
                "created_at_remote": "2026-04-29 12:00:00",
                "raw_json": {
                    "id": "comment-001",
                    "content": "Top level comment",
                    "like_count": "12",
                    "create_time": "2026-04-29 12:00:00",
                    "user_info": {"user_id": "user-001", "nickname": "Comment author"},
                    "sub_comments": [
                        {
                            "id": "comment-001-1",
                            "content": "Reply content",
                            "like_count": 3,
                            "create_time": "2026-04-29 12:01:00",
                            "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                        }
                    ],
                },
            },
            {
                "comment_id": "comment-001-1",
                "user_name": "Reply author",
                "user_id": "user-002",
                "content": "Reply content",
                "like_count": 3,
                "parent_comment_id": "comment-001",
                "created_at_remote": "2026-04-29 12:01:00",
                "raw_json": {
                    "id": "comment-001-1",
                    "content": "Reply content",
                    "like_count": 3,
                    "create_time": "2026-04-29 12:01:00",
                    "user_info": {"user_id": "user-002", "nickname": "Reply author"},
                },
            },
        ]
        assert FakeXhsPcCommentAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "note_url": "https://www.xiaohongshu.com/explore/comment-note-001",
            }
        ]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_xhs_pc_note_comments_rejects_missing_auth_and_cross_user_account(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentAdapter:
        def __init__(self, cookies):
            raise AssertionError("cross-user comments must not instantiate adapter")

    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "comments-cross-owner")
    intruder_token = _register_and_get_access_token("comments-cross-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentAdapter
    try:
        anonymous_response = client.post(
            "/api/xhs/pc/notes/comments",
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            "/api/xhs/pc/notes/comments",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "note_url": "https://www.xiaohongshu.com/explore/comment-note-001"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)
