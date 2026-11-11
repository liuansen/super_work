from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.core.media_storage import media_dir
from backend.app.core.time import shanghai_now
from backend.app.models import ClipExport, ClipSession


def mark_expired_clip_sessions(db: Session, now: Optional[datetime] = None) -> int:
    """把过期（握手超时或会话超时）的会话标记为 expired。

    用条件 UPDATE（WHERE 带状态谓词）而不是 load-modify-commit：
    清理线程的 SELECT 快照可能滞后，若用户恰在窗口内完成 exchange，
    旧值覆盖会把刚拿到的 12h 会话标成 expired（P2 竞态，review 第 3 轮）。
    """
    from sqlalchemy import update as _update

    current = now or shanghai_now()
    changed = 0
    result = db.execute(
        _update(ClipSession)
        .where(ClipSession.status == "issued", ClipSession.handoff_expires_at <= current)
        .values(status="expired")
    )
    changed += result.rowcount or 0
    # completed 也按会话有效期流转到 expired，否则无导出的
    # completed 会话会永久滞留 clip_sessions 表
    result = db.execute(
        _update(ClipSession)
        .where(
            ClipSession.status.in_(("exchanged", "completed")),
            ClipSession.session_expires_at <= current,
        )
        .values(status="expired")
    )
    changed += result.rowcount or 0
    db.commit()
    return changed


def prune_clip_sessions(
    db: Session, now: Optional[datetime] = None, retention_days: int = 7
) -> int:
    """删除过期超过保留期的会话；有成片关联的会话保留（成片引用 session）。"""
    cutoff = (now or shanghai_now()) - timedelta(days=retention_days)
    rows = db.scalars(
        select(ClipSession).where(
            ClipSession.status == "expired",
            ClipSession.handoff_expires_at < cutoff,
        )
    ).all()
    removed = 0
    for session in rows:
        exports = int(
            db.scalar(
                select(func.count())
                .select_from(ClipExport)
                .where(ClipExport.session_id == session.id)
            )
            or 0
        )
        if exports:
            continue
        db.delete(session)
        removed += 1
    if removed:
        db.commit()
    return removed


def prune_clip_temp_files(
    directory: Optional[Path] = None,
    now: Optional[float] = None,
    max_age_hours: int = 24,
) -> int:
    """清理上传中断遗留的 .clip-upload-*.part 临时文件。"""
    target = directory or media_dir()
    if not target.is_dir():
        return 0
    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed = 0
    for path in target.iterdir():
        if not path.is_file() or not path.name.startswith(".clip-upload-") or not path.name.endswith(".part"):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def run_clip_cleanup_once() -> dict[str, int]:
    db = SessionLocal()
    try:
        expired = mark_expired_clip_sessions(db)
        pruned = prune_clip_sessions(db)
        temp = prune_clip_temp_files()
        return {"expired": expired, "pruned": pruned, "temp_files": temp}
    finally:
        db.close()
