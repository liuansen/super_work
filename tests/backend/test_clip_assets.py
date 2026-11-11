from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from api_helpers import *  # noqa: F401,F403


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    """把 storage_dir 隔离到临时目录。

    全局 media 目录含有真实开发数据；素材目录测试按名字精确断言，
    必须与存量文件隔离（计划原版测试在共享目录上会随机失败）。
    """
    from backend.app.core.config import Settings

    storage = tmp_path / "storage"
    (storage / "media").mkdir(parents=True)
    monkeypatch.setattr(Settings, "storage_dir", property(lambda self: storage))
    return storage


def _write_media(name: str, content: bytes) -> None:
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(content)


def test_asset_catalog_lists_owned_sources_and_filters(tmp_path, isolated_storage):
    db_dependency = _override_database(tmp_path)
    try:
        token = _register_and_get_access_token("clip-assets-owner")
        from backend.app.core.security import decode_token
        from backend.app.core.database import get_db
        from backend.app.models import AiDraft, DraftAsset, Note, NoteAsset

        user_id = decode_token(token)["user_id"]
        upload_name = _owned_media_fixture(token)
        note_name = f"xhs-asset-u{user_id}-{uuid4().hex}.mp4"
        draft_name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
        _write_media(note_name, b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
        _write_media(draft_name, b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)

        db = next(app.dependency_overrides[get_db]())
        try:
            note = Note(user_id=user_id, platform="xhs", note_id="note-1", title="参考笔记")
            db.add(note)
            db.flush()
            db.add(NoteAsset(note_id=note.id, asset_type="video", url="", local_path=note_name))
            draft = AiDraft(user_id=user_id, platform="xhs", title="草稿一")
            db.add(draft)
            db.flush()
            db.add(DraftAsset(draft_id=draft.id, asset_type="video", local_path=draft_name, sort_order=0))
            db.commit()
        finally:
            db.close()

        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/clip/assets", headers=headers)
        assert response.status_code == 200
        items = response.json()["items"]
        assert {item["source"] for item in items} == {"note", "draft", "upload"}
        assert {item["file_name"] for item in items} == {upload_name, note_name, draft_name}
        assert all(item["preview_url"].startswith("/api/files/media/") for item in items)

        video = client.get("/api/clip/assets?type=video&source=note", headers=headers).json()["items"]
        assert [item["file_name"] for item in video] == [note_name]

        searched = client.get("/api/clip/assets?q=参考", headers=headers).json()["items"]
        assert [item["file_name"] for item in searched] == [note_name]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for name in (upload_name, note_name, draft_name):
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_asset_catalog_isolated_between_users(tmp_path, isolated_storage):
    db_dependency = _override_database(tmp_path)
    try:
        owner = _register_and_get_access_token("clip-assets-user-a")
        other = _register_and_get_access_token("clip-assets-user-b")
        _owned_media_fixture(owner)
        response = client.get("/api/clip/assets", headers={"Authorization": f"Bearer {other}"})
        assert response.status_code == 200
        assert response.json()["items"] == []
    finally:
        app.dependency_overrides.pop(db_dependency, None)
