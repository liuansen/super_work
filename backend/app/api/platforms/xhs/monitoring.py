from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.platforms.xhs.pc import get_xhs_pc_api_adapter_factory
from backend.app.api.tasks import serialize_task
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.time import shanghai_now
from backend.app.models import MonitoringSnapshot, MonitoringTarget, Note, PlatformAccount, Task, User
from backend.app.schemas.common import paginate_query, paginated
from backend.app.services.monitoring_crawl_service import execute_monitoring_refresh

from backend.app.services.xhs_serializers import (
    note_metrics as _note_metrics,
    serialize_monitoring_note as _serialize_monitoring_note,
    serialize_snapshot as _serialize_snapshot,
    serialize_target as _serialize_target,
)

router = APIRouter(prefix="/xhs/monitoring", tags=["xhs-monitoring"])


class MonitoringTargetCreateRequest(BaseModel):
    target_type: Literal["keyword", "account", "brand", "note_url"]
    name: str = Field(default="", max_length=128)
    value: str = Field(min_length=1, max_length=512)
    status: Literal["active", "paused"] = "active"
    config: dict[str, Any] = Field(default_factory=dict)


class MonitoringTargetUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=128)
    value: Optional[str] = Field(default=None, min_length=1, max_length=512)
    status: Optional[Literal["active", "paused"]] = None
    config: Optional[dict[str, Any]] = None


def _note_haystack(note: Note) -> str:
    # 统一实现见 services/note_search：读取写入时算好的 search_text
    from backend.app.services.note_search import note_haystack

    return note_haystack(note)


def _note_matches_target(note: Note, target: MonitoringTarget) -> bool:
    needle = target.value.strip().lower()
    if not needle:
        return False
    haystack = _note_haystack(note)
    return needle in haystack


def _matching_notes(db: Session, current_user: User, target: MonitoringTarget) -> list[Note]:
    # 复用调度器同一实现：SQL 预过滤（FTS/LIKE 走 search_text）+ Python 精筛 + 上限
    from backend.app.services.scheduler_service import _matching_notes_for_target

    return _matching_notes_for_target(db, target, "xhs")


def _get_owned_target(db: Session, current_user: User, target_id: int) -> MonitoringTarget:
    target = db.get(MonitoringTarget, target_id)
    if target is None or target.user_id != current_user.id or target.platform != "xhs":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitoring target not found")
    return target


@router.get("/targets")
def targets(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        select(MonitoringTarget).where(
            MonitoringTarget.user_id == current_user.id, MonitoringTarget.platform == "xhs"
        ),
        page=page,
        page_size=page_size,
        serializer=_serialize_target,
        order_by=(MonitoringTarget.created_at.desc(), MonitoringTarget.id.desc()),
    )


@router.post("/targets")
def create_target(
    payload: MonitoringTargetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = MonitoringTarget(
        user_id=current_user.id,
        platform="xhs",
        target_type=payload.target_type,
        name=payload.name or payload.value,
        value=payload.value,
        status=payload.status,
        config=payload.config,
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return _serialize_target(target)


@router.patch("/targets/{target_id}")
def update_target(
    target_id: int,
    payload: MonitoringTargetUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _get_owned_target(db, current_user, target_id)
    if payload.name is not None:
        target.name = payload.name
    if payload.value is not None:
        target.value = payload.value
    if payload.status is not None:
        target.status = payload.status
    if payload.config is not None:
        target.config = payload.config
    target.updated_at = shanghai_now()
    db.commit()
    db.refresh(target)
    return _serialize_target(target)


@router.delete("/targets/{target_id}")
def delete_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _get_owned_target(db, current_user, target_id)
    db.delete(target)
    db.commit()
    return {"id": target_id, "status": "deleted"}


@router.post("/targets/{target_id}/refresh")
def refresh_target(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
):
    target = _get_owned_target(db, current_user, target_id)
    return execute_monitoring_refresh(db, target, current_user, adapter_factory=adapter_factory)


@router.get("/targets/{target_id}/notes")
def target_notes(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _get_owned_target(db, current_user, target_id)
    return {"target_id": target.id, "items": [_serialize_monitoring_note(note) for note in _matching_notes(db, current_user, target)]}


@router.get("/targets/{target_id}/snapshots")
def target_snapshots(
    target_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target = _get_owned_target(db, current_user, target_id)
    snapshots = db.scalars(
        select(MonitoringSnapshot)
        .where(MonitoringSnapshot.target_id == target.id)
        .order_by(MonitoringSnapshot.created_at.desc(), MonitoringSnapshot.id.desc())
    ).all()
    return {"target_id": target.id, "items": [_serialize_snapshot(snapshot) for snapshot in snapshots]}
