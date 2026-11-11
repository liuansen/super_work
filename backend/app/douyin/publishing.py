"""发布任务服务：幂等创建、显式执行、取消、状态对账。

状态机：pending → (cancelled | running → succeeded | failed | unknown)。
- 执行领取用条件更新（pending→running）并先提交，再发起平台请求；
- 网络类异常一律记 unknown（结果不明），绝不自动重发；
- 未到计划时间的定时任务仍可由用户显式执行：计划时间以 timing 参数
  交给平台侧定时（上游 create_v2 原生支持）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.database import SessionLocal
from backend.app.core.time import shanghai_now
from backend.app.douyin import accounts as accounts_service
from backend.app.douyin.contracts import (
    DouyinAdapter,
    DouyinAuthError,
    DouyinNetworkError,
)
from backend.app.douyin.models import DouyinAccount, DouyinPublishTask

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_CANCELLED = "cancelled"

VALID_VISIBILITY = (0, 1, 2)  # 0 公开 / 1 仅自己 / 2 好友可见（与上游 create_v2 枚举一致）

VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


class PublishConflict(Exception):
    """幂等冲突或状态竞争。"""


def _media_dir_name() -> str:
    from backend.app.api.files import _media_dir  # 局部导入避免环

    return str(_media_dir())


def resolve_media_paths(user_id: int, media_names: list[str]) -> list[str]:
    """把前端上传的 file_name 解析为媒体目录内的绝对路径。

    只接受本用户上传前缀（xhs-upload-u{uid}- / xhs-image-u{uid}-），
    拒绝路径分隔符与越界，杜绝目录穿越。
    """
    from pathlib import Path

    allowed = (f"xhs-upload-u{user_id}-", f"xhs-image-u{user_id}-")
    media_root = Path(_media_dir_name()).resolve()
    resolved: list[str] = []
    for name in media_names:
        if Path(name).name != name or ".." in name or "/" in name or "\\" in name:
            raise LookupError(f"非法媒体文件名: {name}")
        if not name.startswith(allowed):
            raise LookupError(f"媒体文件不属于当前用户: {name}")
        path = (media_root / name).resolve()
        if not path.is_relative_to(media_root) or not path.is_file():
            raise LookupError(f"媒体文件不存在: {name}")
        resolved.append(str(path))
    return resolved


def _payload_digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_scheduled_at(value: Optional[str]) -> Optional[datetime]:
    """前端提交带偏移的 ISO 时间 → 存储规范（无时区北京时间，与 shanghai_now 一致）。"""
    if value is None or not str(value).strip():
        return None
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("scheduled_at 必须携带时区偏移（北京时间）")
    offset = parsed.utcoffset()
    beijing = parsed.replace(tzinfo=None) - offset  # 转为 UTC naive
    from datetime import timedelta

    beijing = beijing + timedelta(hours=8)  # 再转北京时间 naive
    return beijing


def serialize_task(task: DouyinPublishTask) -> dict:
    return {
        "id": task.id,
        "account_id": task.account_id,
        "kind": task.kind,
        "media_names": json.loads(task.media_names_json or "[]"),
        "title": task.title,
        "description": task.description,
        "visibility": task.visibility,
        "allow_download": task.allow_download,
        "scheduled_at": task.scheduled_at.isoformat() if task.scheduled_at else None,
        "status": task.status,
        "provider_work_id": task.provider_work_id,
        "error_message": task.error_message,
        "result": json.loads(task.result_json or "{}"),
        "dispatched_at": task.dispatched_at.isoformat() if task.dispatched_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def get_owned_task(db: Session, user_id: int, task_id: int) -> Optional[DouyinPublishTask]:
    return db.scalar(
        select(DouyinPublishTask).where(
            DouyinPublishTask.id == task_id, DouyinPublishTask.user_id == user_id
        )
    )


def list_tasks(db: Session, user_id: int, limit: int = 200) -> list[DouyinPublishTask]:
    # review P2：此前无上限，任务表增长后响应无界
    return list(
        db.scalars(
            select(DouyinPublishTask)
            .where(DouyinPublishTask.user_id == user_id)
            .order_by(DouyinPublishTask.id.desc())
            .limit(limit)
        )
    )


def create_task(
    db: Session, user_id: int, *, account: DouyinAccount, kind: str,
    media_names: list[str], title: str, description: str, visibility: int,
    allow_download: bool, scheduled_at_iso: Optional[str], idempotency_key: str,
) -> tuple[DouyinPublishTask, bool]:
    """创建发布意图。返回 (task, created)；幂等键相同且载荷相同返回原任务。

    注意：创建≠发布。真正发送需要用户对具体任务显式调用执行接口。
    """
    if kind not in ("video", "images"):
        raise ValueError("kind 必须是 video 或 images")
    if visibility not in VALID_VISIBILITY:
        raise ValueError("visibility 必须是 0/1/2")
    if kind == "video" and len(media_names) != 1:
        raise ValueError("视频发布只能有一个视频文件")
    if kind == "images" and not media_names:
        raise ValueError("图集发布至少一张图片")
    for name in media_names:
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if kind == "video" and ext not in VIDEO_EXTS:
            raise ValueError("视频发布需要 mp4/mov/avi/mkv 文件" if ext == "" else f"视频发布不接受 {ext} 文件")
        if kind == "images" and ext not in IMAGE_EXTS:
            raise ValueError("图集发布需要 jpg/jpeg/png/webp 图片" if ext == "" else f"图集发布不接受 {ext} 文件")
    try:
        resolve_media_paths(user_id, media_names)
    except LookupError:
        raise
    scheduled_at = parse_scheduled_at(scheduled_at_iso)

    digest = _payload_digest(
        {
            "account_id": account.id, "kind": kind, "media_names": media_names,
            "title": title, "description": description, "visibility": visibility,
            "allow_download": allow_download,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        }
    )
    existing = db.scalar(
        select(DouyinPublishTask).where(
            DouyinPublishTask.user_id == user_id,
            DouyinPublishTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        _verify_idempotent_payload(existing, digest)
        return existing, False

    task = DouyinPublishTask(
        user_id=user_id,
        account_id=account.id,
        kind=kind,
        media_names_json=json.dumps(media_names, ensure_ascii=False),
        title=title,
        description=description,
        visibility=visibility,
        allow_download=allow_download,
        scheduled_at=scheduled_at,
        status=STATUS_PENDING,
        idempotency_key=idempotency_key,
    )
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        # 相同幂等键的并发请求：先查后插双方都没查到，后提交者撞唯一约束。
        # 回滚后按幂等语义返回已存在的任务，而不是 500。
        db.rollback()
        existing = db.scalar(
            select(DouyinPublishTask).where(
                DouyinPublishTask.user_id == user_id,
                DouyinPublishTask.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        _verify_idempotent_payload(existing, digest)
        return existing, False
    db.refresh(task)
    return task, True


def _verify_idempotent_payload(existing: DouyinPublishTask, digest: str) -> None:
    existing_digest = _payload_digest(
        {
            "account_id": existing.account_id, "kind": existing.kind,
            # 不排序：媒体顺序（图集页序）是载荷语义的一部分，重排即异载荷。
            "media_names": json.loads(existing.media_names_json or "[]"),
            "title": existing.title, "description": existing.description,
            "visibility": existing.visibility, "allow_download": existing.allow_download,
            "scheduled_at": existing.scheduled_at.isoformat() if existing.scheduled_at else None,
        }
    )
    if existing_digest != digest:
        raise PublishConflict("相同幂等键但载荷不同")


def _timing_seconds(task: DouyinPublishTask) -> Optional[int]:
    if task.scheduled_at is None:
        return None
    # scheduled_at 为无时区北京时间；平台 timing 为秒级时间戳。
    from datetime import timezone, timedelta

    beijing = timezone(timedelta(hours=8))
    return int(task.scheduled_at.replace(tzinfo=beijing).timestamp())


def execute_task(
    db: Session, user_id: int, task_id: int, adapter: DouyinAdapter
) -> DouyinPublishTask:
    """领取并执行一个发布任务。只有 pending 可执行；结果落库后返回最新状态。"""
    claimed = db.execute(
        update(DouyinPublishTask)
        .where(
            DouyinPublishTask.id == task_id,
            DouyinPublishTask.user_id == user_id,
            DouyinPublishTask.status == STATUS_PENDING,
        )
        .values(status=STATUS_RUNNING, dispatched_at=shanghai_now())
    )
    if claimed.rowcount != 1:
        existing = get_owned_task(db, user_id, task_id)
        if existing is None:
            raise LookupError("task not found")
        raise PublishConflict(
            f"任务当前状态为 {existing.status}，无法执行（只有 pending 可执行）"
        )
    db.commit()  # 先落“已领取”，再发起任何平台请求

    task = get_owned_task(db, user_id, task_id)
    account = db.get(DouyinAccount, task.account_id)
    if account is None or account.user_id != user_id:
        task.status = STATUS_FAILED
        task.error_message = "发布账号不存在或无权访问"
        db.commit()
        db.refresh(task)
        return task

    try:
        # 本地准备（解密凭证、解析媒体、计算定时）：任何失败都可确定为“未发送”。
        cookie = accounts_service.account_cookie(account)
        media_paths = resolve_media_paths(user_id, json.loads(task.media_names_json or "[]"))
        timing = _timing_seconds(task)
    except Exception as error:
        task.status = STATUS_FAILED
        task.error_message = f"本地准备失败，未发送：{error}"
        db.commit()
        db.refresh(task)
        return task

    try:
        if task.kind == "video":
            outcome = adapter.publish_video(
                cookie, media_paths[0], title=task.title, desc=task.description,
                visibility=task.visibility, allow_download=task.allow_download,
                timing=timing,
            )
        else:
            outcome = adapter.publish_images(
                cookie, media_paths, title=task.title, desc=task.description,
                visibility=task.visibility, allow_download=task.allow_download,
                timing=timing,
            )
    except DouyinAuthError as error:
        task.status = STATUS_FAILED
        task.error_message = f"凭证失效，未发送或需重新授权：{error}"
    except LookupError as error:
        task.status = STATUS_FAILED
        task.error_message = f"媒体文件不可用，未发送：{error}"
    except DouyinNetworkError as error:
        task.status = STATUS_UNKNOWN
        task.error_message = f"网络异常，结果不明，禁止自动重发：{error}"
    except Exception as error:  # 上游执行中途异常无法判断进度 → 结果不明
        task.status = STATUS_UNKNOWN
        task.error_message = f"执行中断，结果不明，禁止自动重发：{error}"
    else:
        if outcome.ok:
            task.status = STATUS_SUCCEEDED
            task.provider_work_id = outcome.provider_work_id
            task.result_json = json.dumps(outcome.result_raw, ensure_ascii=False, default=str)
        else:
            task.status = STATUS_FAILED
            task.error_message = outcome.message or "平台拒绝发布"
            task.result_json = json.dumps(outcome.result_raw, ensure_ascii=False, default=str)
    db.commit()
    db.refresh(task)
    return task


def cancel_task(db: Session, user_id: int, task_id: int) -> DouyinPublishTask:
    """取消任务。只有 pending 能取消；已发送边界的状态如实返回。"""
    cancelled = db.execute(
        update(DouyinPublishTask)
        .where(
            DouyinPublishTask.id == task_id,
            DouyinPublishTask.user_id == user_id,
            DouyinPublishTask.status == STATUS_PENDING,
        )
        .values(status=STATUS_CANCELLED, error_message="用户取消（未发送）")
    )
    if cancelled.rowcount == 1:
        db.commit()
        task = get_owned_task(db, user_id, task_id)
        return task
    db.rollback()
    task = get_owned_task(db, user_id, task_id)
    if task is None:
        raise LookupError("task not found")
    raise PublishConflict(
        f"任务状态为 {task.status}，无法取消"
        + ("（已越过发送边界，平台侧定时/发布不能保证已阻止）" if task.status in (STATUS_RUNNING, STATUS_UNKNOWN, STATUS_SUCCEEDED) else "")
    )


STALE_RUNNING_TIMEOUT_MINUTES = 30


def reconcile_stale_tasks(*, db: Optional[Session] = None, max_age_minutes: int = STALE_RUNNING_TIMEOUT_MINUTES) -> int:
    """启动对账：把进程崩溃/重启后滞留在 running 的任务复位为 unknown。

    只复位超过超时阈值的任务，避免误伤其他 worker 正在执行中的任务；
    结果标记为 unknown（结果不明），与状态机语义一致，绝不自动重发。
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        cutoff = shanghai_now() - timedelta(minutes=max_age_minutes)
        stale = session.execute(
            update(DouyinPublishTask)
            .where(
                DouyinPublishTask.status == STATUS_RUNNING,
                or_(
                    DouyinPublishTask.dispatched_at.is_(None),
                    DouyinPublishTask.dispatched_at <= cutoff,
                ),
            )
            .values(
                status=STATUS_UNKNOWN,
                error_message="执行进程中断，结果不明（启动对账）",
            )
        )
        session.commit()
        if stale.rowcount:
            import logging

            logging.getLogger(__name__).warning(
                f"启动对账：复位 {stale.rowcount} 个滞留在 running 的抖音发布任务为 unknown"
            )
        return stale.rowcount
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()
