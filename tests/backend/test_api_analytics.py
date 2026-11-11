"""XHS 数据分析总览、对标、报告与草稿生成测试。

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

def test_xhs_analytics_uses_current_user_saved_notes_tags_and_comments(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "analytics-owner")
    intruder_token = _register_and_get_access_token("analytics-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "analytics-note-001",
                        "title": "高互动早餐笔记",
                        "content": "早餐选题正文",
                        "author_name": "早餐作者",
                        "raw": {"likes": 100, "collects": 30, "comments": 12, "shares": 8, "tags": ["早餐", "低卡"]},
                    },
                    {
                        "note_id": "analytics-note-002",
                        "title": "普通收纳笔记",
                        "content": "收纳正文",
                        "author_name": "收纳作者",
                        "raw": {"likes": 10, "collects": 2, "comments": 1, "shares": 0, "tags": ["收纳"]},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        first_note_id = save_response.json()["items"][0]["id"]
        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "早餐", "color": "#111111"},
        )
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [first_note_id], "tag_ids": [tag_response.json()["id"]], "mode": "add"},
        )
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                NoteComment(
                    note_id=first_note_id,
                    comment_id="analytics-comment-001",
                    user_name="用户 A",
                    content="这个早餐适合通勤吗？价格会不会高？",
                    like_count=9,
                )
            )
            db.commit()
        finally:
            db.close()

        overview_response = client.get(
            "/api/xhs/analytics/overview",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert overview_response.status_code == 200
        overview = overview_response.json()
        assert overview["platform"] == "xhs"
        assert overview["saved_notes"] == 2
        assert overview["total_engagement"] == 163
        assert overview["comment_count"] == 1
        assert overview["hot_topics"][0]["keyword"] == "早餐"

        top_response = client.get(
            "/api/xhs/analytics/top-content",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert top_response.status_code == 200
        top_items = top_response.json()["items"]
        assert [item["note_id"] for item in top_items] == ["analytics-note-001", "analytics-note-002"]
        assert top_items[0]["engagement"] == 150

        topics_response = client.get(
            "/api/xhs/analytics/hot-topics",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert topics_response.status_code == 200
        topics = topics_response.json()["items"]
        assert topics[0]["keyword"] == "早餐"
        assert topics[0]["notes"] == 1
        assert topics[0]["engagement"] == 150

        comments_response = client.get(
            "/api/xhs/analytics/comment-insights",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert comments_response.status_code == 200
        comments = comments_response.json()
        assert comments["total_comments"] == 1
        assert comments["question_count"] == 1
        assert comments["top_comments"][0]["content"] == "这个早餐适合通勤吗？价格会不会高？"

        intruder_response = client.get(
            "/api/xhs/analytics/overview",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["saved_notes"] == 0
        assert intruder_response.json()["total_engagement"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_analytics_benchmarks_are_user_scoped_from_monitoring_targets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import MonitoringTarget

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "benchmark-owner")
    intruder_token = _register_and_get_access_token("benchmark-intruder")
    try:
        anonymous_response = client.get("/api/xhs/analytics/benchmarks")
        assert anonymous_response.status_code == 401

        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "benchmark-note-account",
                        "title": "竞品账号低卡早餐",
                        "content": "creator-001 的早餐选题",
                        "author_name": "creator-001",
                        "raw": {"likes": 80, "collects": 12, "comments": 6, "shares": 2},
                    },
                    {
                        "note_id": "benchmark-note-brand",
                        "title": "BrandA 收纳爆文",
                        "content": "BrandA 新品收纳角度",
                        "author_name": "brand-author",
                        "raw": {"likes": 30, "collects": 10, "comments": 4, "shares": 1},
                    },
                    {
                        "note_id": "benchmark-note-keyword-only",
                        "title": "低卡早餐普通趋势",
                        "content": "低卡早餐关键词命中但不是竞品目标",
                        "author_name": "trend-author",
                        "raw": {"likes": 300},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add_all(
                [
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="account",
                        name="竞品账号",
                        value="creator-001",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="brand",
                        name="BrandA",
                        value="BrandA",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=1,
                        platform="xhs",
                        target_type="keyword",
                        name="低卡早餐",
                        value="低卡早餐",
                        status="active",
                    ),
                    MonitoringTarget(
                        user_id=2,
                        platform="xhs",
                        target_type="account",
                        name="Other account",
                        value="creator-001",
                        status="active",
                    ),
                ]
            )
            db.commit()
        finally:
            db.close()

        response = client.get(
            "/api/xhs/analytics/benchmarks",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["total_targets"] == 2
        assert payload["matched_notes"] == 2
        assert payload["total_engagement"] == 145
        assert [item["target_type"] for item in payload["items"]] == ["account", "brand"]
        assert payload["items"][0]["name"] == "竞品账号"
        assert payload["items"][0]["matched_notes"] == 1
        assert payload["items"][0]["total_engagement"] == 100
        assert payload["items"][0]["top_notes"][0]["note_id"] == "benchmark-note-account"
        assert payload["items"][1]["name"] == "BrandA"
        assert payload["items"][1]["total_engagement"] == 45

        intruder_response = client.get(
            "/api/xhs/analytics/benchmarks",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total_targets"] == 1
        assert intruder_response.json()["matched_notes"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_benchmark_create_drafts_uses_owned_target_matches(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft, MonitoringTarget

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "benchmark-draft-owner")
    intruder_token = _register_and_get_access_token("benchmark-draft-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "benchmark-draft-note-001",
                        "title": "creator-002 爆款标题",
                        "content": "creator-002 的爆款正文",
                        "author_name": "creator-002",
                        "raw": {"likes": 90},
                    },
                    {
                        "note_id": "benchmark-draft-note-002",
                        "title": "creator-002 第二篇",
                        "content": "creator-002 的第二篇正文",
                        "author_name": "creator-002",
                        "raw": {"likes": 40},
                    },
                    {
                        "note_id": "benchmark-draft-note-other",
                        "title": "其他账号内容",
                        "content": "不该命中",
                        "author_name": "other",
                        "raw": {"likes": 500},
                    },
                ],
            },
        )
        assert save_response.status_code == 200
        db = next(app.dependency_overrides[get_db]())
        try:
            target = MonitoringTarget(
                user_id=1,
                platform="xhs",
                target_type="account",
                name="creator-002",
                value="creator-002",
                status="active",
            )
            keyword_target = MonitoringTarget(
                user_id=1,
                platform="xhs",
                target_type="keyword",
                name="普通关键词",
                value="creator-002",
                status="active",
            )
            intruder_target = MonitoringTarget(
                user_id=2,
                platform="xhs",
                target_type="account",
                name="intruder target",
                value="creator-002",
                status="active",
            )
            db.add_all([target, keyword_target, intruder_target])
            db.commit()
            target_id = target.id
            keyword_target_id = keyword_target.id
        finally:
            db.close()

        anonymous_response = client.post(f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts")
        assert anonymous_response.status_code == 401

        intruder_response = client.post(
            f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        keyword_response = client.post(
            f"/api/xhs/analytics/benchmarks/{keyword_target_id}/create-drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert keyword_response.status_code == 400

        response = client.post(
            f"/api/xhs/analytics/benchmarks/{target_id}/create-drafts?limit=1",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["created_count"] == 1
        assert payload["items"][0]["title"] == "creator-002 爆款标题"
        assert payload["items"][0]["source_note_id"] == save_response.json()["items"][0]["id"]

        db = next(app.dependency_overrides[get_db]())
        try:
            drafts = db.query(AiDraft).all()
            assert len(drafts) == 1
            assert drafts[0].user_id == 1
            assert drafts[0].platform == "xhs"
            assert drafts[0].body == "creator-002 的爆款正文"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_xhs_analytics_report_generates_owned_json_export_and_rejects_cross_user_notes(tmp_path):
    import json
    from pathlib import Path

    from backend.app.core.database import get_db
    from backend.app.models import PlatformAccount

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "analytics-report-owner")
    intruder_token = _register_and_get_access_token("analytics-report-intruder")
    try:
        anonymous_response = client.post("/api/xhs/analytics/reports")
        assert anonymous_response.status_code == 401

        owner_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "analytics-report-note-001",
                        "title": "Report note one",
                        "content": "Breakfast content with BrandA",
                        "author_name": "creator-report",
                        "raw": {"likes": 20, "collects": 5, "comments": 3, "shares": 2, "tags": ["breakfast"]},
                    },
                    {
                        "note_id": "analytics-report-note-002",
                        "title": "Report note two",
                        "content": "Storage content",
                        "author_name": "creator-report",
                        "raw": {"likes": 10, "collects": 1, "comments": 0, "shares": 0, "tags": ["storage"]},
                    },
                ],
            },
        )
        assert owner_save_response.status_code == 200
        owner_note_ids = [item["id"] for item in owner_save_response.json()["items"]]

        db = next(app.dependency_overrides[get_db]())
        try:
            intruder_account = PlatformAccount(
                user_id=2,
                platform="xhs",
                sub_type="pc",
                external_user_id="analytics-report-intruder",
                nickname="Intruder",
                status="active",
            )
            db.add(intruder_account)
            db.commit()
            intruder_account_id = intruder_account.id
        finally:
            db.close()

        intruder_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={
                "account_id": intruder_account_id,
                "notes": [
                    {
                        "note_id": "analytics-report-intruder-note",
                        "title": "Intruder note",
                        "content": "Not visible to owner",
                        "author_name": "intruder",
                        "raw": {"likes": 999},
                    }
                ],
            },
        )
        assert intruder_save_response.status_code == 200
        intruder_note_id = intruder_save_response.json()["items"][0]["id"]

        forbidden_response = client.post(
            "/api/xhs/analytics/reports",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [owner_note_ids[0], intruder_note_id], "format": "json"},
        )
        assert forbidden_response.status_code == 404

        report_response = client.post(
            "/api/xhs/analytics/reports",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": owner_note_ids, "format": "json"},
        )
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["report_type"] == "operations"
        assert report["note_count"] == 2
        assert report["summary"]["total_engagement"] == 41
        assert report["summary"]["top_notes"][0]["note_id"] == "analytics-report-note-001"
        assert report["file_name"].startswith("xhs-report-u1-")
        assert report["download_url"].startswith("/api/files/exports/xhs-report-u1-")
        # BE-10：响应不再包含服务器绝对路径
        assert "file_path" not in report

        report_path = Path(get_settings().storage_dir) / "exports" / report["file_name"]
        assert report_path.is_file()
        report_file = json.loads(report_path.read_text(encoding="utf-8"))
        assert report_file["metadata"]["user_id"] == 1
        assert report_file["summary"]["note_count"] == 2
        assert report_file["top_notes"][0]["title"] == "Report note one"

        download_response = client.get(
            report["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.json()["metadata"]["report_type"] == "operations"

        intruder_download_response = client.get(
            report["download_url"],
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_download_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
