import json
from pathlib import Path
from uuid import uuid4

from api_helpers import *  # noqa: F401,F403


def _video_for(token: str) -> str:
    from backend.app.core.security import decode_token

    user_id = decode_token(token)["user_id"]
    name = f"xhs-upload-u{user_id}-{uuid4().hex}.mp4"
    media = Path(get_settings().storage_dir) / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 128)
    return name


def test_create_and_exchange_session_once(tmp_path):
    db_dependency = _override_database(tmp_path)
    name = ""
    try:
        token = _register_and_get_access_token("clip-session-owner")
        name = _video_for(token)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/clip/sessions",
            headers=headers,
            json={"title": "开箱视频", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["editor_url"].startswith("http://")
        assert payload["handoff_token"]
        session_id = payload["session_id"]

        exchanged = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {payload['handoff_token']}"},
        )
        assert exchanged.status_code == 200, exchanged.text
        body = exchanged.json()
        assert body["session_token"]
        assert body["assets"][0]["file_name"] == name
        assert body["assets"][0]["download_path"].endswith(name)

        replay = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {payload['handoff_token']}"},
        )
        assert replay.status_code == 409
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        if name:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_expired_handoff_token_returns_410(tmp_path):
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.time import shanghai_now
    from backend.app.models import ClipSession

    db_dependency = _override_database(tmp_path)
    name = ""
    try:
        token = _register_and_get_access_token("clip-session-expired")
        name = _video_for(token)
        created = client.post(
            "/api/clip/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"title": "过期", "assets": [{"kind": "upload", "file_name": name}]},
        )
        session_id = created.json()["session_id"]
        db = next(app.dependency_overrides[get_db]())
        try:
            session = db.get(ClipSession, session_id)
            session.handoff_expires_at = shanghai_now() - timedelta(minutes=1)
            db.commit()
        finally:
            db.close()

        response = client.post(
            f"/api/clip/sessions/{session_id}/exchange",
            headers={"Authorization": f"Bearer {created.json()['handoff_token']}"},
        )
        assert response.status_code == 410
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        if name:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)


def test_session_rejects_foreign_asset_and_enforces_active_limit(tmp_path, monkeypatch):
    db_dependency = _override_database(tmp_path)
    names = []
    try:
        owner = _register_and_get_access_token("clip-session-a")
        other = _register_and_get_access_token("clip-session-b")
        name = _video_for(owner)
        names.append(name)
        headers_owner = {"Authorization": f"Bearer {owner}"}
        headers_other = {"Authorization": f"Bearer {other}"}

        foreign = client.post(
            "/api/clip/sessions",
            headers=headers_other,
            json={"title": "越权", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert foreign.status_code == 400

        from backend.app.core.config import get_settings

        monkeypatch.setattr(get_settings(), "clip_max_active_sessions", 2)
        for index in range(2):
            response = client.post(
                "/api/clip/sessions",
                headers=headers_owner,
                json={"title": f"会话{index}", "assets": [{"kind": "upload", "file_name": name}]},
            )
            assert response.status_code == 201
        over = client.post(
            "/api/clip/sessions",
            headers=headers_owner,
            json={"title": "超限", "assets": [{"kind": "upload", "file_name": name}]},
        )
        assert over.status_code == 409
    finally:
        app.dependency_overrides.pop(db_dependency, None)
        for name in names:
            (Path(get_settings().storage_dir) / "media" / name).unlink(missing_ok=True)
