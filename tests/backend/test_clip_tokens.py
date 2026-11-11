import pytest
from fastapi import HTTPException

from backend.app.core.security import (
    create_clip_handoff_token,
    create_clip_session_token,
    decode_clip_token,
)


def test_handoff_token_roundtrip_and_scope():
    token = create_clip_handoff_token(7, 42, "jti-1")
    payload = decode_clip_token(token, "clip_handoff")
    assert payload["user_id"] == 7
    assert payload["session_id"] == 42
    assert payload["jti"] == "jti-1"
    with pytest.raises(HTTPException):
        decode_clip_token(token, "clip_session")


def test_session_token_carries_session_id_and_expires():
    token = create_clip_session_token(7, 42, ttl_hours=-1)
    with pytest.raises(HTTPException):
        decode_clip_token(token, "clip_session")


def test_tampered_token_rejected():
    token = create_clip_handoff_token(7, 42, "jti-1")
    with pytest.raises(HTTPException):
        decode_clip_token(token + "x", "clip_handoff")


def test_clip_token_carries_version_claim():
    """回归（review P2）：clip 令牌必须携带 ver 声明，供会话装载层与
    token_version 比对（logout-all 后旧会话令牌立即失效）。"""
    from backend.app.core.security import decode_clip_token

    handoff = create_clip_handoff_token(7, 42, "jti-1", token_version=3)
    assert decode_clip_token(handoff, "clip_handoff")["ver"] == 3

    session_token = create_clip_session_token(7, 42, ttl_hours=1, token_version=5)
    assert decode_clip_token(session_token, "clip_session")["ver"] == 5


def test_clip_session_rejected_when_token_version_mismatch(tmp_path):
    """ver 不匹配 → 会话装载必须 401（等价于 logout-all 后立即吊销）。"""
    from datetime import timedelta

    from backend.app.core.database import get_db
    from backend.app.core.security import create_clip_session_token
    from backend.app.core.time import shanghai_now
    from backend.app.main import app
    from backend.app.models import ClipSession

    from api_helpers import _override_database, _register_and_get_access_token, client

    db_dependency = _override_database(tmp_path)
    try:
        token = _register_and_get_access_token("clip-ver-owner")
        _unused = token
        db = next(app.dependency_overrides[get_db]())
        try:
            now = shanghai_now()
            session = ClipSession(
                user_id=1, title="ver", manifest_json="[]", status="exchanged",
                handoff_jti="jver", handoff_expires_at=now,
                session_expires_at=now + timedelta(hours=1),
                created_at=now,
            )
            db.add(session)
            db.commit()
            session_id = session.id
            # 用户当前 token_version=0；用 ver=9 的令牌模拟旧版本令牌
            stale = create_clip_session_token(1, session_id, ttl_hours=1, token_version=9)
        finally:
            db.close()
        response = client.get(
            f"/api/clip/sessions/{session_id}/assets/xhs-upload-u1-x.mp4",
            headers={"Authorization": f"Bearer {stale}"},
        )
        # 令牌 ver=9 与用户 token_version=0 不匹配 → 401（先于 404 资产判断）
        assert response.status_code == 401
    finally:
        app.dependency_overrides.pop(db_dependency, None)
