from __future__ import annotations

import logging
import random
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.services.xhs_normalizers import (
    data_items as _data_items,
    normalize_search_item as _normalize_search_item,
)
from backend.app.api.publish import get_creator_publish_adapter_factory
from backend.app.api.platforms.xhs.pc import (
    _get_owned_pc_account_cookies,
    get_xhs_pc_api_adapter_factory,
)
from backend.app.core.database import get_db
from backend.app.core.deps import app_access_required, get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import (
    AccountCookieVersion,
    AiDraft,
    AutoTask,
    ModelConfig,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    Task,
    User,
)
from backend.app.schemas.common import paginate_query, paginated
from backend.app.services.ai_service import OpenAICompatibleTextClient

router = APIRouter(
    prefix="/auto-tasks",
    tags=["auto-tasks"],
    dependencies=[Depends(app_access_required("xhs"))],
)

# review P1：schedule_time 之前只校验长度，写进 "abcde" 会让 _calculate_next_run_at
# 抛 ValueError；调度器吞掉异常后 next_run_at 滞留在过去，于是每分钟重复发布一次。
_SCHEDULE_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _normalize_schedule_time(value: str) -> str:
    text = (value or "").strip()
    if not _SCHEDULE_TIME_RE.match(text):
        raise ValueError("schedule_time 必须为 HH:MM（24 小时制，例如 09:30）")
    return text


def _parse_schedule_time(value: str | None) -> tuple[int, int] | None:
    """解析 HH:MM；非法值返回 None（调用方据此停止排期，不再让异常逃逸）。"""
    match = _SCHEDULE_TIME_RE.match((value or "").strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


class AutoTaskCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    keywords: list[str] = Field(min_length=1)
    pc_account_id: int
    creator_account_id: int
    ai_instruction: str = Field(default="", max_length=2000)
    schedule_type: str = Field(default="manual", pattern="^(manual|daily|weekly|interval)$")
    schedule_time: str = Field(default="09:00", max_length=5)
    schedule_days: str = Field(default="", max_length=64)
    schedule_interval_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("schedule_time")
    @classmethod
    def _validate_schedule_time(cls, value: str) -> str:
        return _normalize_schedule_time(value)


class AutoTaskUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    keywords: Optional[list[str]] = None
    ai_instruction: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[str] = Field(default=None, pattern="^(active|paused|completed)$")
    schedule_type: Optional[str] = Field(default=None, pattern="^(manual|daily|weekly|interval)$")
    schedule_time: Optional[str] = Field(default=None, max_length=5)
    schedule_days: Optional[str] = Field(default=None, max_length=64)
    schedule_interval_hours: Optional[int] = Field(default=None, ge=1, le=168)

    @field_validator("schedule_time")
    @classmethod
    def _validate_schedule_time(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _normalize_schedule_time(value)


def _serialize_auto_task(task: AutoTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "user_id": task.user_id,
        "name": task.name,
        "keywords": task.keywords or [],
        "pc_account_id": task.pc_account_id,
        "creator_account_id": task.creator_account_id,
        "ai_instruction": task.ai_instruction,
        "status": task.status,
        "schedule_type": task.schedule_type,
        "schedule_time": task.schedule_time,
        "schedule_days": task.schedule_days,
        "schedule_interval_hours": task.schedule_interval_hours,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "total_published": task.total_published,
        "created_at": task.created_at.isoformat(),
    }


def _get_owned_auto_task(db: Session, current_user: User, task_id: int) -> AutoTask:
    auto_task = db.scalars(
        select(AutoTask).where(AutoTask.id == task_id, AutoTask.user_id == current_user.id)
    ).first()
    if auto_task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auto task not found")
    return auto_task


def _verify_account_ownership(db: Session, current_user: User, account_id: int, expected_sub_type: str) -> PlatformAccount:
    account = db.get(PlatformAccount, account_id)
    if (
        account is None
        or account.user_id != current_user.id
        or account.platform != "xhs"
        or account.sub_type != expected_sub_type
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"XHS {expected_sub_type} account not found",
        )
    return account


def _get_account_cookies(db: Session, account_id: int) -> str:
    from backend.app.api.publish import _cookies_to_string

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account_id)
        .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc())
    ).first()
    if cookie_version is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account has no cookies")
    return _cookies_to_string(decrypt_text(cookie_version.encrypted_cookies))


def _calculate_next_run_at(task: AutoTask) -> None:
    from datetime import timedelta
    now = shanghai_now()
    if task.schedule_type == "manual":
        task.next_run_at = None
    elif task.schedule_type in ("daily", "weekly"):
        parsed = _parse_schedule_time(task.schedule_time)
        if parsed is None:
            # 历史脏数据兜底：宁可停排，也不能让 next_run_at 滞留在过去导致每分钟发布
            logger.warning(
                "auto task %s 的 schedule_time 非法(%r)，已停止排期",
                task.id,
                task.schedule_time,
            )
            task.next_run_at = None
            return
        h, m = parsed
        if task.schedule_type == "daily":
            next_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if next_time <= now:
                next_time += timedelta(days=1)
            task.next_run_at = next_time
            return
        days = [int(d) for d in (task.schedule_days or "").split(",") if d.strip().isdigit()]
        if not days:
            task.next_run_at = None
            return
        # SCH-6：从 offset=0 开始——配置为"今天"时，当天目标时刻尚未过去就应排到今天执行
        for offset in range(0, 8):
            candidate = now + timedelta(days=offset)
            if candidate.isoweekday() in days:
                candidate_time = candidate.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate_time > now:
                    task.next_run_at = candidate_time
                    return
        task.next_run_at = None
    elif task.schedule_type == "interval":
        task.next_run_at = now + timedelta(hours=task.schedule_interval_hours)
    else:
        # 未知 schedule_type（DB 直改脏数据）与 schedule_time 脏数据同语义：
        # 停止排期，绝不能让 next_run_at 滞留在过去导致每个 tick 重复执行
        logger.warning(
            "auto task %s 的 schedule_type 未知(%r)，已停止排期",
            task.id,
            task.schedule_type,
        )
        task.next_run_at = None


@router.get("")
def list_auto_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        select(AutoTask).where(AutoTask.user_id == current_user.id),
        page=page,
        page_size=page_size,
        serializer=_serialize_auto_task,
        order_by=(AutoTask.created_at.desc(), AutoTask.id.desc()),
    )


@router.post("")
def create_auto_task(
    payload: AutoTaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _verify_account_ownership(db, current_user, payload.pc_account_id, "pc")
    _verify_account_ownership(db, current_user, payload.creator_account_id, "creator")

    auto_task = AutoTask(
        user_id=current_user.id,
        name=payload.name,
        keywords=payload.keywords,
        pc_account_id=payload.pc_account_id,
        creator_account_id=payload.creator_account_id,
        ai_instruction=payload.ai_instruction,
        schedule_type=payload.schedule_type,
        schedule_time=payload.schedule_time,
        schedule_days=payload.schedule_days,
        schedule_interval_hours=payload.schedule_interval_hours,
        status="active",
    )
    _calculate_next_run_at(auto_task)
    db.add(auto_task)
    db.commit()
    db.refresh(auto_task)
    return _serialize_auto_task(auto_task)


@router.patch("/{task_id}")
def update_auto_task(
    task_id: int,
    payload: AutoTaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auto_task = _get_owned_auto_task(db, current_user, task_id)

    if payload.name is not None:
        auto_task.name = payload.name
    if payload.keywords is not None:
        auto_task.keywords = payload.keywords
    if payload.ai_instruction is not None:
        auto_task.ai_instruction = payload.ai_instruction
    if payload.status is not None:
        auto_task.status = payload.status

    schedule_changed = False
    if payload.schedule_type is not None:
        auto_task.schedule_type = payload.schedule_type
        schedule_changed = True
    if payload.schedule_time is not None:
        auto_task.schedule_time = payload.schedule_time
        schedule_changed = True
    if payload.schedule_days is not None:
        auto_task.schedule_days = payload.schedule_days
        schedule_changed = True
    if payload.schedule_interval_hours is not None:
        auto_task.schedule_interval_hours = payload.schedule_interval_hours
        schedule_changed = True
    if schedule_changed:
        _calculate_next_run_at(auto_task)

    db.commit()
    db.refresh(auto_task)
    return _serialize_auto_task(auto_task)


@router.delete("/{task_id}")
def delete_auto_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auto_task = _get_owned_auto_task(db, current_user, task_id)
    db.delete(auto_task)
    db.commit()
    return {"id": task_id, "status": "deleted"}


@router.post("/{task_id}/run")
def run_auto_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_xhs_pc_api_adapter_factory),
    publish_adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    """手动运行一次自动运营任务（= 搜索 → 改写 → 发布）。

    执行体在后台线程池中跑（见 services/job_runner.py）：
    - 阈值内完成：直接返回完整结果（保持原有前端契约）；
    - 超过 TASK_SYNC_WAIT_SECONDS：返回 202 + 任务 ID，前端到任务中心查看。
    这样上游变慢时不会挂死请求线程、拖垮整站。
    """
    auto_task = _get_owned_auto_task(db, current_user, task_id)

    # 轻量校验留在请求线程：账号不存在等错误应立即 404，而不是排进队列
    _verify_account_ownership(db, current_user, auto_task.pc_account_id, "pc")
    _verify_account_ownership(db, current_user, auto_task.creator_account_id, "creator")

    # 先落一条运行记录：超时返回 202 时前端据此轮询
    tracking_task = Task(
        user_id=current_user.id,
        platform="xhs",
        task_type="auto_ops_run",
        status="running",
        progress=5,
        payload={"auto_task_id": auto_task.id, "auto_task_name": auto_task.name},
    )
    db.add(tracking_task)
    db.commit()
    db.refresh(tracking_task)

    from concurrent.futures import TimeoutError as FutureTimeout

    from backend.app.services import job_runner

    future = job_runner.submit(
        _execute_auto_ops_run,
        auto_task_id=auto_task.id,
        user_id=current_user.id,
        bind=db.get_bind(),
        tracking_task_id=tracking_task.id,
        adapter_factory=adapter_factory,
        publish_adapter_factory=publish_adapter_factory,
    )
    try:
        return future.result(timeout=job_runner.sync_wait_seconds())
    except FutureTimeout:
        logger.info(
            "auto task %s 手动运行超过同步阈值，转后台（tracking_task=%s）",
            auto_task.id,
            tracking_task.id,
        )
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail={
                "status": "accepted",
                "task_id": tracking_task.id,
                "message": "任务已转入后台执行，请在任务中心查看进度",
            },
        )


def _execute_auto_ops_run(
    *,
    auto_task_id: int,
    user_id: int,
    bind,
    tracking_task_id: int,
    adapter_factory,
    publish_adapter_factory,
) -> dict:
    """后台执行体：自带 session（不可复用请求线程的 Session）。"""
    from sqlalchemy.orm import Session as _Session

    db = _Session(bind=bind)
    try:
        auto_task = db.get(AutoTask, auto_task_id)
        current_user = db.get(User, user_id)
        tracking_task = db.get(Task, tracking_task_id)
        if auto_task is None or current_user is None or tracking_task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Auto task not found",
            )
        tracking_task.progress = 10
        db.commit()
        try:
            return _run_auto_ops_pipeline(
                db,
                auto_task=auto_task,
                current_user=current_user,
                tracking_task=tracking_task,
                adapter_factory=adapter_factory,
                publish_adapter_factory=publish_adapter_factory,
            )
        except HTTPException as exc:
            _mark_run_failed(db, tracking_task, str(exc.detail))
            raise
        except Exception as exc:
            _mark_run_failed(db, tracking_task, str(exc)[:500])
            raise
    finally:
        db.close()


def _mark_run_failed(db: Session, tracking_task: Task, message: str) -> None:
    try:
        db.rollback()
        task = db.get(Task, tracking_task.id)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            task.payload = {**(task.payload or {}), "error": message[:500]}
            db.commit()
    except Exception:
        db.rollback()
        logger.warning("标记运行记录失败: task=%s", tracking_task.id, exc_info=True)


def _run_auto_ops_pipeline(
    db: Session,
    *,
    auto_task: AutoTask,
    current_user: User,
    tracking_task: Task,
    adapter_factory,
    publish_adapter_factory,
) -> dict:
    """搜索 → 选优 → AI 改写 → 建发布任务 → 立即发布（原 run_auto_task 主体）。"""
    # 1. Pick a random keyword    # 1. Pick a random keyword
    keywords = auto_task.keywords or []
    if not keywords:
        tracking_task.status = "failed"
        tracking_task.progress = 100
        tracking_task.payload = {**(tracking_task.payload or {}), "error": "No keywords configured"}
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No keywords configured")

    keyword = random.choice(keywords)
    tracking_task.payload = {**(tracking_task.payload or {}), "keyword": keyword}
    db.flush()

    # 2. Search notes using PC adapter
    pc_cookies = _get_owned_pc_account_cookies(db, current_user, auto_task.pc_account_id)
    adapter = adapter_factory(pc_cookies)
    success, message, raw_payload = adapter.search_note(keyword, page=1)
    if not success:
        tracking_task.status = "failed"
        tracking_task.progress = 100
        tracking_task.payload = {**(tracking_task.payload or {}), "error": message or "Search failed"}
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=message or "XHS search failed")

    tracking_task.progress = 30
    db.flush()

    # 3. Normalize and pick top-engagement note
    items = _data_items(raw_payload)
    normalized_items = [_normalize_search_item(item) for item in items]
    if not normalized_items:
        tracking_task.status = "failed"
        tracking_task.progress = 100
        tracking_task.payload = {**(tracking_task.payload or {}), "error": "No notes found for keyword"}
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No notes found for keyword")

    # Limit to crawl_count and pick best by engagement
    candidates = normalized_items[:10]
    best_note = max(
        candidates,
        key=lambda n: (n.get("likes", 0) + n.get("collects", 0) + n.get("comments", 0) + n.get("shares", 0)),
    )

    tracking_task.progress = 50
    tracking_task.payload = {
        **(tracking_task.payload or {}),
        "source_note_id": best_note.get("note_id"),
        "source_title": best_note.get("title"),
        "candidates_count": len(candidates),
    }
    db.flush()

    # 4. Create an AiDraft from the best note
    draft = AiDraft(
        user_id=current_user.id,
        platform="xhs",
        title=str(best_note.get("title") or ""),
        body=str(best_note.get("content") or ""),
    )
    db.add(draft)
    db.flush()

    tracking_task.progress = 60
    tracking_task.payload = {**(tracking_task.payload or {}), "draft_id": draft.id}
    db.flush()

    # 5. AI rewrite using the task's instruction
    model_config = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == current_user.id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if model_config is None:
        tracking_task.status = "failed"
        tracking_task.progress = 100
        tracking_task.payload = {**(tracking_task.payload or {}), "error": "Default text model not configured"}
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Default text model is not configured")

    api_key = decrypt_text(model_config.encrypted_api_key) if model_config.encrypted_api_key else ""
    text_client = OpenAICompatibleTextClient()

    try:
        rewritten_body = text_client.rewrite_note(
            model_config=model_config,
            api_key=api_key,
            title=draft.title,
            body=draft.body,
            instruction=auto_task.ai_instruction or "改写为原创小红书笔记，保持核心信息，提升表达和语感",
        )
        draft.body = rewritten_body
    except Exception as exc:
        tracking_task.status = "failed"
        tracking_task.progress = 100
        tracking_task.payload = {**(tracking_task.payload or {}), "error": f"AI rewrite failed: {exc}"}
        db.commit()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI rewrite failed: {exc}") from exc

    # 5b. Title rewrite (non-fatal)
    try:
        draft.title = text_client.rewrite_title(
            model_config=model_config,
            api_key=api_key,
            title=draft.title,
            body=draft.body,
            max_length=15,
        )
    except Exception as exc:
        logger.warning(f"Auto task {auto_task.id} title rewrite failed: {exc}")

    tracking_task.progress = 80
    db.flush()

    # 6. Create a PublishJob with the Creator account
    publish_job = PublishJob(
        user_id=current_user.id,
        platform_account_id=auto_task.creator_account_id,
        source_draft_id=draft.id,
        platform="xhs",
        title=draft.title,
        body=draft.body,
        publish_mode="immediate",
        status="pending",
    )
    db.add(publish_job)
    db.flush()

    # 6b. Copy image assets from source note
    image_urls = best_note.get("image_urls", [])
    if isinstance(image_urls, list):
        for url in image_urls[:9]:  # max 9 images
            if isinstance(url, str) and url:
                db.add(PublishAsset(
                    publish_job_id=publish_job.id,
                    asset_type="image",
                    file_path=url,
                    upload_status="pending",
                ))

    # 7. Update auto task run time.
    auto_task.last_run_at = shanghai_now()
    _calculate_next_run_at(auto_task)

    tracking_task.status = "completed"
    tracking_task.progress = 100
    tracking_task.payload = {
        **(tracking_task.payload or {}),
        "publish_job_id": publish_job.id,
        "rewritten_length": len(rewritten_body),
    }

    db.commit()
    db.refresh(auto_task)
    db.refresh(draft)
    db.refresh(publish_job)

    # SCH-5（W0-3 决策：手动"运行"= 真正发布）：与手动发布/调度器共用同一执行器。
    # 先原子领取，再执行；total_published 由执行器链路在发布成功后递增。
    # review P1-1：手动运行同样领取 auto_tasks.claimed_at，
    # 防止调度器 tick 与手动运行并发重复执行同一任务
    from backend.app.services.scheduler_service import _claim_auto_task, _release_auto_task_claim

    if not _claim_auto_task(db, auto_task.id):
        db.refresh(publish_job)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该自动运营任务正在被调度器执行，请稍后再试",
        )
    try:
        return _finish_manual_auto_task_run(
            db,
            auto_task=auto_task,
            current_user=current_user,
            publish_job=publish_job,
            keyword=keyword,
            best_note=best_note,
            draft=draft,
            adapter_factory=publish_adapter_factory,
        )
    finally:
        _release_auto_task_claim(db, auto_task.id)


def _finish_manual_auto_task_run(
    db: Session,
    *,
    auto_task: AutoTask,
    current_user: User,
    publish_job: PublishJob,
    keyword: str,
    best_note: dict,
    draft: AiDraft,
    adapter_factory=None,
) -> dict:
    """手动运行的发布执行段（调用方已完成 auto task 原子领取）。

    keyword / best_note / draft 由调用方显式传入：它们只存在于 run_auto_task
    的局部作用域，早期版本在这里直接引用会抛 NameError（且发布已经完成并提交，
    用户看到 500 后重试会造成重复发布）。
    """
    publish_status = publish_job.status
    publish_error = ""
    creator_account = db.get(PlatformAccount, auto_task.creator_account_id)
    if (
        creator_account is not None
        and creator_account.platform == "xhs"
        and creator_account.sub_type == "creator"
    ):
        from backend.app.api.publish import execute_claimed_publish_job
        from backend.app.models import PublishJob
        from backend.app.core.time import shanghai_now as _now

        claimed = db.execute(
            update(PublishJob)
            .where(
                PublishJob.id == publish_job.id,
                PublishJob.status.not_in(("publishing", "uploading", "published", "scheduled")),
            )
            .values(status="publishing", publish_started_at=_now())
        )
        db.commit()
        if claimed.rowcount == 1:
            db.refresh(publish_job)
            try:
                execute_claimed_publish_job(
                    db,
                    job=publish_job,
                    account=creator_account,
                    current_user=current_user,
                    adapter_factory=(adapter_factory or get_creator_publish_adapter_factory()),
                )
            except HTTPException as exc:
                publish_error = str(exc.detail)
            except Exception as exc:  # 网络等非 HTTP 异常也要反馈给用户
                publish_error = str(exc)[:300]
            db.refresh(publish_job)
            publish_status = publish_job.status
        else:
            publish_status = "conflict"
    else:
        # 账号不是 Creator：明确告知用户任务已排队但不会执行
        publish_error = "自动运营绑定的不是 Creator（专业号）账号，任务已创建但不会自动发布"
        publish_status = "pending"

    return {
        "auto_task": _serialize_auto_task(auto_task),
        "keyword": keyword,
        "source_note": {
            "note_id": best_note.get("note_id"),
            "title": best_note.get("title"),
            "likes": best_note.get("likes", 0),
            "collects": best_note.get("collects", 0),
            "comments": best_note.get("comments", 0),
        },
        "draft": {
            "id": draft.id,
            "title": draft.title,
            "body": draft.body,
            "created_at": draft.created_at.isoformat(),
        },
        "publish_job": {
            "id": publish_job.id,
            "status": publish_status,
            "publish_error": publish_error,
            "platform_account_id": publish_job.platform_account_id,
        },
    }
