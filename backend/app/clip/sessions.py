from __future__ import annotations

import json
from datetime import timedelta
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.clip.assets import asset_type_for, resolve_clip_asset
from backend.app.clip.schemas import ClipSessionCreateRequest
from backend.app.core.config import Settings
from backend.app.core.media_source import InvalidMediaSource
from backend.app.core.security import (
    create_clip_handoff_token,
    create_clip_session_token,
    decode_clip_token,
)
from backend.app.core.time import shanghai_now
from backend.app.models import ClipSession

HANDOFF_TTL_MINUTES = 5


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _active_session_count(db: Session, user_id: int) -> int:
    """活跃会话数：已签发未过期（握手未过期）+ 已交换未过期。"""
    now = shanghai_now()
    return int(
        db.scalar(
            select(func.count())
            .select_from(ClipSession)
            .where(
                ClipSession.user_id == user_id,
                ClipSession.status.in_(("issued", "exchanged")),
                or_(
                    ClipSession.session_expires_at > now,
                    and_(
                        ClipSession.session_expires_at.is_(None),
                        ClipSession.handoff_expires_at > now,
                    ),
                ),
            )
        )
        or 0
    )


def create_clip_session(
    db: Session, user_id: int, payload: ClipSessionCreateRequest, settings: Settings
) -> tuple[ClipSession, str]:
    if _active_session_count(db, user_id) >= settings.clip_max_active_sessions:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="进行中的剪辑会话过多，请先完成或放弃旧会话")

    manifest: list[dict] = []
    seen: set[str] = set()
    for item in payload.assets:
        try:
            file_name, size_bytes = resolve_clip_asset(
                db, user_id, kind=item.kind, ref_id=item.id, file_name=item.file_name
            )
        except InvalidMediaSource as exc:
            raise _bad_request(str(exc)) from exc
        if file_name in seen:
            continue
        seen.add(file_name)
        manifest.append(
            {
                "file_name": file_name,
                "asset_type": asset_type_for(file_name) or "video",
                "size_bytes": size_bytes,
            }
        )
    if not manifest:
        raise _bad_request("至少选择一个有效素材")

    now = shanghai_now()
    jti = uuid4().hex
    title = payload.title.strip()
    if not title:
        raise _bad_request("会话标题不能为空")

    session = ClipSession(
        user_id=user_id,
        title=title,
        manifest_json=json.dumps(manifest, ensure_ascii=False),
        status="issued",
        handoff_jti=jti,
        handoff_expires_at=now + timedelta(minutes=HANDOFF_TTL_MINUTES),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    from backend.app.models import User

    user = db.get(User, user_id)
    version = int(user.token_version or 0) if user else 0
    return session, create_clip_handoff_token(user_id, session.id, jti, token_version=version)


def exchange_clip_session(
    db: Session, session_id: int, token: str, ttl_hours: int
) -> tuple[ClipSession, str, list[dict]]:
    """一次性握手：校验 jti + 归属 + 过期，签发 12h 会话令牌。

    重放防御：status 只有 issued → exchanged 一个方向，重复交换直接 409。
    """
    payload = decode_clip_token(token, "clip_handoff")
    if int(payload["session_id"]) != int(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    session = db.get(ClipSession, session_id)
    if session is None or session.user_id != payload["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    from backend.app.models import User

    user = db.get(User, session.user_id)
    if user is None or int(payload.get("ver") or 0) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid clip token")
    # 应用权限：handoff 令牌没有 access 身份，无法走路由级门禁，
    # 这里显式校验持令牌用户的 clip 权限（回收后握手/换令牌一并失效）
    from backend.app.core.deps import HTTPException as _HTTPException
    from backend.app.services.app_perms import user_has_access

    if not user_has_access(db, user, "clip"):
        raise _HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该应用未对当前账号开通，请联系管理员",
        )
    now = shanghai_now()
    if session.status != "issued":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="剪辑会话已交换或已结束")
    if session.handoff_jti != payload.get("jti"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid clip token")
    if session.handoff_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="剪辑会话已过期，请返回工作台重新进入")

    # 条件更新防并发重放：两个请求同时通过 status 检查时，
    # 只有第一个能置位（WHERE status='issued'），第二个 rowcount=0 → 409
    claimed = db.execute(
        update(ClipSession)
        .where(ClipSession.id == session.id, ClipSession.status == "issued")
        .values(
            status="exchanged",
            exchanged_at=now,
            session_expires_at=now + timedelta(hours=ttl_hours),
        )
    )
    claimed_count = claimed.rowcount  # commit 前读取，避免个别驱动在事务释放后清 cursor
    db.commit()
    if claimed_count != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="剪辑会话已交换或已结束")
    db.refresh(session)
    user = db.get(User, session.user_id)
    version = int(user.token_version or 0) if user else 0
    return (
        session,
        create_clip_session_token(session.user_id, session.id, ttl_hours, token_version=version),
        json.loads(session.manifest_json),
    )


def load_active_clip_session(
    db: Session, session_id: int, token: str
) -> tuple[ClipSession, list[dict]]:
    """用会话令牌装载活跃会话与素材清单。"""
    payload = decode_clip_token(token, "clip_session")
    if int(payload["session_id"]) != int(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    session = db.get(ClipSession, session_id)
    if session is None or session.user_id != payload["user_id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Clip session not found")
    from backend.app.models import User

    user = db.get(User, session.user_id)
    if user is None or int(payload.get("ver") or 0) != int(user.token_version or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid clip token")
    # 应用权限：本函数是 stream/upload 两条会话令牌消费路径的唯一汇聚点。
    # 回收 clip 后，用户已持有的 session 令牌必须立即失效（review 第 1 轮 P1：
    # 实机穿透——回收后 12h 内仍可流取素材/上传成片）。
    from backend.app.core.deps import HTTPException as _HTTPException
    from backend.app.services.app_perms import user_has_access

    if not user_has_access(db, user, "clip"):
        raise _HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该应用未对当前账号开通，请联系管理员",
        )
    now = shanghai_now()
    if session.status not in ("exchanged", "completed"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="剪辑会话不可用")
    if session.session_expires_at is None or session.session_expires_at <= now:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="剪辑会话已过期，请返回工作台重新进入")
    return session, json.loads(session.manifest_json)


def get_session_asset_path(
    db: Session, session_id: int, token: str, file_name: str
) -> "Path":
    """校验会话有效 + 文件在会话清单内 + 归属当前用户，返回本地路径。

    三重约束缺一不可：清单外文件即使带正确前缀也拒绝（会话级最小权限）。
    """
    from pathlib import Path

    from backend.app.core.media_source import InvalidMediaSource, assert_owned_media_name
    from backend.app.core.media_storage import media_dir

    session, manifest = load_active_clip_session(db, session_id, token)
    allowed = {item["file_name"] for item in manifest}
    if file_name not in allowed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    try:
        assert_owned_media_name(file_name, session.user_id)
    except InvalidMediaSource as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from exc
    path = media_dir() / file_name
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return path
