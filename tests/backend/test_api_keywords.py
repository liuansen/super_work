"""关键词分组、关键词趋势与采集限流测试。

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

def test_xhs_analytics_keyword_trends_are_user_scoped_from_keyword_groups(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import KeywordGroup

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "keyword-trends-owner")
    intruder_token = _register_and_get_access_token("keyword-trends-intruder")
    try:
        anonymous_response = client.get("/api/xhs/analytics/keyword-trends")
        assert anonymous_response.status_code == 401

        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "keyword-trend-note-001",
                        "title": "Breakfast angle",
                        "content": "Low calorie breakfast for commute",
                        "author_name": "trend author",
                        "raw": {"likes": 20, "collects": 5, "comments": 1, "shares": 0},
                    },
                    {
                        "note_id": "keyword-trend-note-002",
                        "title": "Storage angle",
                        "content": "Closet storage checklist",
                        "author_name": "trend author",
                        "raw": {"likes": 10, "collects": 2},
                    },
                ],
            },
        )
        assert save_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    KeywordGroup(user_id=1, platform="xhs", name="Owner ideas", keywords=["breakfast", "storage"]),
                    KeywordGroup(user_id=2, platform="xhs", name="Intruder ideas", keywords=["breakfast"]),
                ]
            )
            db.commit()
        finally:
            db.close()

        owner_response = client.get(
            "/api/xhs/analytics/keyword-trends",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        owner_items = owner_response.json()["items"]
        assert [item["keyword"] for item in owner_items] == ["breakfast", "storage"]
        assert owner_items[0]["group_name"] == "Owner ideas"
        assert owner_items[0]["notes"] == 1
        assert owner_items[0]["engagement"] == 26
        assert owner_items[0]["top_notes"][0]["note_id"] == "keyword-trend-note-001"
        assert owner_items[1]["engagement"] == 12

        intruder_response = client.get(
            "/api/xhs/analytics/keyword-trends",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["items"][0]["keyword"] == "breakfast"
        assert intruder_response.json()["items"][0]["notes"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_crawl_rate_limiter_blocks_after_max_requests():
    from backend.app.services.rate_limiter import CrawlRateLimiter

    limiter = CrawlRateLimiter(max_per_minute=3)
    assert limiter.allow(1) is True
    assert limiter.allow(1) is True
    assert limiter.allow(1) is True
    assert limiter.allow(1) is False

    assert limiter.allow(2) is True

    limiter.reset(1)
    assert limiter.allow(1) is True

def test_keyword_groups_require_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/keyword-groups")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_keyword_groups_crud_are_user_scoped(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "keyword-group-owner")
    intruder_token = _register_and_get_access_token("keyword-group-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "keyword-note-001",
                        "title": "低卡早餐模板",
                        "content": "适合通勤的低卡早餐搭配。",
                        "author_name": "早餐作者",
                        "raw": {"likes": 30, "collects": 10, "comments": 4, "shares": 1, "tags": ["低卡", "早餐"]},
                    },
                    {
                        "note_id": "keyword-note-002",
                        "title": "家居收纳灵感",
                        "content": "收纳工具清单。",
                        "author_name": "收纳作者",
                        "raw": {"likes": 2, "collects": 1, "comments": 0, "shares": 0, "tags": ["收纳"]},
                    },
                ],
            },
        )
        assert save_response.status_code == 200

        create_response = client.post(
            "/api/keyword-groups",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"platform": "xhs", "name": "早餐机会", "keywords": ["低卡", "早餐"]},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "早餐机会"
        assert created["keywords"] == ["低卡", "早餐"]

        owner_list_response = client.get("/api/keyword-groups", headers={"Authorization": f"Bearer {owner_token}"})
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get("/api/keyword-groups", headers={"Authorization": f"Bearer {intruder_token}"})
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        detail_response = client.get(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["trend"]["total_matches"] == 1
        assert detail["trend"]["total_engagement"] == 45
        assert detail["trend"]["keywords"][0]["keyword"] == "低卡"
        assert detail["trend"]["matched_notes"][0]["note_id"] == "keyword-note-001"

        patch_response = client.patch(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐选题池", "keywords": ["早餐"]},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "早餐选题池"
        assert patch_response.json()["keywords"] == ["早餐"]

        cross_get_response = client.get(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert cross_get_response.status_code == 404

        cross_patch_response = client.patch(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "偷看"},
        )
        assert cross_patch_response.status_code == 404

        delete_response = client.delete(
            f"/api/keyword-groups/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
