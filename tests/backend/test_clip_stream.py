from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403


def _prepare(tmp_path):
    db_dependency = _override_database(tmp_path)
    from backend.app.core.security import decode_token

    token = _register_and_get_access_token("clip-stream-owner")
    user_id = decode_token(token)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0123456789")
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/clip/sessions",
        headers=headers,
        json={"title": "流测试", "assets": [{"kind": "upload", "file_name": name}]},
    )
    handoff = created.json()["handoff_token"]
    session_id = created.json()["session_id"]
    exchanged = client.post(
        f"/api/clip/sessions/{session_id}/exchange",
        headers={"Authorization": f"Bearer {handoff}"},
    )
    return db_dependency, token, name, session_id, exchanged.json()["session_token"]


def test_stream_asset_supports_range_and_rejects_unknown_name(tmp_path):
    db_dependency, token, name, session_id, session_token = _prepare(tmp_path)
    try:
        url = f"/api/clip/sessions/{session_id}/assets/{name}"
        full = client.get(url, headers={"Authorization": f"Bearer {session_token}"})
        assert full.status_code == 200
        assert full.headers["cache-control"] == "private, no-store"

        partial = client.get(
            url,
            headers={"Authorization": f"Bearer {session_token}", "Range": "bytes=0-3"},
        )
        assert partial.status_code == 206
        assert partial.content == b"\x00\x00\x00\x18"
        assert partial.headers["content-range"].startswith("bytes 0-3/")

        missing = client.get(
            f"/api/clip/sessions/{session_id}/assets/xhs-upload-u1-missing.mp4",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert missing.status_code == 404

        no_token = client.get(url)
        assert no_token.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_expired_session_token_returns_410(tmp_path):
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import ClipSession

    db_dependency, token, name, session_id, session_token = _prepare(tmp_path)
    try:
        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(ClipSession, session_id)
            session.session_expires_at = shanghai_now() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()
        response = client.get(
            f"/api/clip/sessions/{session_id}/assets/{name}",
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert response.status_code == 410
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)
