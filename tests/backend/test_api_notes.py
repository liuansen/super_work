"""笔记批量保存、素材、评论持久化、标签、导出与笔记库测试。

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

def test_notes_batch_save_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.post(
            "/api/notes/batch-save",
            json={"account_id": 1, "notes": [{"note_id": "note-001", "title": "标题"}]},
        )

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_save_persists_owned_search_results_and_updates_duplicates(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import Note

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "save-owner")
    try:
        first_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-save-001",
                        "title": "第一版标题",
                        "content": "第一版正文",
                        "author_name": "作者 A",
                        "raw": {"source": "search", "version": 1},
                    }
                ],
            },
        )
        assert first_response.status_code == 200
        first_payload = first_response.json()
        assert first_payload["saved_count"] == 1
        assert first_payload["items"][0]["note_id"] == "note-save-001"
        assert first_payload["items"][0]["title"] == "第一版标题"

        second_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-save-001",
                        "title": "第二版标题",
                        "content": "第二版正文",
                        "author_name": "作者 B",
                        "raw": {"source": "search", "version": 2},
                    }
                ],
            },
        )
        assert second_response.status_code == 200
        assert second_response.json()["saved_count"] == 1

        db = next(app.dependency_overrides[get_db]())
        try:
            notes = db.query(Note).all()
            assert len(notes) == 1
            assert notes[0].platform == "xhs"
            assert notes[0].platform_account_id == account_id
            assert notes[0].note_id == "note-save-001"
            assert notes[0].title == "第二版标题"
            assert notes[0].content == "第二版正文"
            assert notes[0].author_name == "作者 B"
            assert notes[0].raw_json == {"source": "search", "version": 2}
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_save_persists_detail_assets_and_lists_owned_assets(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteAsset

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "save-assets-owner")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-assets-001",
                        "title": "Asset detail title",
                        "content": "Asset detail body",
                        "author_name": "Asset author",
                        "image_urls": [
                            "https://example.test/detail-1.webp",
                            "https://example.test/detail-2.webp",
                        ],
                        "video_addr": "https://example.test/detail-video.mp4",
                        "cover_url": "https://example.test/detail-cover.webp",
                        "raw": {"source": "detail"},
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        saved_payload = save_response.json()["items"][0]
        note_id = saved_payload["id"]
        assert saved_payload["cover_url"] == "https://example.test/detail-1.webp"
        assert saved_payload["asset_urls"] == [
            "https://example.test/detail-1.webp",
            "https://example.test/detail-2.webp",
            "https://example.test/detail-video.mp4",
        ]

        list_response = client.get(
            f"/api/notes/{note_id}/assets",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 3
        assert [(item["asset_type"], item["url"]) for item in payload["items"]] == [
            ("image", "https://example.test/detail-1.webp"),
            ("image", "https://example.test/detail-2.webp"),
            ("video", "https://example.test/detail-video.mp4"),
        ]

        note_detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert note_detail_response.status_code == 200
        assert note_detail_response.json()["asset_urls"] == [
            "https://example.test/detail-1.webp",
            "https://example.test/detail-2.webp",
            "https://example.test/detail-video.mp4",
        ]

        update_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "notes": [
                    {
                        "note_id": "note-assets-001",
                        "title": "Asset detail title updated",
                        "image_urls": ["https://example.test/detail-2.webp"],
                    }
                ],
            },
        )
        assert update_response.status_code == 200

        db = next(app.dependency_overrides[get_db]())
        try:
            assets = db.query(NoteAsset).filter(NoteAsset.note_id == note_id).all()
            assert [(asset.asset_type, asset.url) for asset in assets] == [("image", "https://example.test/detail-2.webp")]
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_assets_reject_cross_user_note(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "assets-owner")
    intruder_token = _register_and_get_access_token("assets-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "note-assets-cross-001",
                        "title": "Owner note",
                        "image_urls": ["https://example.test/owner.webp"],
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        response = client.get(
            f"/api/notes/{note_id}/assets",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_save_fetches_and_persists_comments(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    class FakeXhsPcCommentPersistAdapter:
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
                                "id": "persist-comment-001",
                                "content": "Persisted top comment",
                                "like_count": "8",
                                "create_time": "2026-04-29 13:00:00",
                                "user_info": {"user_id": "persist-user-001", "nickname": "Persist author"},
                            }
                        ]
                    }
                },
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comment-persist-owner")
    FakeXhsPcCommentPersistAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentPersistAdapter
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "account_id": account_id,
                "fetch_comments": True,
                "notes": [
                    {
                        "note_id": "note-comments-001",
                        "note_url": "https://www.xiaohongshu.com/explore/note-comments-001",
                        "title": "Comment note",
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]
        assert FakeXhsPcCommentPersistAdapter.calls == [
            {
                "cookies": "a1=json-a1; web_session=json-session",
                "note_url": "https://www.xiaohongshu.com/explore/note-comments-001",
            }
        ]

        list_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 1
        assert payload["items"][0]["comment_id"] == "persist-comment-001"
        assert payload["items"][0]["user_name"] == "Persist author"
        assert payload["items"][0]["user_id"] == "persist-user-001"
        assert payload["items"][0]["content"] == "Persisted top comment"
        assert payload["items"][0]["like_count"] == 8
        assert payload["items"][0]["parent_comment_id"] is None
        assert payload["items"][0]["created_at_remote"] == "2026-04-29 13:00:00"

        db = next(app.dependency_overrides[get_db]())
        try:
            comments = db.query(NoteComment).filter(NoteComment.note_id == note_id).all()
            assert len(comments) == 1
            assert comments[0].raw_json["id"] == "persist-comment-001"
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_notes_batch_save_replaces_stale_comments_on_refetch(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentReplaceAdapter:
        calls = []

        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            self.calls.append(note_url)
            comment_id = "stale-comment" if len(self.calls) == 1 else "fresh-comment"
            return (
                True,
                "ok",
                {"data": {"comments": [{"id": comment_id, "content": comment_id, "user_info": {"nickname": "User"}}]}},
            )

    db_dependency, access_token, account_id = _create_pc_account_with_cookie(tmp_path, "comment-replace-owner")
    FakeXhsPcCommentReplaceAdapter.calls = []
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentReplaceAdapter
    try:
        for _ in range(2):
            save_response = client.post(
                "/api/notes/batch-save",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "account_id": account_id,
                    "fetch_comments": True,
                    "notes": [
                        {
                            "note_id": "note-comments-replace-001",
                            "note_url": "https://www.xiaohongshu.com/explore/note-comments-replace-001",
                            "title": "Replace comments",
                        }
                    ],
                },
            )
            assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]

        list_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["total"] == 1
        assert list_response.json()["items"][0]["comment_id"] == "fresh-comment"
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_notes_comments_list_requires_auth_and_enforces_ownership(tmp_path):
    from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory

    class FakeXhsPcCommentListAdapter:
        def __init__(self, cookies):
            self.cookies = cookies

        def get_note_comments(self, note_url):
            return (
                True,
                "ok",
                {"data": {"comments": [{"id": "owned-comment", "content": "Owned", "user_info": {"nickname": "User"}}]}},
            )

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "comments-list-owner")
    intruder_token = _register_and_get_access_token("comments-list-intruder")
    app.dependency_overrides[get_xhs_pc_api_adapter_factory] = lambda: FakeXhsPcCommentListAdapter
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "fetch_comments": True,
                "notes": [
                    {
                        "note_id": "note-comments-owned-001",
                        "note_url": "https://www.xiaohongshu.com/explore/note-comments-owned-001",
                        "title": "Owned comment note",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        anonymous_response = client.get(f"/api/notes/{note_id}/comments")
        assert anonymous_response.status_code == 401

        intruder_response = client.get(
            f"/api/notes/{note_id}/comments",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        app.dependency_overrides.pop(get_xhs_pc_api_adapter_factory, None)

def test_tags_crud_are_user_scoped_and_validate_duplicates(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        owner_token = _register_and_get_access_token("tags-crud-owner")
        intruder_token = _register_and_get_access_token("tags-crud-intruder")

        create_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "High value", "color": "#111111"},
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "High value"
        assert created["color"] == "#111111"

        duplicate_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "High value", "color": "#ef4444"},
        )
        assert duplicate_response.status_code == 400

        owner_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_list_response.status_code == 200
        assert owner_list_response.json()["total"] == 1

        intruder_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_list_response.status_code == 200
        assert intruder_list_response.json()["total"] == 0

        intruder_update_response = client.patch(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "Stolen"},
        )
        assert intruder_update_response.status_code == 404

        update_response = client.patch(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Rewrite queue", "color": "#2563eb"},
        )
        assert update_response.status_code == 200
        assert update_response.json()["name"] == "Rewrite queue"
        assert update_response.json()["color"] == "#2563eb"

        intruder_delete_response = client.delete(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_delete_response.status_code == 404

        delete_response = client.delete(
            f"/api/tags/{created['id']}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert delete_response.status_code == 200
        assert delete_response.json() == {"id": created["id"], "status": "deleted"}

        empty_list_response = client.get(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert empty_list_response.json()["total"] == 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_tag_applies_and_removes_owned_tags(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-tag-owner")
    try:
        first_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Rewrite", "color": "#111111"},
        ).json()
        second_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Benchmark", "color": "#2563eb"},
        ).json()
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "note-tags-001",
                        "title": "Tagged note",
                        "content": "Tag me",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        replace_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [first_tag["id"]], "mode": "replace"},
        )
        assert replace_response.status_code == 200
        assert replace_response.json()["updated_count"] == 1
        assert replace_response.json()["items"][0]["tags"] == [first_tag]

        add_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [second_tag["id"]], "mode": "add"},
        )
        assert add_response.status_code == 200
        assert [tag["name"] for tag in add_response.json()["items"][0]["tags"]] == ["Rewrite", "Benchmark"]

        remove_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [first_tag["id"]], "mode": "remove"},
        )
        assert remove_response.status_code == 200
        assert remove_response.json()["items"][0]["tags"] == [second_tag]

        detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 200
        assert detail_response.json()["tags"] == [second_tag]

        list_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["tags"] == [second_tag]
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_tag_rejects_cross_user_note_or_tag(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-tag-cross-owner")
    intruder_token = _register_and_get_access_token("batch-tag-cross-intruder")
    try:
        owner_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Owner tag", "color": "#111111"},
        ).json()
        intruder_tag = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"name": "Intruder tag", "color": "#ef4444"},
        ).json()
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [{"note_id": "note-tags-cross-001", "title": "Owner note"}],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        intruder_note_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_id], "tag_ids": [intruder_tag["id"]], "mode": "replace"},
        )
        assert intruder_note_response.status_code == 404

        owner_cross_tag_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [intruder_tag["id"]], "mode": "replace"},
        )
        assert owner_cross_tag_response.status_code == 404

        owner_valid_response = client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [owner_tag["id"]], "mode": "replace"},
        )
        assert owner_valid_response.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_create_drafts_creates_owned_drafts_and_rejects_cross_user_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "batch-drafts-owner")
    intruder_token = _register_and_get_access_token("batch-drafts-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {"note_id": "batch-draft-001", "title": "First source", "content": "First body"},
                    {"note_id": "batch-draft-002", "title": "Second source", "content": "Second body"},
                ],
            },
        )
        assert save_response.status_code == 200
        note_ids = [item["id"] for item in save_response.json()["items"]]

        response = client.post(
            "/api/notes/batch-create-drafts",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": note_ids, "intent": "rewrite"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["created_count"] == 2
        assert [item["title"] for item in payload["items"]] == ["First source", "Second source"]
        assert [item["body"] for item in payload["items"]] == ["First body", "Second body"]
        assert [item["source_note_id"] for item in payload["items"]] == note_ids

        intruder_response = client.post(
            "/api/notes/batch-create-drafts",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_ids[0]], "intent": "rewrite"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_export_writes_json_for_owned_notes_and_rejects_cross_user_notes(tmp_path):
    import json
    from pathlib import Path

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "notes-export-owner")
    intruder_token = _register_and_get_access_token("notes-export-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "export-note-001",
                        "title": "Exported note",
                        "content": "Export body",
                        "author_name": "Export author",
                        "raw": {"source": "unit-test"},
                    }
                ],
            },
        )
        assert save_response.status_code == 200
        note_id = save_response.json()["items"][0]["id"]
        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Export", "color": "#111111"},
        )
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "tag_ids": [tag_response.json()["id"]], "mode": "replace"},
        )

        response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "format": "json"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["exported_count"] == 1
        assert payload["file_name"].endswith(".json")
        assert f"u{1}-" in payload["file_name"]
        # BE-10：响应不再包含服务器绝对路径，测试用 file_name 自行拼出落盘位置
        assert "file_path" not in payload
        export_path = Path(get_settings().storage_dir) / "exports" / payload["file_name"]
        assert export_path.exists()
        exported = json.loads(export_path.read_text(encoding="utf-8"))
        assert exported["items"][0]["note_id"] == "export-note-001"
        assert exported["items"][0]["tags"][0]["name"] == "Export"

        download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        assert download_response.json()["items"][0]["note_id"] == "export-note-001"

        intruder_download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_download_response.status_code == 404

        intruder_response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"note_ids": [note_id], "format": "json"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_export_writes_csv_for_owned_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "notes-export-csv-owner")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "export-csv-001",
                        "title": "CSV 标题",
                        "content": "CSV 正文",
                        "author_name": "CSV 作者",
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        response = client.post(
            "/api/notes/export",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [note_id], "format": "csv"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["file_name"].endswith(".csv")
        download_response = client.get(
            payload["download_url"],
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert download_response.status_code == 200
        csv_text = download_response.content.decode("utf-8-sig")
        assert "note_id,title,author_name,content,tags,created_at" in csv_text
        assert "export-csv-001" in csv_text
        assert "CSV 标题" in csv_text
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_batch_save_rejects_cross_user_account(tmp_path):
    db_dependency, _, account_id = _create_pc_account_with_cookie(tmp_path, "save-owner-2")
    intruder_token = _register_and_get_access_token("save-intruder")
    try:
        response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {intruder_token}"},
            json={"account_id": account_id, "notes": [{"note_id": "note-001", "title": "标题"}]},
        )

        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_library_list_requires_authentication(tmp_path):
    db_dependency = _override_database(tmp_path)
    try:
        response = client.get("/api/notes?platform=xhs")

        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_library_list_returns_only_current_user_saved_notes(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-owner")
    intruder_token = _register_and_get_access_token("library-intruder")
    try:
        owner_save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "owner-note-001",
                        "title": "我的内容库笔记",
                        "content": "这条应该只属于 owner。",
                        "author_name": "作者 Owner",
                        "raw": {"source": "owner"},
                    }
                ],
            },
        )
        assert owner_save_response.status_code == 200

        intruder_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 200
        assert intruder_response.json()["total"] == 0

        owner_response = client.get(
            "/api/notes?platform=xhs",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        payload = owner_response.json()
        assert payload["total"] == 1
        assert payload["page"] == 1
        assert payload["page_size"] == 20
        assert payload["items"][0]["note_id"] == "owner-note-001"
        assert payload["items"][0]["title"] == "我的内容库笔记"
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_library_filters_by_keyword_tag_assets_and_comments(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import NoteComment

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-filter-owner")
    intruder_token = _register_and_get_access_token("library-filter-intruder")
    try:
        first_save = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "filter-note-assets",
                        "title": "低卡早餐灵感",
                        "content": "适合通勤前快速准备。",
                        "author_name": "早餐研究员",
                        "image_urls": ["https://example.test/filter-assets.webp"],
                    },
                    {
                        "note_id": "filter-note-comments",
                        "title": "旅行收纳清单",
                        "content": "评论里有很多问题。",
                        "author_name": "收纳作者",
                    },
                ],
            },
        )
        assert first_save.status_code == 200
        asset_note_id = first_save.json()["items"][0]["id"]
        comment_note_id = first_save.json()["items"][1]["id"]

        tag_response = client.post(
            "/api/tags",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"name": "Breakfast", "color": "#111111"},
        )
        tag_id = tag_response.json()["id"]
        client.post(
            "/api/notes/batch-tag",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"note_ids": [asset_note_id], "tag_ids": [tag_id], "mode": "replace"},
        )
        db = next(app.dependency_overrides[get_db]())
        try:
            db.add(
                NoteComment(
                    note_id=comment_note_id,
                    comment_id="filter-comment-001",
                    user_name="评论用户",
                    content="这条笔记有评论",
                )
            )
            db.commit()
        finally:
            db.close()

        keyword_response = client.get(
            "/api/notes?platform=xhs&q=早餐",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert keyword_response.status_code == 200
        assert [item["note_id"] for item in keyword_response.json()["items"]] == ["filter-note-assets"]

        tag_filter_response = client.get(
            f"/api/notes?platform=xhs&tag_id={tag_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert tag_filter_response.status_code == 200
        assert [item["note_id"] for item in tag_filter_response.json()["items"]] == ["filter-note-assets"]

        assets_response = client.get(
            "/api/notes?platform=xhs&has_assets=true",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert assets_response.status_code == 200
        assert [item["note_id"] for item in assets_response.json()["items"]] == ["filter-note-assets"]

        comments_response = client.get(
            "/api/notes?platform=xhs&has_comments=true",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert comments_response.status_code == 200
        assert [item["note_id"] for item in comments_response.json()["items"]] == ["filter-note-comments"]

        intruder_response = client.get(
            f"/api/notes?platform=xhs&tag_id={tag_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_library_detail_enforces_ownership(tmp_path):
    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-detail-owner")
    intruder_token = _register_and_get_access_token("library-detail-intruder")
    try:
        save_response = client.post(
            "/api/notes/batch-save",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={
                "account_id": owner_account_id,
                "notes": [
                    {
                        "note_id": "detail-note-001",
                        "title": "详情页笔记",
                        "content": "详情正文",
                        "author_name": "详情作者",
                        "raw": {"source": "detail"},
                    }
                ],
            },
        )
        note_id = save_response.json()["items"][0]["id"]

        owner_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json()["note_id"] == "detail-note-001"
        assert owner_response.json()["raw_json"] == {"source": "detail"}

        intruder_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)

def test_notes_library_delete_removes_owned_note_children_and_rejects_cross_user(tmp_path):
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft, Note, NoteAsset, NoteComment, Tag, note_tags

    db_dependency, owner_token, owner_account_id = _create_pc_account_with_cookie(tmp_path, "library-delete-owner")
    intruder_token = _register_and_get_access_token("library-delete-intruder")
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            note = Note(
                user_id=1,
                platform_account_id=owner_account_id,
                platform="xhs",
                note_id="delete-note-001",
                title="Delete me",
            )
            tag = Tag(user_id=1, name="待删除", color="#111111")
            db.add_all([note, tag])
            db.flush()
            db.add(NoteAsset(note_id=note.id, asset_type="image", url="https://example.test/delete.webp"))
            db.add(NoteComment(note_id=note.id, comment_id="delete-comment", content="删除评论"))
            db.add(AiDraft(user_id=1, platform="xhs", title="Draft", body="Body", source_note_id=note.id))
            db.execute(note_tags.insert().values(note_id=note.id, tag_id=tag.id))
            db.commit()
            note_id = note.id
        finally:
            db.close()

        intruder_response = client.delete(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {intruder_token}"},
        )
        assert intruder_response.status_code == 404

        owner_response = client.delete(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert owner_response.status_code == 200
        assert owner_response.json() == {"id": note_id, "status": "deleted"}

        detail_response = client.get(
            f"/api/notes/{note_id}",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert detail_response.status_code == 404

        db = next(app.dependency_overrides[get_db]())
        try:
            assert db.get(Note, note_id) is None
            assert db.query(NoteAsset).filter(NoteAsset.note_id == note_id).count() == 0
            assert db.query(NoteComment).filter(NoteComment.note_id == note_id).count() == 0
            assert db.execute(select(note_tags).where(note_tags.c.note_id == note_id)).first() is None
            assert db.query(AiDraft).filter(AiDraft.source_note_id == note_id).count() == 0
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
