from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.core.database import get_db
from backend.app.core.media_source import InvalidMediaSource, validate_media_source, validate_owned_media_source
from backend.app.core.time import to_naive_shanghai
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, PlatformAccount, PublishAsset, PublishJob, Task, User
from backend.app.schemas.common import paginate_query, paginated

router = APIRouter(prefix="/publish", tags=["publish"])


class PublishJobUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=256)
    body: Optional[str] = None
    platform_account_id: Optional[int] = None
    publish_mode: Optional[str] = Field(default=None, pattern="^(immediate|scheduled)$")
    scheduled_at: Optional[datetime] = None
    topics: Optional[list[str]] = None
    location: Optional[str] = None
    privacy_type: Optional[int] = Field(default=None, ge=0, le=1)
    is_private: Optional[bool] = None

    @field_validator("scheduled_at")
    @classmethod
    def _normalize_scheduled_at(cls, value: Optional[datetime]) -> Optional[datetime]:
        # 前端可能提交带时区偏移的 ISO 时间，统一转为库内口径（naive 北京时间）
        if value is not None:
            value = to_naive_shanghai(value)
        return value


class PublishAssetCreateRequest(BaseModel):
    asset_type: str = Field(pattern="^(image|video)$")
    file_path: str = Field(min_length=1)

    @field_validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str) -> str:
        try:
            validate_media_source(value)
        except InvalidMediaSource as exc:
            raise ValueError(str(exc)) from exc
        return value


def get_creator_publish_adapter_factory():
    return XhsCreatorApiAdapter


def _clean_topics(topics: Optional[list[str]]) -> list[str]:
    if topics is None:
        return []
    return [topic.strip() for topic in topics if topic and topic.strip()]


def _load_publish_options(job: PublishJob) -> dict[str, Any]:
    try:
        options = json.loads(job.publish_options or "{}")
    except json.JSONDecodeError:
        return {}
    return options if isinstance(options, dict) else {}


def _store_publish_options(job: PublishJob, options: dict[str, Any]) -> None:
    job.publish_options = json.dumps(options, ensure_ascii=False, separators=(",", ":"))


def _update_publish_options(job: PublishJob, payload: PublishJobUpdateRequest) -> None:
    fields = payload.model_fields_set
    if not {"topics", "location", "privacy_type", "is_private"} & fields:
        return

    options = _load_publish_options(job)
    if "topics" in fields:
        topics = _clean_topics(payload.topics)
        if topics:
            options["topics"] = topics
        else:
            options.pop("topics", None)
    if "location" in fields:
        if payload.location and payload.location.strip():
            options["location"] = payload.location.strip()
        else:
            options.pop("location", None)
    if "is_private" in fields:
        if payload.is_private is None:
            options.pop("is_private", None)
            options.pop("privacy_type", None)
        else:
            options["is_private"] = payload.is_private
            options["privacy_type"] = 1 if payload.is_private else 0
    elif "privacy_type" in fields:
        if payload.privacy_type is None:
            options.pop("privacy_type", None)
            options.pop("is_private", None)
        else:
            options["privacy_type"] = payload.privacy_type
            options["is_private"] = payload.privacy_type == 1
    _store_publish_options(job, options)


def _apply_publish_options(note_info: dict[str, Any], options: dict[str, Any]) -> None:
    topics = _clean_topics(options.get("topics") if isinstance(options.get("topics"), list) else None)
    if not topics:
        draft_tags = options.get("draft_tags")
        if isinstance(draft_tags, list):
            topics = [str(t.get("name", "")) for t in draft_tags if isinstance(t, dict) and t.get("name")]
    if topics:
        note_info["topics"] = topics
    location = options.get("location")
    if isinstance(location, str) and location.strip():
        note_info["location"] = location.strip()
    privacy_type = options.get("privacy_type")
    if privacy_type in (0, 1):
        note_info["type"] = privacy_type


def serialize_publish_job(job: PublishJob) -> dict:
    return {
        "id": job.id,
        "platform_account_id": job.platform_account_id,
        "source_draft_id": job.source_draft_id,
        "platform": job.platform,
        "title": job.title,
        "body": job.body,
        "publish_mode": job.publish_mode,
        "publish_options": _load_publish_options(job),
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "external_note_id": job.external_note_id,
        "publish_error": job.publish_error,
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "created_at": job.created_at.isoformat(),
    }


def serialize_publish_asset(asset: PublishAsset) -> dict:
    try:
        creator_upload_info = json.loads(asset.creator_upload_info or "{}")
    except json.JSONDecodeError:
        creator_upload_info = {}
    source = asset.file_path or ""
    if source.startswith(("http://", "https://")):
        display_url = source
    elif source:
        display_url = f"/api/files/media/{source}"
    else:
        display_url = ""
    return {
        "id": asset.id,
        "publish_job_id": asset.publish_job_id,
        "asset_type": asset.asset_type,
        "file_path": asset.file_path,
        "download_url": display_url,
        "upload_status": asset.upload_status,
        "creator_media_id": asset.creator_media_id,
        "upload_error": asset.upload_error,
        "creator_upload_info": creator_upload_info,
    }


def _cookies_to_string(value: str) -> str:
    """Cookie 文本 → `k=v; k=v` 头（统一实现见 account_service）。"""
    from backend.app.services.account_service import cookie_header_from_text

    return cookie_header_from_text(value)


def _extract_creator_media_id(payload: dict[str, Any]) -> str:
    for key in ("creator_media_id", "fileIds", "file_id", "media_id", "video_id"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _extract_external_note_id(payload: dict[str, Any]) -> str:
    for key in ("note_id", "noteId", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_external_note_id(data)
    return ""


def _scheduled_post_time(job: PublishJob) -> Optional[int]:
    if job.publish_mode != "scheduled":
        return None
    if job.scheduled_at is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled publish time is required")
    if job.scheduled_at <= shanghai_now():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled publish time must be in the future")
    # scheduled_at 为 naive 北京时间；显式挂 +08:00 再取时间戳，避免按服务器本地时区解释
    beijing = timezone(timedelta(hours=8))
    return int(job.scheduled_at.replace(tzinfo=beijing).timestamp() * 1000)


def _assert_asset_source_owned(asset: PublishAsset, user_id: int) -> None:
    """使用素材前惰性校验来源（存量数据可能早于归属校验上线）。

    校验失败时把素材标记为 failed，并抛出 400 让调用方得到可读错误。
    """
    try:
        validate_owned_media_source(asset.file_path, user_id)
    except InvalidMediaSource as exc:
        asset.upload_status = "failed"
        asset.upload_error = f"素材来源校验失败: {exc}"[:500]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def execute_claimed_publish_job(
    db: Session,
    *,
    job: PublishJob,
    account: PlatformAccount,
    current_user: User,
    adapter_factory,
) -> None:
    """执行一个已领取（publishing）的发布任务：上传素材 → 调 Creator API → 落结果。

    供手动发布端点与自动运营手动运行共用（SCH-1/5）。调用方必须已经用
    条件 UPDATE 完成原子领取并提交，且发起网络请求前所有状态已落库。
    """
    assets = db.scalars(
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id).order_by(PublishAsset.id.asc())
    ).all()
    if not assets:
        job.status = "failed"
        job.publish_error = "至少需要一个素材"
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="至少需要一个素材")

    cookies = _get_latest_account_cookies(db, account.id)
    adapter = adapter_factory(cookies)

    for asset in assets:
        if asset.upload_status in ("pending", "failed"):
            try:
                _assert_asset_source_owned(asset, current_user.id)
            except HTTPException:
                # 任务已被领取为 publishing，校验失败必须同步落失败状态，
                # 否则任务会滞留中间态直到对账回收
                job.status = "failed"
                job.publish_error = f"素材来源校验失败: {asset.upload_error}"[:500]
                db.commit()
                raise
            try:
                payload = adapter.upload_media(asset.file_path, asset.asset_type)
                asset.upload_status = "uploaded"
                asset.creator_media_id = _extract_creator_media_id(payload)
                asset.creator_upload_info = json.dumps(payload, ensure_ascii=False)
                asset.upload_error = ""
            except Exception as exc:
                asset.upload_status = "failed"
                asset.upload_error = str(exc)[:500]
                job.status = "failed"
                job.publish_error = f"素材上传失败: {exc}"[:500]
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"素材上传失败: {exc}",
                ) from exc
    db.commit()

    uploaded_images = [a for a in assets if a.asset_type == "image" and a.upload_status == "uploaded"]
    uploaded_videos = [a for a in assets if a.asset_type == "video" and a.upload_status == "uploaded"]

    def _fail_and_raise(detail: str) -> None:
        # review P1-2：任务已被领取为 publishing，确定性失败必须同步落 failed，
        # 否则用户重试永远 409，直到进程重启触发对账
        job.status = "failed"
        job.publish_error = detail[:500]
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    if not uploaded_images and not uploaded_videos:
        _fail_and_raise("没有成功上传的素材")

    if uploaded_videos:
        _fail_and_raise("视频发布功能即将上线，目前仅支持图片发布")

    image_file_infos = [_asset_creator_upload_info(asset) for asset in uploaded_images]

    note_info = {
        "title": job.title,
        "desc": job.body,
        "media_type": "image",
        "image_file_infos": image_file_infos,
        "type": 1,
        "postTime": _scheduled_post_time(job),
    }
    _apply_publish_options(note_info, _load_publish_options(job))

    task = Task(
        user_id=current_user.id,
        platform=job.platform,
        task_type="creator_publish",
        status="running",
        progress=20,
        payload={
            "publish_job_id": job.id,
            "platform_account_id": account.id,
            "asset_ids": [asset.id for asset in uploaded_images],
            "publish_mode": job.publish_mode,
        },
    )
    db.add(task)
    db.commit()

    try:
        payload = adapter_factory(cookies).post_note(note_info)
        job.status = "scheduled" if job.publish_mode == "scheduled" else "published"
        job.external_note_id = _extract_external_note_id(payload)
        job.publish_error = ""
        job.published_at = shanghai_now()
        task.status = "completed"
        task.progress = 100
        task.payload = {
            **(task.payload or {}),
            "external_note_id": job.external_note_id,
            "published_at": job.published_at.isoformat(),
        }
        db.commit()
        db.refresh(job)
    except Exception as exc:
        db.rollback()
        job = db.get(PublishJob, job.id)
        task = db.get(Task, task.id)
        job.status = "failed"
        job.publish_error = str(exc)[:500]
        if task is not None:
            task.status = "failed"
            task.progress = 100
            task.payload = {**(task.payload or {}), "error": str(exc)[:500]}
        db.commit()
        db.refresh(job)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=job.publish_error)


def _asset_creator_upload_info(asset: PublishAsset) -> dict[str, Any]:
    try:
        upload_info = json.loads(asset.creator_upload_info or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded asset metadata is invalid") from exc
    if not upload_info.get("fileIds"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded asset is missing Creator upload info")
    return upload_info


def _get_owned_publish_job(db: Session, current_user: User, job_id: int) -> PublishJob:
    job = db.scalars(
        select(PublishJob)
        .where(PublishJob.id == job_id, PublishJob.user_id == current_user.id)
    ).first()
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish job not found")
    return job


def _get_owned_publish_asset(db: Session, current_user: User, asset_id: int) -> PublishAsset:
    asset = db.scalars(
        select(PublishAsset)
        .join(PublishJob, PublishAsset.publish_job_id == PublishJob.id)
        .where(
            PublishAsset.id == asset_id,
            PublishJob.user_id == current_user.id,
        )
    ).first()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish asset not found")
    return asset


def _get_latest_account_cookies(db: Session, account_id: int) -> str:
    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account_id)
        .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc())
    ).first()
    if cookie_version is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account has no cookies")
    return _cookies_to_string(decrypt_text(cookie_version.encrypted_cookies))


def _record_publish_control_task(db: Session, current_user: User, job: PublishJob, task_type: str) -> None:
    task = Task(
        user_id=current_user.id,
        platform=job.platform,
        task_type=task_type,
        status="pending",
        progress=0,
        payload={
            "publish_job_id": job.id,
            "platform_account_id": job.platform_account_id,
            "publish_mode": job.publish_mode,
        },
    )
    db.add(task)


@router.get("/jobs")
def get_publish_jobs(
    platform: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(PublishJob)
        .where(PublishJob.user_id == current_user.id)
    )
    if platform:
        statement = statement.where(PublishJob.platform == platform)
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        statement,
        page=page,
        page_size=page_size,
        serializer=serialize_publish_job,
        order_by=(PublishJob.created_at.desc(), PublishJob.id.desc()),
    )


@router.get("/jobs/{job_id}")
def get_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return serialize_publish_job(_get_owned_publish_job(db, current_user, job_id))


@router.patch("/jobs/{job_id}")
def update_publish_job(
    job_id: int,
    payload: PublishJobUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if payload.platform_account_id is not None:
        account = db.get(PlatformAccount, payload.platform_account_id)
        if account is None or account.user_id != current_user.id or account.platform != job.platform:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Platform account not found")
        # SCH-3：改绑必须是 Creator 子类型账号，否则任务到期执行时必然失败并阻塞队列
        if account.sub_type != "creator":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Publish jobs require a Creator (creator) account",
            )
        job.platform_account_id = account.id
    if payload.title is not None:
        job.title = payload.title
    if payload.body is not None:
        job.body = payload.body
    if payload.publish_mode is not None:
        job.publish_mode = payload.publish_mode
    if payload.scheduled_at is not None or payload.publish_mode == "immediate":
        job.scheduled_at = payload.scheduled_at
    # SCH-6：scheduled 模式的交叉字段校验——没有未来时间的 scheduled 任务会永远滞留 pending
    if job.publish_mode == "scheduled":
        if job.scheduled_at is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="scheduled 发布模式必须提供未来的 scheduled_at",
            )
        if job.scheduled_at <= shanghai_now():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="scheduled_at 必须晚于当前时间",
            )
    _update_publish_options(job, payload)

    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.post("/jobs/{job_id}/retry")
def retry_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish job cannot be retried")

    job.status = "pending"
    job.publish_error = ""
    job.external_note_id = ""
    job.published_at = None
    _record_publish_control_task(db, current_user, job, "creator_publish_retry")
    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status not in {"pending", "scheduled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish job cannot be cancelled")

    job.status = "cancelled"
    _record_publish_control_task(db, current_user, job, "creator_publish_cancel")
    db.commit()
    db.refresh(job)
    return serialize_publish_job(job)


@router.delete("/jobs/{job_id}")
def delete_publish_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if job.status in {"publishing", "uploading"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="正在进行中的任务无法删除")

    for asset in db.scalars(select(PublishAsset).where(PublishAsset.publish_job_id == job.id)).all():
        db.delete(asset)
    db.delete(job)
    db.commit()
    return {"ok": True}


@router.get("/jobs/{job_id}/assets")
def get_publish_assets(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        select(PublishAsset).where(PublishAsset.publish_job_id == job.id),
        page=page,
        page_size=page_size,
        serializer=serialize_publish_asset,
        order_by=PublishAsset.id.asc(),
    )


@router.post("/jobs/{job_id}/assets")
def create_publish_asset(
    job_id: int,
    payload: PublishAssetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    # 本地文件名必须属于当前用户（防跨用户引用他人媒体；URL 走白名单校验）
    try:
        validated_source = validate_owned_media_source(payload.file_path, current_user.id)
    except InvalidMediaSource as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    asset = PublishAsset(publish_job_id=job.id, asset_type=payload.asset_type, file_path=validated_source)
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return serialize_publish_asset(asset)


@router.delete("/assets/{asset_id}")
def delete_publish_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    asset = _get_owned_publish_asset(db, current_user, asset_id)
    db.delete(asset)
    db.commit()
    return {"id": asset_id, "status": "deleted"}


@router.post("/assets/{asset_id}/upload")
def upload_publish_asset(
    asset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    asset = _get_owned_publish_asset(db, current_user, asset_id)
    job = db.get(PublishJob, asset.publish_job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Publish job not found")

    account = db.get(PlatformAccount, job.platform_account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if account.platform != "xhs" or account.sub_type != "creator":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Creator account required")

    cookies = _get_latest_account_cookies(db, account.id)
    _assert_asset_source_owned(asset, current_user.id)
    asset.upload_status = "uploading"
    asset.upload_error = ""
    db.commit()

    try:
        payload = adapter_factory(cookies).upload_media(asset.file_path, asset.asset_type)
        asset.upload_status = "uploaded"
        asset.creator_media_id = _extract_creator_media_id(payload)
        asset.creator_upload_info = json.dumps(payload, ensure_ascii=False)
        asset.upload_error = ""
        db.commit()
        db.refresh(asset)
        return serialize_publish_asset(asset)
    except Exception as exc:
        asset.upload_status = "failed"
        asset.upload_error = str(exc)
        db.commit()
        db.refresh(asset)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=asset.upload_error)


@router.post("/jobs/{job_id}/publish")
def publish_job_to_creator(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter_factory=Depends(get_creator_publish_adapter_factory),
):
    job = _get_owned_publish_job(db, current_user, job_id)
    if not job.platform_account_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先选择发布账号")
    account = db.get(PlatformAccount, job.platform_account_id)
    if account is None or account.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    if account.platform != "xhs" or account.sub_type != "creator":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Creator account required")
    if job.status in {"publishing", "uploading", "published", "scheduled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish job is already completed or in progress")
    if not job.title.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Publish title is required")
    if job.publish_mode == "scheduled":
        if job.scheduled_at is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled publish time is required")
        if job.scheduled_at <= shanghai_now():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Scheduled publish time must be in the future")

    # 原子领取：条件 UPDATE 抢占，防止与调度器 / run-due 并发时重复发布
    claimed = db.execute(
        update(PublishJob)
        .where(
            PublishJob.id == job.id,
            PublishJob.status.not_in(("publishing", "uploading", "published", "scheduled")),
        )
        .values(status="publishing", publish_error="", publish_started_at=shanghai_now())
    )
    db.commit()
    if claimed.rowcount != 1:
        db.refresh(job)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Publish job is already completed or in progress")
    db.refresh(job)

    # 领取成功后共用同一执行器（SCH-1/5）
    execute_claimed_publish_job(db, job=job, account=account, current_user=current_user, adapter_factory=adapter_factory)
    db.refresh(job)
    return serialize_publish_job(job)
