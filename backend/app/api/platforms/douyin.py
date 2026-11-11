"""抖音运营 API：账号 / 参考库 / 作品数据 / 发布任务。

所有接口都用现有认证依赖（get_current_user）；对非 owner 资源一律 404。
真实平台操作只发生在显式的执行/采集/刷新接口上。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.app.adapters.douyin import get_adapter
from backend.app.core.database import get_db
from backend.app.core.deps import app_access_required, get_current_user
from backend.app.douyin import accounts as accounts_service
from backend.app.douyin import metrics as metrics_service
from backend.app.douyin import publishing as publishing_service
from backend.app.douyin import references as references_service
from backend.app.douyin.contracts import (
    DouyinAdapter,
    DouyinAdapterError,
    DouyinAuthError,
    DouyinNetworkError,
    DouyinUpstreamError,
)
from backend.app.douyin.models import DouyinPublishTask, DouyinReferenceWork
from backend.app.models import User

router = APIRouter(
    prefix="/douyin",
    tags=["douyin"],
    dependencies=[Depends(app_access_required("douyin"))],
)


def adapter_dependency() -> DouyinAdapter:
    return get_adapter()


def _map_adapter_error(error: DouyinAdapterError) -> HTTPException:
    if isinstance(error, DouyinAuthError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    if isinstance(error, DouyinNetworkError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    if isinstance(error, DouyinUpstreamError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))


class AccountCreateRequest(BaseModel):
    cookie: str = Field(min_length=10)
    account_id: Optional[int] = None  # 提供则为重新授权


class CollectRequest(BaseModel):
    account_id: int
    url: str = Field(min_length=5)


class ReferenceUpdateRequest(BaseModel):
    tags: Optional[list[str]] = None
    note: Optional[str] = None


class WorkRefreshRequest(BaseModel):
    account_id: Optional[int] = None


class PublishTaskCreateRequest(BaseModel):
    account_id: int
    kind: str = Field(pattern="^(video|images)$")
    media_names: list[str] = Field(min_length=1)
    title: str = Field(default="", max_length=20)  # 上游 create_v2 契约：标题 ≤20 字
    description: str = Field(default="", max_length=2000)
    visibility: int = Field(default=1, ge=0, le=2)
    allow_download: bool = True
    scheduled_at: Optional[str] = None  # ISO 时间，必须带时区偏移
    idempotency_key: str = Field(min_length=8, max_length=64)


# ---------- 账号 ----------


@router.get("/accounts")
def list_accounts(
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return [
        accounts_service.serialize_account(a)
        for a in accounts_service.list_accounts(db, current_user.id, limit=limit)
    ]


@router.post("/accounts")
def create_account(
    payload: AccountCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    try:
        account = accounts_service.upsert_account(
            db, current_user.id, payload.cookie, adapter, payload.account_id
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except ValueError as error:
        # 重新授权的凭证属于同用户另一已绑定账号（upsert_account 冲突检查）
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except DouyinAdapterError as error:
        raise _map_adapter_error(error)
    return accounts_service.serialize_account(account)


@router.post("/accounts/{account_id}/check")
def check_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    account = accounts_service.get_owned_account(db, current_user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    account = accounts_service.recheck_account(db, current_user.id, account, adapter)
    return accounts_service.serialize_account(account)


@router.delete("/accounts/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = accounts_service.get_owned_account(db, current_user.id, account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    # 外键强制开启：删除账号必须先处理引用行。
    # 1) 未终结任务（pending/running/unknown）→ 拒绝，避免销毁可执行/结果不明的任务记录；
    # 2) 终态任务（succeeded/failed/cancelled）随账号删除（删号即明确放弃该账号任务历史）；
    # 3) 参考作品是用户数据，与账号解绑（source_account_id 置空）后保留。
    unfinished = db.scalar(
        select(func.count())
        .select_from(DouyinPublishTask)
        .where(
            DouyinPublishTask.account_id == account_id,
            DouyinPublishTask.status.in_(("pending", "running", "unknown")),
        )
    )
    if unfinished:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该账号存在未完成的发布任务（含结果不明），请先取消或等待结束后再删除",
        )
    db.execute(
        update(DouyinReferenceWork)
        .where(DouyinReferenceWork.source_account_id == account_id)
        .values(source_account_id=None)
    )
    db.execute(delete(DouyinPublishTask).where(DouyinPublishTask.account_id == account_id))
    db.delete(account)
    db.commit()
    return {"deleted": True}


# ---------- 参考库 ----------


@router.post("/references/collect")
def collect_reference(
    payload: CollectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    account = accounts_service.get_owned_account(db, current_user.id, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if account.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"账号状态为 {account.status}，请先重新授权")
    try:
        cookie = accounts_service.account_cookie(account)
        snapshot = adapter.crawl_work(cookie, payload.url)
    except DouyinAdapterError as error:
        raise _map_adapter_error(error)
    work = references_service.upsert_from_snapshot(db, current_user.id, snapshot, account.id)
    return {
        "reference": references_service.serialize_reference(work),
        "collected": references_service.snapshot_to_dict(snapshot),
    }


@router.get("/references")
def list_references(
    keyword: str = "", tag: str = "",
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    rows = references_service.list_references(
        db, current_user.id, keyword=keyword, tag=tag, limit=limit
    )
    return [references_service.serialize_reference(r) for r in rows]


@router.patch("/references/{reference_id}")
def update_reference(
    reference_id: int,
    payload: ReferenceUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    work = references_service.update_user_fields(
        db, current_user.id, reference_id, tags=payload.tags, note=payload.note
    )
    if work is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="参考作品不存在")
    return references_service.serialize_reference(work)


# ---------- 作品数据（复盘） ----------


@router.get("/works")
def list_works(
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    rows = references_service.list_references(db, current_user.id, limit=limit)
    latest = metrics_service.latest_metrics_map(db, current_user.id, [r.id for r in rows])
    return [
        references_service.serialize_reference(r, latest_metrics=latest.get(r.id))
        for r in rows
    ]


@router.post("/works/{reference_id}/refresh")
def refresh_work_metrics(
    reference_id: int,
    payload: WorkRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    reference = references_service.get_owned_reference(db, current_user.id, reference_id)
    if reference is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="参考作品不存在")
    if payload.account_id is not None:
        account = accounts_service.get_owned_account(db, current_user.id, payload.account_id)
    else:
        account = accounts_service.get_owned_account(db, current_user.id, reference.source_account_id or -1)
    if account is None or account.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="没有可用且已授权的账号")
    try:
        snapshot = metrics_service.refresh_reference(db, current_user.id, reference, account, adapter)
    except (DouyinAdapterError, ValueError) as error:
        db.rollback()
        raise _map_adapter_error(error) if isinstance(error, DouyinAdapterError) else HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        )
    return metrics_service.serialize_snapshot(snapshot)


@router.post("/works/refresh-account")
def refresh_account_works(
    payload: WorkRefreshRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    account = accounts_service.get_owned_account(db, current_user.id, payload.account_id or -1)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if account.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"账号状态为 {account.status}，请先重新授权")
    try:
        created = metrics_service.refresh_account_works(db, current_user.id, account, adapter)
    except (DouyinAdapterError, ValueError) as error:
        db.rollback()
        raise _map_adapter_error(error) if isinstance(error, DouyinAdapterError) else HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        )
    return {"snapshots": [metrics_service.serialize_snapshot(s) for s in created]}


# ---------- 发布任务 ----------


@router.get("/publish/tasks")
def list_publish_tasks(
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return [
        publishing_service.serialize_task(t)
        for t in publishing_service.list_tasks(db, current_user.id, limit=limit)
    ]


@router.post("/publish/tasks")
def create_publish_task(
    payload: PublishTaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = accounts_service.get_owned_account(db, current_user.id, payload.account_id)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if account.status != "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"账号状态为 {account.status}，请先重新授权")
    # 应用权限：剪辑工坊被回收后，回收前获知的 xhs-clip- 成片不得再用于发布
    if any(
        name.startswith(f"xhs-clip-u{current_user.id}-") for name in payload.media_names
    ):
        from backend.app.services.app_perms import user_has_access

        if not user_has_access(db, current_user, "clip"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="该应用未对当前账号开通，请联系管理员",
            )
    try:
        task, created = publishing_service.create_task(
            db, current_user.id, account=account, kind=payload.kind,
            media_names=payload.media_names, title=payload.title,
            description=payload.description, visibility=payload.visibility,
            allow_download=payload.allow_download,
            scheduled_at_iso=payload.scheduled_at,
            idempotency_key=payload.idempotency_key,
        )
    except publishing_service.PublishConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    except (ValueError, LookupError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    return {"task": publishing_service.serialize_task(task), "created": created}


@router.post("/publish/tasks/{task_id}/execute")
def execute_publish_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: DouyinAdapter = Depends(adapter_dependency),
):
    try:
        task = publishing_service.execute_task(db, current_user.id, task_id, adapter)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except publishing_service.PublishConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return publishing_service.serialize_task(task)


@router.post("/publish/tasks/{task_id}/cancel")
def cancel_publish_task(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        task = publishing_service.cancel_task(db, current_user.id, task_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    except publishing_service.PublishConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error))
    return publishing_service.serialize_task(task)
