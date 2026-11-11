from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.app.clip.assets import list_clip_assets
from backend.app.clip.exports import (
    create_draft_from_clip_export,
    delete_clip_export,
    list_clip_exports,
    save_clip_export,
    serialize_export,
)
from backend.app.clip.sessions import load_active_clip_session
from backend.app.clip.schemas import ClipSessionCreateRequest
from backend.app.clip.sessions import (
    create_clip_session,
    exchange_clip_session,
    get_session_asset_path,
)
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import User

from backend.app.core.deps import app_access_required

# 应用权限：剪辑工坊被回收/全局关闭后，该用户的 /api/clip/* 403。
# 注意不能挂在路由级：exchange 用的是 clip_handoff 令牌（非 access token），
# get_current_user 会 401；该端点在 sessions.py 内做显式权限校验。
_CLIP_APP_GATE = app_access_required("clip")

router = APIRouter(prefix="/clip", tags=["clip"])


@router.get("/health")
def clip_health(current_user: User = Depends(get_current_user)):
    return {"status": "ok", "user_id": current_user.id}


@router.get("/assets")
def get_clip_assets(
    q: str = "",
    asset_type: str = Query(default="", alias="type"),
    source: str = "",
    limit: int = Query(default=200, ge=1, le=200),
    current_user: User = Depends(_CLIP_APP_GATE),
    db: Session = Depends(get_db),
):
    return {
        "items": list_clip_assets(
            db,
            current_user.id,
            q=q,
            asset_type=asset_type,
            source=source,
            limit=limit,
        )
    }


def _bearer_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return authorization[7:].strip()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ClipSessionCreateRequest,
    current_user: User = Depends(_CLIP_APP_GATE),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, handoff_token = create_clip_session(db, current_user.id, payload, settings)
    return {
        "session_id": session.id,
        "editor_url": settings.clip_editor_public_base_url.rstrip("/"),
        "handoff_token": handoff_token,
        "handoff_expires_at": session.handoff_expires_at.isoformat(),
    }


@router.post("/sessions/{session_id}/exchange")
def exchange_session(
    session_id: int,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, session_token, manifest = exchange_clip_session(
        db, session_id, _bearer_token(authorization), settings.clip_session_ttl_hours
    )
    return {
        "session_token": session_token,
        "session_expires_at": session.session_expires_at.isoformat(),
        "assets": [
            {
                "file_name": item["file_name"],
                "asset_type": item["asset_type"],
                "size_bytes": item["size_bytes"],
                "download_path": f"/api/clip/sessions/{session.id}/assets/{item['file_name']}",
            }
            for item in manifest
        ],
    }


@router.get("/sessions/{session_id}/assets/{file_name}")
def stream_session_asset(
    session_id: int,
    file_name: str,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    path = get_session_asset_path(db, session_id, _bearer_token(authorization), file_name)
    media_type = "video/mp4" if file_name.lower().endswith(".mp4") else "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        filename=file_name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/exports", status_code=status.HTTP_201_CREATED)
async def upload_export(
    response: Response,
    session_id: int = Form(...),
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=120),
    client_export_id: str = Form(..., min_length=1, max_length=64),
    duration_ms: Optional[int] = Form(default=None),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    session, _manifest = load_active_clip_session(db, session_id, _bearer_token(authorization))
    export, created = await save_clip_export(
        db,
        session,
        file,
        title=title,
        client_export_id=client_export_id,
        duration_ms=duration_ms,
        settings=settings,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return serialize_export(export)


@router.get("/exports")
def get_exports(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(_CLIP_APP_GATE),
    db: Session = Depends(get_db),
):
    return {"items": list_clip_exports(db, current_user.id, limit)}


@router.delete("/exports/{export_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_export(
    export_id: int,
    current_user: User = Depends(_CLIP_APP_GATE),
    db: Session = Depends(get_db),
):
    delete_clip_export(db, current_user.id, export_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/exports/{export_id}/draft")
def export_to_xhs_draft(
    export_id: int,
    current_user: User = Depends(_CLIP_APP_GATE),
    db: Session = Depends(get_db),
):
    draft, created = create_draft_from_clip_export(db, current_user.id, export_id)
    return {"draft_id": draft.id, "created": created}
