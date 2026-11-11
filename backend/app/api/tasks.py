from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.publish import get_creator_publish_adapter_factory
from backend.app.core.config import get_settings
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Task, User
from backend.app.schemas.common import paginate_query, paginated
from backend.app.services.scheduler_service import run_due_publish_jobs

router = APIRouter(prefix="/tasks", tags=["tasks"])


def serialize_task(task: Task) -> dict:
    duration_ms = None
    if task.started_at and task.finished_at:
        duration_ms = int((task.finished_at - task.started_at).total_seconds() * 1000)
    return {
        "id": task.id,
        "platform": task.platform,
        "task_type": task.task_type,
        "status": task.status,
        "progress": task.progress,
        "payload": task.payload or {},
        "created_at": task.created_at.isoformat(),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_ms": duration_ms,
        "error_type": task.error_type,
        "retry_count": task.retry_count,
        "max_retries": task.max_retries,
        "parent_task_id": task.parent_task_id,
    }


def _get_owned_task(db: Session, current_user: User, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _is_scheduler_task(task: Task) -> bool:
    if task.task_type == "creator_publish_scheduler":
        return True
    if task.task_type == "monitoring_refresh":
        return bool((task.payload or {}).get("scheduler"))
    return False


# 纯审计任务类型：只是运行记录，没有可重新入队的消费者（BE-7）
AUDIT_ONLY_TASK_TYPES = {
    "monitoring_refresh",
    "monitoring_crawl",
    "auto_ops_run",
    "creator_publish_retry",
    "creator_publish_cancel",
    "crawl_search",
    "crawl_note_urls",
    "crawl_user_notes",
    "crawl_comments",
    "data_search",
    "data_note_urls",
    "data_user_notes",
    "data_comments",
}


def _linked_publish_job_id(task: Task) -> Optional[int]:
    payload = task.payload or {}
    job_id = payload.get("publish_job_id")
    return int(job_id) if isinstance(job_id, (int, str)) and str(job_id).isdigit() else None


@router.get("")
def get_tasks(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = select(Task).where(Task.user_id == current_user.id)
    if platform:
        statement = statement.where(Task.platform == platform)
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        statement,
        page=page,
        page_size=page_size,
        serializer=serialize_task,
        order_by=(Task.created_at.desc(), Task.id.desc()),
    )


@router.post("/run-due")
def run_due_tasks(
    platform: str = Query("xhs"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    return run_due_publish_jobs(
        db=db,
        current_user=current_user,
        now=None,
        platform=platform,
        adapter_factory=adapter_factory,
    )


@router.get("/scheduler/status")
def scheduler_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    scheduler = getattr(request.app.state, "scheduler", None)
    jobs = []
    if scheduler is not None:
        jobs = [
            {
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            }
            for job in scheduler.get_jobs()
        ]
    scheduler_task_candidates = db.scalars(
        select(Task)
        .where(
            Task.user_id == current_user.id,
            Task.task_type.in_(("creator_publish_scheduler", "monitoring_refresh")),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
        .limit(50)
    ).all()
    recent_tasks = [task for task in scheduler_task_candidates if _is_scheduler_task(task)][:10]
    return {
        "enabled": settings.scheduler_enabled,
        "running": bool(scheduler is not None and scheduler.running),
        "interval_seconds": settings.scheduler_interval_seconds,
        "jobs": jobs,
        "recent_tasks": [serialize_task(task) for task in recent_tasks],
    }


@router.get("/{task_id}")
def get_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_owned_task(db, current_user, task_id)
    result = serialize_task(task)
    children = db.scalars(
        select(Task)
        .where(Task.parent_task_id == task.id, Task.user_id == current_user.id)
        .order_by(Task.created_at.asc())
    ).all()
    result["children"] = [serialize_task(c) for c in children]
    return result


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_owned_task(db, current_user, task_id)
    if task.task_type in AUDIT_ONLY_TASK_TYPES:
        # BE-7：审计任务没有可取消的执行体——改状态只会造成"已取消"的假象
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该任务仅为执行记录，无法取消；如需停止发布，请到发布中心取消对应的发布任务",
        )
    if task.status in {"pending", "running"}:
        task.status = "cancelled"
        # 取消标记：执行器在每次外部调用前检查（协作式取消）
        task.payload = {**(task.payload or {}), "cancel_requested": True}
        # review P2-3：取消发布任务时联动取消关联的 PublishJob，
        # 否则 scheduled 任务到期仍会被调度器执行
        job_id = _linked_publish_job_id(task)
        if job_id is not None:
            from backend.app.models import PublishJob

            job = db.get(PublishJob, job_id)
            if job is not None and job.user_id == current_user.id and job.status == "pending":
                job.status = "cancelled"
        db.commit()
        db.refresh(task)
    return serialize_task(task)


@router.post("/{task_id}/retry")
def retry_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from backend.app.models import PublishJob

    task = _get_owned_task(db, current_user, task_id)
    if task.task_type in AUDIT_ONLY_TASK_TYPES:
        # BE-7：审计任务改回 pending 没有任何消费者处理，只会误导用户
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该任务仅为执行记录，无法重试；如需重新发布，请到发布中心重试对应的发布任务",
        )
    if task.status in {"failed", "exhausted"}:
        job_id = _linked_publish_job_id(task)
        if job_id is not None:
            job = db.get(PublishJob, job_id)
            if job is not None and job.user_id == current_user.id and job.status == "failed":
                # 真正的重新入队：关联发布任务回到 pending，由调度器/手动发布执行
                job.status = "pending"
                job.publish_error = ""
        task.status = "pending"
        task.progress = 0
        task.retry_count = task.retry_count + 1
        task.error_type = None
        task.started_at = None
        task.finished_at = None
        db.commit()
        db.refresh(task)
    return serialize_task(task)
