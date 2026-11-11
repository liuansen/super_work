from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"1" * 1024


def _decode_user_id(token: str) -> int:
    from backend.app.core.security import decode_token

    return int(decode_token(token)["user_id"])


def _session_token(tmp_path, username="clip-export-owner"):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    login = _register_and_get_access_token(username)
    user_id = decode_token(login)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(MP4)
    created = client.post(
        "/api/clip/sessions",
        headers={"Authorization": f"Bearer {login}"},
        json={"title": "成片测试", "assets": [{"kind": "upload", "file_name": name}]},
    )
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
    )
    return db_dependency, login, session_id, exchanged.json()["session_token"], name


def _upload(session_id, session_token, client_export_id="exp-1"):
    return client.post(
        "/api/clip/exports",
        headers={"Authorization": f"Bearer {session_token}"},
        data={
            "session_id": session_id,
            "title": "成片一",
            "client_export_id": client_export_id,
        },
        files={"file": ("clip.mp4", MP4, "video/mp4")},
    )


def test_upload_export_is_idempotent_and_listed(tmp_path):
    db_dependency, login, session_id, session_token, source_name = _session_token(tmp_path)
    try:
        first = _upload(session_id, session_token)
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["file_name"].startswith("xhs-clip-u1-")
        assert (Path(get_settings().storage_dir) / "media" / body["file_name"]).is_file()

        second = _upload(session_id, session_token)
        assert second.status_code == 200
        assert second.json()["id"] == body["id"]

        # 列表使用登录态而不是会话令牌
        rows = client.get("/api/clip/exports", headers={"Authorization": f"Bearer {login}"})
        assert rows.status_code == 200
        assert [item["id"] for item in rows.json()["items"]] == [body["id"]]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_upload_rejects_bad_type_and_oversize(tmp_path, monkeypatch):
    from backend.app.core.config import get_settings

    db_dependency, login, session_id, session_token, source_name = _session_token(tmp_path)
    try:
        # 计划原版测试漏传 session_id（会被 422 挡住而非到达 MP4 校验）
        bad = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"session_id": session_id, "title": "假视频", "client_export_id": "bad-1"},
            files={"file": ("clip.mp4", b"not-an-mp4", "video/mp4")},
        )
        assert bad.status_code == 400, bad.text

        monkeypatch.setattr(get_settings(), "clip_max_export_bytes", 16)
        big = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"session_id": session_id, "title": "过大", "client_export_id": "big-1"},
            files={"file": ("clip.mp4", MP4, "video/mp4")},
        )
        assert big.status_code == 413
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_export_ownership_isolated_between_users(tmp_path):
    """用户 B 不能查看/删除用户 A 的成片。"""
    from backend.app.core.config import get_settings

    db_dependency, login_a, session_id, session_token, source_name = _session_token(
        tmp_path, "clip-export-user-a"
    )
    try:
        from pathlib import Path as _P

        uploaded = _upload(session_id, session_token, client_export_id="iso-1")
        assert uploaded.status_code == 201, uploaded.text
        export_id = uploaded.json()["id"]

        # 用户 B 登录态
        b_token = _register_and_get_access_token("clip-export-user-b")
        b_headers = {"Authorization": f"Bearer {b_token}"}
        rows_b = client.get("/api/clip/exports", headers=b_headers)
        assert rows_b.status_code == 200
        assert rows_b.json()["items"] == []
        assert client.delete(f"/api/clip/exports/{export_id}", headers=b_headers).status_code == 404
        assert client.post(f"/api/clip/exports/{export_id}/draft", headers=b_headers).status_code == 404

        # 会话令牌只对单会话有效：用 B 的身份签发的“合法格式”会话令牌
        # 访问 A 的会话 → 404（归属不符），而不是 401 格式错误
        from backend.app.core.security import create_clip_session_token

        b_session_token = create_clip_session_token(
            int(_decode_user_id(b_token)), session_id, ttl_hours=1
        )
        foreign_asset = client.get(
            f"/api/clip/sessions/{session_id}/assets/xhs-upload-u{session_id}-x.mp4",
            headers={"Authorization": f"Bearer {b_session_token}"},
        )
        assert foreign_asset.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_upload_enforces_user_quota(tmp_path, monkeypatch):
    from backend.app.core.config import get_settings

    db_dependency, login, session_id, session_token, source_name = _session_token(
        tmp_path, "clip-export-quota"
    )
    try:
        settings = get_settings()
        monkeypatch.setattr(settings, "clip_user_export_quota_bytes", 1000)
        big = client.post(
            "/api/clip/exports",
            headers={"Authorization": f"Bearer {session_token}"},
            data={"session_id": session_id, "title": "超配额", "client_export_id": "quota-1"},
            files={"file": ("clip.mp4", MP4, "video/mp4")},
        )
        assert big.status_code == 413, big.text
        assert "配额" in big.json()["detail"]
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_clip_files_rejected_by_generic_media_delete(tmp_path):
    """成片必须走剪辑工坊删除，通用媒体删除接口要拒绝 xhs-clip- 前缀。"""
    from backend.app.core.config import get_settings

    db_dependency, login, session_id, session_token, source_name = _session_token(
        tmp_path, "clip-export-guard"
    )
    try:
        uploaded = _upload(session_id, session_token, client_export_id="guard-1")
        assert uploaded.status_code == 201, uploaded.text
        file_name = uploaded.json()["file_name"]

        blocked = client.delete(
            f"/api/files/images/{file_name}",
            headers={"Authorization": f"Bearer {login}"},
        )
        assert blocked.status_code == 409
        # 文件仍然存在且可下载
        assert (Path(get_settings().storage_dir) / "media" / file_name).is_file()
        download = client.get(
            f"/api/files/media/{file_name}", headers={"Authorization": f"Bearer {login}"}
        )
        assert download.status_code == 200
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            path.unlink(missing_ok=True)


def test_delete_export_tolerates_unlink_failure(tmp_path, monkeypatch):
    """终审建议：文件删除失败（下载流占用）不 500，行已删、记录告警。"""
    from backend.app.core.config import get_settings

    db_dependency, login, session_id, session_token, source_name = _session_token(
        tmp_path, "clip-export-unlink"
    )
    try:
        uploaded = _upload(session_id, session_token, client_export_id="unlink-1")
        assert uploaded.status_code == 201, uploaded.text
        export_id = uploaded.json()["id"]

        from backend.app.clip.exports import delete_clip_export
        from backend.app.core.database import get_db as _get_db

        real_delete = delete_clip_export

        def failing_unlink():
            raise OSError("file in use")

        import backend.app.clip.exports as exports_module

        db = next(app.dependency_overrides[_get_db]())
        try:
            monkeypatch.setattr(
                Path, "unlink", lambda self, missing_ok=False: failing_unlink()
            )
            # 不应抛异常
            real_delete(db, login and 1, export_id)
        finally:
            monkeypatch.undo()
            db.close()

        # 行已删：再次删除得到 404
        second = client.delete(
            f"/api/clip/exports/{export_id}", headers={"Authorization": f"Bearer {login}"}
        )
        assert second.status_code == 404
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / source_name).unlink(missing_ok=True)
        for path in (Path(get_settings().storage_dir) / "media").glob("xhs-clip-u1-*"):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
