from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.core.media_storage import media_dir
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession

CHUNK_SIZE = 1024 * 1024


def serialize_export(export: ClipExport) -> dict:
    return {
        "id": export.id,
        "title": export.title,
        "file_name": export.file_name,
        "mime": export.mime,
        "size_bytes": export.size_bytes,
        "duration_ms": export.duration_ms,
        "status": export.status,
        "linked_draft_id": export.linked_draft_id,
        "created_at": export.created_at.isoformat(),
        "download_url": f"/api/files/media/{export.file_name}",
    }


def list_clip_exports(db: Session, user_id: int, limit: int = 50) -> list[dict]:
    limit = max(1, min(int(limit), 200))
    rows = db.scalars(
        select(ClipExport)
        .where(ClipExport.user_id == user_id)
        .order_by(ClipExport.created_at.desc(), ClipExport.id.desc())
        .limit(limit)
    ).all()
    return [serialize_export(row) for row in rows]


async def save_clip_export(
    db: Session,
    session: ClipSession,
    upload: UploadFile,
    *,
    title: str,
    client_export_id: str,
    duration_ms: Optional[int],
    settings: Settings,
) -> tuple[ClipExport, bool]:
    """落盘成片（临时文件 → 原子改名），幂等键 (session_id, client_export_id)。

    幂等语义：同一次导出的重试不会产生第二份文件；并发下靠唯一约束兜底，
    撞约束时删除本次落盘文件并返回已有记录。
    """
    existing = db.scalar(
        select(ClipExport).where(
            ClipExport.session_id == session.id,
            ClipExport.client_export_id == client_export_id,
        )
    )
    if existing is not None:
        return existing, False

    ext = Path(upload.filename or "").suffix.lower()
    if ext != ".mp4":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="首期只支持 MP4 成片")

    # 配额预检（SEC-4 同款思路）：声明大小 + 存量在开始流式写之前就拒绝，
    # 避免先把 2GiB 落盘才发现超配额；声明缺失时由流式路径兜底。
    used_now = int(
        db.scalar(
            select(func.coalesce(func.sum(ClipExport.size_bytes), 0)).where(
                ClipExport.user_id == session.user_id
            )
        )
        or 0
    )
    declared = getattr(upload, "size", None)
    if (
        declared is not None
        and used_now + int(declared) > settings.clip_user_export_quota_bytes
    ):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="成片总容量超过配额，请先删除旧成片",
        )

    directory = media_dir()
    directory.mkdir(parents=True, exist_ok=True)
    tmp_path = directory / f".clip-upload-{uuid4().hex}.part"
    total = 0
    try:
        with tmp_path.open("wb") as output:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.clip_max_export_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"成片超过 {settings.clip_max_export_bytes} 字节上限",
                    )
                output.write(chunk)

        with tmp_path.open("rb") as check:
            head = check.read(12)
        if len(head) < 8 or head[4:8] != b"ftyp":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件不是有效的 MP4")

        used = int(
            db.scalar(
                select(func.coalesce(func.sum(ClipExport.size_bytes), 0)).where(
                    ClipExport.user_id == session.user_id
                )
            )
            or 0
        )
        if used + total > settings.clip_user_export_quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="成片总容量超过配额，请先删除旧成片",
            )

        final_name = f"xhs-clip-u{session.user_id}-{uuid4().hex}.mp4"
        final_path = directory / final_name
        os.replace(tmp_path, final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    export = ClipExport(
        user_id=session.user_id,
        session_id=session.id,
        title=title.strip(),
        file_name=final_name,
        mime="video/mp4",
        size_bytes=total,
        duration_ms=duration_ms,
        status="available",
        client_export_id=client_export_id,
        created_at=shanghai_now(),
    )
    from sqlalchemy import update as _update

    try:
        db.add(export)
        # 条件置位：若清理线程恰好把会话标为 expired，这里不得「复活」它
        db.execute(
            _update(ClipSession)
            .where(ClipSession.id == session.id, ClipSession.status.in_(("exchanged", "completed")))
            .values(status="completed")
        )
        db.commit()
        db.refresh(export)
    except IntegrityError:
        db.rollback()
        final_path.unlink(missing_ok=True)
        existing = db.scalar(
            select(ClipExport).where(
                ClipExport.session_id == session.id,
                ClipExport.client_export_id == client_export_id,
            )
        )
        if existing is None:
            raise
        return existing, False
    return export, True


def delete_clip_export(db: Session, user_id: int, export_id: int) -> None:
    export = db.get(ClipExport, export_id)
    if export is None or export.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成片不存在")
    if export.linked_draft_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="成片已关联草稿，请先解除草稿引用")
    path = media_dir() / export.file_name
    # 条件删除防「DELETE ∥ 转草稿」竞态：转草稿先持锁置 linked_draft_id 后，
    # 这里的无条件删除会绕过「已关联草稿不可删」保护
    from sqlalchemy import delete as _delete

    result = db.execute(
        _delete(ClipExport).where(
            ClipExport.id == export_id, ClipExport.linked_draft_id.is_(None)
        )
    )
    db.commit()
    if result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="成片状态已变化，请刷新后重试")
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # 文件被下载流占用等场景：记录但不 500（行已删）。
        # 注意 xhs-clip- 前缀不参与自动清理，孤儿文件需人工清理或后续
        # 为无行引用的成片文件增加专项回收。
        import logging

        logging.getLogger(__name__).warning(
            "成片文件删除失败（成为孤儿文件）: %s", export.file_name, exc_info=True
        )


def create_draft_from_clip_export(
    db: Session, user_id: int, export_id: int
) -> tuple["AiDraft", bool]:
    """把成片送入小红书草稿（幂等：一份成片最多关联一个草稿）。"""
    from backend.app.models import AiDraft, DraftAsset

    export = db.get(ClipExport, export_id)
    if export is None or export.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成片不存在")

    if export.linked_draft_id:
        existing = db.get(AiDraft, export.linked_draft_id)
        if existing is not None:
            return existing, False
        # 草稿被外部删除：解除引用，允许重新创建
        export.linked_draft_id = None
        export.status = "available"

    from sqlalchemy import update as _update

    draft = AiDraft(user_id=user_id, platform="xhs", title=export.title, body="")
    db.add(draft)
    db.flush()
    db.add(
        DraftAsset(
            draft_id=draft.id,
            asset_type="video",
            local_path=export.file_name,
            sort_order=0,
        )
    )
    # 条件更新防并发双草稿：只有第一个能把 linked_draft_id 从 NULL 置位
    claimed = db.execute(
        _update(ClipExport)
        .where(ClipExport.id == export.id, ClipExport.linked_draft_id.is_(None))
        .values(linked_draft_id=draft.id, status="linked")
    )
    claimed_count = claimed.rowcount
    if claimed_count != 1:
        # 并发败者：必须先回滚本事务内未决的 AiDraft/DraftAsset INSERT，
        # 否则 commit 会把孤儿草稿落库（review 第 5 轮 P2）
        db.rollback()
        current = db.get(ClipExport, export.id)
        if current is not None and current.linked_draft_id:
            existing = db.get(AiDraft, current.linked_draft_id)
            if existing is not None:
                return existing, False
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="成片状态已变化，请刷新后重试")
    db.commit()
    db.commit()
    db.refresh(draft)
    return draft, True
