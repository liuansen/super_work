from pathlib import Path
from uuid import uuid4

from sqlalchemy import update as _update

from api_helpers import *  # noqa: F401,F403

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"2" * 512


def _export_for(tmp_path, username="clip-draft-owner"):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    login = _register_and_get_access_token(username)
    user_id = decode_token(login)["user_id"]
    source = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / source).write_bytes(MP4)
    created = client.post(
        "/api/clip/sessions",
        headers={"Authorization": f"Bearer {login}"},
        json={"title": "草稿来源", "assets": [{"kind": "upload", "file_name": source}]},
    )
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
    )
    export = client.post(
        "/api/clip/exports",
        headers={"Authorization": f"Bearer {exchanged.json()['session_token']}"},
        data={"session_id": session_id, "title": "成片标题", "client_export_id": "draft-1"},
        files={"file": ("clip.mp4", MP4, "video/mp4")},
    )
    return db_dependency, login, user_id, source, export.json()


def test_export_creates_one_xhs_draft_and_links_it(tmp_path):
    db_dependency, login, user_id, source, export = _export_for(tmp_path)
    try:
        headers = {"Authorization": f"Bearer {login}"}
        first = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert first.status_code == 200, first.text
        draft_id = first.json()["draft_id"]

        second = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert second.status_code == 200
        assert second.json()["draft_id"] == draft_id
        assert second.json()["created"] is False

        blocked = client.delete(f"/api/clip/exports/{export['id']}", headers=headers)
        assert blocked.status_code == 409

        from backend.app.core.database import get_db
        from backend.app.models import AiDraft, DraftAsset

        db = next(app.dependency_overrides[get_db]())
        try:
            draft = db.get(AiDraft, draft_id)
            assert draft.user_id == user_id
            assert draft.platform == "xhs"
            assets = db.query(DraftAsset).filter_by(draft_id=draft_id).all()
            assert len(assets) == 1
            assert assets[0].asset_type == "video"
            assert assets[0].local_path == export["file_name"]
        finally:
            db.close()

        download = client.get(f"/api/files/media/{export['file_name']}", headers=headers)
        assert download.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)


def test_clip_prefix_is_accepted_by_douyin_and_ignored_by_cleanup(tmp_path):
    db_dependency, login, user_id, source, export = _export_for(tmp_path, "clip-prefix-owner")
    try:
        from backend.app.douyin.publishing import resolve_media_paths
        from backend.app.services.media_cleanup import prune_media_dir

        resolved = resolve_media_paths(user_id, [export["file_name"]])
        assert Path(resolved[0]).name == export["file_name"]

        temp_media = tmp_path / "prune-media"
        temp_media.mkdir()
        keep = temp_media / export["file_name"]
        keep.write_bytes(b"x")
        prune_media_dir(temp_media, max_age_days=0, max_total_bytes=0)
        assert keep.exists()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)


def test_delete_linked_draft_releases_export(tmp_path):
    """回归（review P1）：删除已关联成片的草稿必须成功，成片回到 available。"""
    from backend.app.core.config import get_settings

    db_dependency, login, user_id, source, export = _export_for(tmp_path, "clip-draft-delete")
    try:
        headers = {"Authorization": f"Bearer {login}"}
        first = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert first.status_code == 200, first.text
        draft_id = first.json()["draft_id"]

        deleted = client.delete(f"/api/drafts/{draft_id}", headers=headers)
        assert deleted.status_code == 200, deleted.text

        # 成片解除引用后可重新送入草稿
        again = client.post(f"/api/clip/exports/{export['id']}/draft", headers=headers)
        assert again.status_code == 200, again.text
        # created=True 表示成片已解除旧引用并创建了新草稿
        # （SQLite 复用 rowid，新草稿 id 可能与旧值相同，不作断言）
        assert again.json()["created"] is True
        assert again.json()["draft_id"] > 0
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)


def test_concurrent_draft_creation_leaves_no_orphan(tmp_path):
    """终审 P2 回归：并发「送入草稿」败者（条件 UPDATE 0 行）不得提交孤儿。

    SQLite 单写者无法在进程内真并发；这里用 execute 拦截代理把败者路径
    的条件 UPDATE 强制报 0 行，直接验证「先回滚后裁决」的顺序契约。
    """
    from backend.app.core.database import get_db
    from backend.app.models import AiDraft, ClipExport
    from backend.app.clip.exports import create_draft_from_clip_export

    db_dependency, login, user_id, source, export = _export_for(tmp_path, "clip-draft-race")
    try:
        # 预置赢家：另一请求已把成片关联到草稿 999（外部提交状态）
        db = next(app.dependency_overrides[get_db]())
        try:
            # 预置真实存在的赢家草稿（FK 需要）
            winner = AiDraft(user_id=user_id, platform="xhs", title="winner", body="")
            db.add(winner)
            db.flush()
            winner_id = winner.id
            db.execute(
                _update(ClipExport)
                .where(ClipExport.id == export["id"])
                .values(linked_draft_id=winner_id, status="linked")
            )
            db.commit()

            class _LoserSession:
                """代理：让被测函数走败者路径（条件 UPDATE 报 0 行）。"""

                def __init__(self, real):
                    self._real = real

                def execute(self, stmt, *args, **kwargs):
                    result = self._real.execute(stmt, *args, **kwargs)
                    if isinstance(stmt, _update) and stmt.table.name == "clip_exports":
                        # 模拟另一请求抢先置位导致本请求 rowcount=0
                        class _R:
                            rowcount = 0

                        return _R()
                    return result

                def __getattr__(self, name):
                    return getattr(self._real, name)

            proxy = _LoserSession(db)
            draft, created = create_draft_from_clip_export(proxy, user_id, export["id"])

            # 败者裁决：返回赢家草稿
            assert created is False
            assert draft.id == winner_id
            # 关键断言：败者的孤儿草稿不得落库（修复前 commit 先于裁决会留下 2 行）
            assert db.query(AiDraft).count() == 1
            assert db.query(ClipExport).filter_by(id=export["id"]).one().linked_draft_id == winner_id
        finally:
            db.close()
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)
        (Path(get_settings().storage_dir) / "media" / source).unlink(missing_ok=True)
