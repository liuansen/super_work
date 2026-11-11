from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.core.database import SessionLocal
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now, to_naive_shanghai
from backend.app.models import (
    AccountCookieVersion,
    AiDraft,
    AutoTask,
    ModelConfig,
    MonitoringSnapshot,
    MonitoringTarget,
    Note,
    Notification,
    PlatformAccount,
    PublishAsset,
    PublishJob,
    Task,
    User,
)


def _cookies_to_string(value: str) -> str:
    """Cookie 文本 → `k=v; k=v` 头（统一实现见 account_service）。"""
    from backend.app.services.account_service import cookie_header_from_text

    return cookie_header_from_text(value)


def _latest_account_cookies(db: Session, account_id: int) -> str:
    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account_id)
        .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc())
    ).first()
    if cookie_version is None:
        raise RuntimeError("Account has no cookies")
    return _cookies_to_string(decrypt_text(cookie_version.encrypted_cookies))


def _asset_upload_info(asset: PublishAsset) -> dict[str, Any]:
    try:
        payload = json.loads(asset.creator_upload_info or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("Uploaded asset metadata is invalid") from exc
    if not payload.get("fileIds"):
        raise RuntimeError("Uploaded asset is missing Creator upload info")
    return payload


def _external_note_id(payload: dict[str, Any]) -> str:
    for key in ("note_id", "noteId", "id"):
        value = payload.get(key)
        if value:
            return str(value)
    data = payload.get("data")
    if isinstance(data, dict):
        return _external_note_id(data)
    return ""


def _serialize_publish_job(job: PublishJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "platform_account_id": job.platform_account_id,
        "source_draft_id": job.source_draft_id,
        "platform": job.platform,
        "title": job.title,
        "body": job.body,
        "publish_mode": job.publish_mode,
        "status": job.status,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "external_note_id": job.external_note_id,
        "publish_error": job.publish_error,
        "published_at": job.published_at.isoformat() if job.published_at else None,
        "created_at": job.created_at.isoformat(),
    }


def _load_publish_options(job: PublishJob) -> dict[str, Any]:
    try:
        options = json.loads(job.publish_options or "{}")
    except json.JSONDecodeError:
        return {}
    return options if isinstance(options, dict) else {}


def _clean_topics(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [topic.strip() for topic in value if isinstance(topic, str) and topic.strip()]


def _apply_publish_options(note_info: dict[str, Any], options: dict[str, Any]) -> None:
    topics = _clean_topics(options.get("topics"))
    if topics:
        note_info["topics"] = topics
    location = options.get("location")
    if isinstance(location, str) and location.strip():
        note_info["location"] = location.strip()
    if options.get("privacy_type") in (0, 1):
        note_info["type"] = options["privacy_type"]


def _claim_publish_job(db: Session, job_id: int) -> bool:
    """原子领取：仅当任务仍为 pending 时置为 publishing（条件 UPDATE）。

    调度器、手动发布接口、/tasks/run-due 三方并发时，只有一个能领取成功，
    杜绝对同一笔记重复发布。
    """
    claimed = db.execute(
        update(PublishJob)
        .where(PublishJob.id == job_id, PublishJob.status == "pending")
        .values(status="publishing", publish_error="", publish_started_at=shanghai_now())
    )
    db.commit()
    return claimed.rowcount == 1


def _run_one_due_publish_job(db: Session, current_user: User, job: PublishJob, adapter_factory) -> tuple[str, dict[str, Any]]:
    """领取并执行一个到期任务。返回 (outcome, serialized)；outcome ∈ published/failed/skipped。"""
    if not _claim_publish_job(db, job.id):
        db.refresh(job)
        return "skipped", _serialize_publish_job(job)
    db.refresh(job)

    task = Task(
        user_id=current_user.id,
        platform=job.platform,
        task_type="creator_publish_scheduler",
        status="running",
        progress=20,
        payload={"publish_job_id": job.id, "platform_account_id": job.platform_account_id, "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None},
    )
    db.add(task)
    db.commit()

    try:
        account = db.get(PlatformAccount, job.platform_account_id)
        if account is None or account.user_id != current_user.id:
            raise RuntimeError("Account not found")
        if account.platform != "xhs" or account.sub_type != "creator":
            raise RuntimeError("Creator account required")

        assets = db.scalars(
            select(PublishAsset).where(PublishAsset.publish_job_id == job.id).order_by(PublishAsset.id.asc())
        ).all()
        if any(asset.asset_type != "image" for asset in assets):
            raise RuntimeError("Only image publish is supported")
        uploaded_assets = [asset for asset in assets if asset.upload_status == "uploaded"]
        if not uploaded_assets:
            raise RuntimeError("At least one uploaded image asset is required")

        note_info = {
            "title": job.title,
            "desc": job.body,
            "media_type": "image",
            "image_file_infos": [_asset_upload_info(asset) for asset in uploaded_assets],
            "type": 1,
            "postTime": None,
        }
        _apply_publish_options(note_info, _load_publish_options(job))
        payload = adapter_factory(_latest_account_cookies(db, account.id)).post_note(note_info)
        job.status = "published"
        job.external_note_id = _external_note_id(payload)
        job.publish_error = ""
        job.published_at = shanghai_now()
        task.status = "completed"
        task.progress = 100
        task.payload = {**(task.payload or {}), "external_note_id": job.external_note_id, "published_at": job.published_at.isoformat()}
        db.commit()
        db.refresh(job)
        return "published", _serialize_publish_job(job)
    except Exception as exc:
        db.rollback()
        job = db.get(PublishJob, job.id)
        task = db.get(Task, task.id)
        job.status = "failed"
        job.publish_error = str(exc)
        if task is not None:
            task.status = "failed"
            task.progress = 100
            task.payload = {**(task.payload or {}), "error": str(exc)}
        # SCH-5 对等：定时发布失败此前只写库，用户不主动看任务列表就不知道，
        # 与 auto task 路径的 _record_auto_task_failure 不对称。
        try:
            from backend.app.services.notification_service import notify_publish_failed

            notify_publish_failed(
                db,
                current_user.id,
                # Notification.title 是 String(256)：PublishJob.title 最长 256，
                # 拼上「发布失败: 」前缀会溢出，MySQL strict 模式下 flush 抛错
                # 会连带让上面的失败状态无法落库。这里先截断。
                (job.title or f"任务 #{job.id}")[:240],
                job.id,
                task_id=task.id if task is not None else None,
                error=str(exc),
            )
        except Exception:  # 通知失败不能影响失败状态落库
            logger.warning("写入发布失败通知失败: job=%s", job.id, exc_info=True)
        db.commit()
        db.refresh(job)
        return "failed", _serialize_publish_job(job)


def run_due_publish_jobs(
    *,
    db: Session,
    current_user: User,
    now: Optional[datetime],
    platform: str,
    adapter_factory,
) -> dict[str, Any]:
    now = now or shanghai_now()
    due_jobs = db.scalars(
        select(PublishJob)
        .join(PlatformAccount, PublishJob.platform_account_id == PlatformAccount.id)
        .where(
            PlatformAccount.user_id == current_user.id,
            PublishJob.platform == platform,
            PublishJob.publish_mode == "scheduled",
            PublishJob.status == "pending",
            PublishJob.scheduled_at.is_not(None),
            PublishJob.scheduled_at <= now,
        )
        .order_by(PublishJob.scheduled_at.asc(), PublishJob.id.asc())
    ).all()

    items: list[dict[str, Any]] = []
    skipped_count = 0
    failed_count = 0
    for job in due_jobs:
        try:
            outcome, item = _run_one_due_publish_job(db, current_user, job, adapter_factory)
        except Exception as exc:
            db.rollback()
            logger.exception(f"Due publish job {job.id} crashed: {exc}")
            try:
                stale = db.get(PublishJob, job.id)
                if stale is not None and stale.status in ("pending", "publishing"):
                    stale.status = "failed"
                    stale.publish_error = f"调度器内部错误: {exc}"[:500]
                db.commit()
                item = _serialize_publish_job(db.get(PublishJob, job.id))
            except Exception:
                db.rollback()
                continue
            outcome = "failed"
        if outcome == "skipped":
            skipped_count += 1
            continue
        items.append(item)
        if outcome == "failed":
            failed_count += 1

    return {
        "executed_count": len(items),
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "items": items,
    }


def run_due_publish_jobs_for_all_users(
    *,
    db: Session,
    now: Optional[datetime],
    platform: str,
    adapter_factory,
) -> dict[str, Any]:
    now = now or shanghai_now()
    users = db.scalars(
        select(User)
        .join(PlatformAccount, PlatformAccount.user_id == User.id)
        .join(PublishJob, PublishJob.platform_account_id == PlatformAccount.id)
        .where(
            PublishJob.platform == platform,
            PublishJob.publish_mode == "scheduled",
            PublishJob.status == "pending",
            PublishJob.scheduled_at.is_not(None),
            PublishJob.scheduled_at <= now,
        )
        .distinct()
        .order_by(User.id.asc())
    ).all()

    items: list[dict[str, Any]] = []
    failed_count = 0
    for user in users:
        result = run_due_publish_jobs(
            db=db,
            current_user=user,
            now=now,
            platform=platform,
            adapter_factory=adapter_factory,
        )
        items.extend(result["items"])
        failed_count += result["failed_count"]

    return {
        "executed_count": len(items),
        "failed_count": failed_count,
        "items": items,
    }


def run_due_publish_jobs_once(platform: str = "xhs", adapter_factory=XhsCreatorApiAdapter) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_due_publish_jobs_for_all_users(
            db=db,
            now=None,
            platform=platform,
            adapter_factory=adapter_factory,
        )
    finally:
        db.close()


STALE_PUBLISH_TIMEOUT_MINUTES = 30


def reconcile_stale_publish_jobs(*, db: Optional[Session] = None) -> dict[str, Any]:
    """启动对账：把进程崩溃/重启时滞留在 publishing/uploading 的任务复位为 failed。

    只复位超过超时阈值的任务（正常上传+发布最多几分钟），避免误伤
    其他 worker 正在执行中的任务；publish_started_at 为 NULL 的视为
    历史遗留（旧数据），同样复位。
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        now = shanghai_now()
        cutoff = now - timedelta(minutes=STALE_PUBLISH_TIMEOUT_MINUTES)
        stale_jobs = session.scalars(
            select(PublishJob).where(
                PublishJob.status.in_(("publishing", "uploading")),
                or_(
                    PublishJob.publish_started_at.is_(None),
                    PublishJob.publish_started_at <= cutoff,
                ),
            )
        ).all()
        for job in stale_jobs:
            job.status = "failed"
            job.publish_error = "任务执行被进程重启中断，请重试"
        if stale_jobs:
            session.commit()
            logger.warning(f"启动对账：复位 {len(stale_jobs)} 个滞留的发布任务")
        return {"reset_publish_jobs": len(stale_jobs)}
    except Exception as exc:
        session.rollback()
        logger.error(f"reconcile_stale_publish_jobs failed: {exc}")
        return {"reset_publish_jobs": 0, "error": str(exc)}
    finally:
        if own_session:
            session.close()


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if cleaned.isdigit():
            return int(cleaned)
    return 0


def _first_metric(raw: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in raw:
            return _as_int(raw.get(key))
    return 0


def _note_metrics(note: Note) -> dict[str, int]:
    raw = note.raw_json or {}
    interaction = raw.get("interact_info") if isinstance(raw.get("interact_info"), dict) else {}
    merged = {**raw, **interaction}
    likes = _first_metric(merged, ("likes", "liked_count", "like_count", "likedCount"))
    collects = _first_metric(merged, ("collects", "collected_count", "collect_count", "collectedCount"))
    comments = _first_metric(merged, ("comments", "comment_count", "commentCount"))
    shares = _first_metric(merged, ("shares", "share_count", "shareCount"))
    return {
        "likes": likes,
        "collects": collects,
        "comments": comments,
        "shares": shares,
        "engagement": likes + collects + comments + shares,
    }


def _serialize_monitoring_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "title": note.title,
        "author_name": note.author_name,
        "created_at": note.created_at.isoformat(),
        **_note_metrics(note),
    }


def _note_haystack(note: Note) -> str:
    raw_text = json.dumps(note.raw_json or {}, ensure_ascii=False)
    return "\n".join([note.note_id, note.title, note.content, note.author_name, raw_text]).lower()


def _note_matches_target(note: Note, target: MonitoringTarget) -> bool:
    needle = target.value.strip().lower()
    if not needle:
        return False
    return needle in _note_haystack(note)


# PERF-1：单个目标参与匹配计算的笔记上限（内存快照不随全库线性增长）
MONITORING_MATCH_NOTE_LIMIT = 2000
# PERF-1：每个目标的快照保留条数（超过则清理最旧的）
MONITORING_SNAPSHOT_KEEP = 100


def _matching_notes_for_target(db: Session, target: MonitoringTarget, platform: str) -> list[Note]:
    """先在 SQL 里预过滤关键词，再在 Python 中精筛。

    统一走 services/note_search：检索列是写入时算好的 ``notes.search_text``
    （SQLite 上还有 FTS5 trigram 索引），不再对 raw_json 做 json.dumps + LIKE。
    """
    from backend.app.services.note_search import candidate_notes, note_matches

    needle = target.value.strip()
    if not needle:
        return []
    candidates = candidate_notes(
        db,
        user_id=target.user_id,
        platform=platform,
        needle=needle,
        limit=MONITORING_MATCH_NOTE_LIMIT,
    )
    matched = [note for note in candidates if note_matches(note, needle)]
    return sorted(matched, key=lambda note: _note_metrics(note)["engagement"], reverse=True)


def _prune_monitoring_snapshots(db: Session, target_id: int, keep: int = MONITORING_SNAPSHOT_KEEP) -> int:
    """PERF-1：快照保留策略——每目标只保留最近 N 条。"""
    stale_ids = db.scalars(
        select(MonitoringSnapshot.id)
        .where(MonitoringSnapshot.target_id == target_id)
        .order_by(MonitoringSnapshot.id.desc())
        .offset(keep)
        .limit(1000)
    ).all()
    if not stale_ids:
        return 0
    db.execute(
        delete(MonitoringSnapshot).where(MonitoringSnapshot.id.in_(stale_ids))
    )
    return len(stale_ids)


def _refresh_monitoring_target(db: Session, target: MonitoringTarget, now: datetime, platform: str) -> dict[str, Any]:
    matched_notes = _matching_notes_for_target(db, target, platform)
    snapshot_payload = {
        "matched_count": len(matched_notes),
        "total_engagement": sum(_note_metrics(note)["engagement"] for note in matched_notes),
        "top_notes": [_serialize_monitoring_note(note) for note in matched_notes[:10]],
    }
    target.last_refreshed_at = now
    target.updated_at = now
    snapshot = MonitoringSnapshot(target_id=target.id, payload=snapshot_payload)
    db.add(snapshot)
    db.flush()
    # PERF-1：快照保留策略，防止每天 14.4 万行的无限增长
    _prune_monitoring_snapshots(db, target.id)
    db.flush()

    task = Task(
        user_id=target.user_id,
        platform=platform,
        task_type="monitoring_refresh",
        status="completed",
        progress=100,
        payload={
            "target_id": target.id,
            "target_type": target.target_type,
            "value": target.value,
            "snapshot_id": snapshot.id,
            "matched_count": snapshot_payload["matched_count"],
            "scheduler": True,
        },
    )
    db.add(task)
    db.flush()
    return {
        "target_id": target.id,
        "snapshot_id": snapshot.id,
        "matched_count": snapshot_payload["matched_count"],
        "total_engagement": snapshot_payload["total_engagement"],
    }


def run_monitoring_refresh_for_all_users(*, db: Session, now: Optional[datetime], platform: str) -> dict[str, Any]:
    now = now or shanghai_now()
    targets = db.scalars(
        select(MonitoringTarget)
        .where(
            MonitoringTarget.platform == platform,
            MonitoringTarget.status == "active",
        )
        .order_by(MonitoringTarget.id.asc())
    ).all()

    items = []
    for target in targets:
        # 尊重每个 target 自己的抓取间隔，而不是每个调度 tick 全量刷新
        interval_minutes = target.crawl_interval_minutes or 60
        if target.last_refreshed_at is not None:
            due_at = target.last_refreshed_at + timedelta(minutes=interval_minutes)
            if now < due_at:
                continue
        try:
            item = _refresh_monitoring_target(db, target, now, platform)
            db.commit()
            items.append(item)
        except Exception as exc:
            db.rollback()
            logger.warning(f"Monitoring refresh failed for target {target.id}: {exc}")

    return {
        "refreshed_count": len(items),
        "items": items,
    }


def run_monitoring_refresh_once(platform: str = "xhs") -> dict[str, Any]:
    db = SessionLocal()
    try:
        return run_monitoring_refresh_for_all_users(db=db, now=None, platform=platform)
    finally:
        db.close()


def _get_text_model_for_user(db: Session, user_id: int):
    config = db.scalars(
        select(ModelConfig).where(
            ModelConfig.user_id == user_id,
            ModelConfig.model_type == "text",
            ModelConfig.is_default.is_(True),
        )
    ).first()
    if not config or not config.encrypted_api_key:
        return None, ""
    return config, decrypt_text(config.encrypted_api_key)


def _scheduler_cookies_to_string(value: str) -> str:
    """兼容旧调用点：与 _cookies_to_string 共用同一实现。"""
    return _cookies_to_string(value)


AUTO_TASK_CLAIM_STALE_MINUTES = 30


def _claim_auto_task(db: Session, task_id: int, *, now: Optional[datetime] = None) -> bool:
    """SCH-2：原子领取自动运营任务。

    条件 UPDATE：仅当任务 active 且未被领取（或领取已超时）时置 claimed_at。
    防止调度器 tick 与手动运行并发重复执行同一任务。
    """
    now = now or shanghai_now()
    stale_cutoff = now - timedelta(minutes=AUTO_TASK_CLAIM_STALE_MINUTES)
    claimed = db.execute(
        update(AutoTask)
        .where(
            AutoTask.id == task_id,
            AutoTask.status == "active",
            or_(AutoTask.claimed_at.is_(None), AutoTask.claimed_at <= stale_cutoff),
        )
        .values(claimed_at=now)
    )
    db.commit()
    return claimed.rowcount == 1


def _release_auto_task_claim(db: Session, task_id: int) -> None:
    try:
        fresh = db.get(AutoTask, task_id)
        if fresh is not None:
            fresh.claimed_at = None
            db.commit()
    except Exception:
        db.rollback()


def _record_auto_task_failure(db: Session, task: AutoTask, reason: str) -> None:
    """SCH-5：自动运营的每次失败都写 Task 审计记录 + 用户通知，不再静默。"""
    task.last_run_at = shanghai_now()
    db.add(
        Task(
            user_id=task.user_id,
            platform="xhs",
            task_type="auto_ops_run",
            status="failed",
            progress=100,
            error_type="auto_task",
            payload={
                "auto_task_id": task.id,
                "auto_task_name": task.name,
                "error": reason[:500],
            },
        )
    )
    db.add(
        Notification(
            user_id=task.user_id,
            title="自动运营运行失败",
            body=f"任务「{task.name}」本次运行失败：{reason[:200]}",
            level="warning",
        )
    )
    db.commit()


def _execute_auto_task_background(db: Session, task: AutoTask) -> None:
    """Simplified auto-task execution for background scheduler.

    事务边界（SCH-2/P0-5）：
    1. 素材上传完成、任务置 publishing 后先提交，再做发布网络调用；
    2. 发布结果用独立事务提交——外部发布成功后任何本地失败都不会导致重复发布。
    所有提前失败路径写 Task + Notification（SCH-5），不再静默返回。
    """
    import random

    from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
    from backend.app.services.xhs_normalizers import (
        data_items as _data_items,
        normalize_search_item as _normalize_search_item,
    )
    from backend.app.services.ai_service import OpenAICompatibleTextClient

    # Get PC cookies
    account = db.get(PlatformAccount, task.pc_account_id)
    if not account:
        _record_auto_task_failure(db, task, "未找到可用的 PC 账号")
        return
    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if not cookie_version:
        _record_auto_task_failure(db, task, "PC 账号没有可用的 Cookie 版本")
        return
    cookies = _scheduler_cookies_to_string(decrypt_text(cookie_version.encrypted_cookies))

    # Pick keyword
    keywords = task.keywords or []
    if not keywords:
        _record_auto_task_failure(db, task, "未配置关键词")
        return
    keyword = random.choice(keywords)

    # Search
    adapter = XhsPcApiAdapter(cookies)
    try:
        success, message, raw = adapter.search_note(keyword, page=1)
    except Exception as exc:
        _record_auto_task_failure(db, task, f"搜索异常: {exc}")
        return
    if not success:
        _record_auto_task_failure(db, task, f"搜索失败: {message or '未知错误'}")
        return

    items = _data_items(raw)
    normalized = [_normalize_search_item(item) for item in items[:10]]
    if not normalized:
        _record_auto_task_failure(db, task, f"关键词「{keyword}」没有搜索到可用笔记")
        return

    # Pick best
    best = max(
        normalized,
        key=lambda n: sum([n.get("likes", 0), n.get("collects", 0), n.get("comments", 0), n.get("shares", 0)]),
    )

    # Create draft
    draft = AiDraft(
        user_id=task.user_id,
        platform="xhs",
        title=best.get("title", ""),
        body=best.get("content", ""),
    )
    db.add(draft)
    db.flush()

    # Try AI rewrite title + body (non-fatal, but never silent)
    try:
        model_config, api_key = _get_text_model_for_user(db, task.user_id)
        if model_config:
            client = OpenAICompatibleTextClient()
            instruction = task.ai_instruction or "改写为原创小红书笔记"
            rewritten_body = client.rewrite_note(
                model_config=model_config,
                api_key=api_key,
                title=draft.title,
                body=draft.body,
                instruction=instruction,
            )
            draft.body = rewritten_body
            try:
                titles = client.generate_titles(
                    model_config=model_config,
                    api_key=api_key,
                    title=draft.title,
                    body=draft.body,
                    count=1,
                )
                if titles:
                    draft.title = titles[0]
            except Exception as exc:
                logger.warning(f"Auto task {task.id} title generation failed: {exc}")
        else:
            logger.warning(
                f"Auto task {task.id} 未配置可用的文本模型，将以原文发布（存在搬运风险）"
            )
    except Exception as exc:
        logger.warning(f"Auto task {task.id} AI rewrite failed,将以原文发布: {exc}")

    # Get Creator cookies
    creator_account = db.get(PlatformAccount, task.creator_account_id)
    if not creator_account:
        db.rollback()
        _record_auto_task_failure(db, task, "未找到可用的 Creator 账号")
        return
    creator_cv = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == creator_account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if not creator_cv:
        db.rollback()
        _record_auto_task_failure(db, task, "Creator 账号没有可用的 Cookie 版本")
        return
    creator_cookies = _scheduler_cookies_to_string(decrypt_text(creator_cv.encrypted_cookies))

    # Upload images and create publish job
    from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter as AutoCreatorAdapter
    creator_adapter = AutoCreatorAdapter(creator_cookies)

    image_urls = (best.get("image_urls") or [])[:9]
    file_infos = []
    for url in image_urls:
        if not url:
            continue
        try:
            payload = creator_adapter.upload_media(url, "image")
            file_infos.append(payload)
        except Exception as exc:
            logger.warning(f"Auto task {task.id} image upload failed: {exc}")

    if not file_infos:
        db.rollback()
        _record_auto_task_failure(db, task, "源笔记图片上传到创作平台全部失败")
        return

    # Create publish job：先提交 publishing 状态，再做发布网络调用（SCH-2）
    job = PublishJob(
        user_id=task.user_id,
        platform_account_id=task.creator_account_id,
        source_draft_id=draft.id,
        platform="xhs",
        title=draft.title,
        body=draft.body,
        publish_mode="immediate",
        status="publishing",
        publish_started_at=shanghai_now(),
    )
    db.add(job)
    db.flush()

    for info in file_infos:
        db.add(PublishAsset(
            publish_job_id=job.id,
            asset_type="image",
            file_path="",
            upload_status="uploaded",
            creator_media_id=str(info.get("fileIds", "") or ""),
            creator_upload_info=json.dumps(info, ensure_ascii=False, default=str),
        ))
    db.commit()

    # Publish via Creator API（结果用独立事务提交）
    try:
        note_info = {
            "title": job.title,
            "desc": job.body,
            "media_type": "image",
            "image_file_infos": file_infos,
            "type": 1,
            "postTime": None,
        }
        result = creator_adapter.post_note(note_info)
        job.status = "published"
        job.external_note_id = ""
        for key in ("note_id", "noteId", "id"):
            v = result.get(key) or (result.get("data", {}) or {}).get(key)
            if v:
                job.external_note_id = str(v)
                break
        job.published_at = shanghai_now()
    except Exception as exc:
        job.status = "failed"
        job.publish_error = str(exc)[:500]
        logger.warning(f"Auto task {task.id} publish failed: {exc}")

    if job.status == "published":
        task.total_published = (task.total_published or 0) + 1
        task.last_run_at = shanghai_now()
        db.commit()
        logger.info(f"Auto task {task.id} executed: keyword={keyword}, job={job.id}, status={job.status}")
    else:
        publish_error = job.publish_error
        db.commit()
        task.last_run_at = shanghai_now()
        _record_auto_task_failure(db, task, f"发布失败: {publish_error}")


def run_due_auto_tasks() -> None:
    from backend.app.api.auto_tasks import _calculate_next_run_at

    db = SessionLocal()
    try:
        now = shanghai_now()
        due_tasks = db.scalars(
            select(AutoTask).where(
                AutoTask.status == "active",
                AutoTask.schedule_type != "manual",
                AutoTask.next_run_at != None,  # noqa: E711
                AutoTask.next_run_at <= now,
            )
        ).all()

        for task in due_tasks:
            # SCH-2：先原子领取并提交，再执行——并发 tick / 手动运行只有一个能执行
            if not _claim_auto_task(db, task.id, now=now):
                continue
            try:
                _execute_auto_task_background(db, task)
            except Exception as exc:
                db.rollback()
                logger.warning(f"Auto task {task.id} execution failed: {exc}")
                _record_auto_task_failure(db, task, f"执行异常: {exc}")
            finally:
                # review P3：排期推进必须发生在释放 claim 之前。若先释放再推进，
                # 中间存在「claim 已释放且 next_run_at 仍在过去」的窗口，并发 tick
                # 会再次领取执行（等于重复发布）。持有 claim 期间推进，窗口为零。
                try:
                    db.refresh(task)
                    _calculate_next_run_at(task)
                    db.commit()
                except Exception as exc:
                    db.rollback()
                    logger.warning(f"Auto task {task.id} next-run reschedule failed: {exc}")
                    # review P1：排期推进失败时 next_run_at 会滞留在过去，若继续 active
                    # 就会每个 tick 重复执行（等于重复发布）。这里直接暂停任务并通知用户。
                    try:
                        stale = db.get(AutoTask, task.id)
                        if stale is not None:
                            stale.status = "paused"
                            stale.next_run_at = None
                            db.commit()
                            _record_auto_task_failure(
                                db, stale, f"排期计算失败，已自动暂停: {exc}"
                            )
                    except Exception:
                        db.rollback()
                        logger.exception(f"Auto task {task.id} pause after reschedule failure failed")
                _release_auto_task_claim(db, task.id)
    except Exception as exc:
        db.rollback()
        logger.error(f"run_due_auto_tasks failed: {exc}")
    finally:
        db.close()


def _is_auth_failure(exc: Exception) -> bool:
    """区分认证失败与网络/上游错误（BE-5）。

    认证失败（登录态失效）才把账号标记为 expired；网络抖动保留原状态。
    """
    text = str(exc).lower()
    # review P2-8：去掉过宽的 "cookie" 标记——网络错误信息里出现 cookie 字样
    # 不代表登录态失效，误判会批量置 expired 并轰炸通知
    auth_markers = (
        "401", "403", "unauthorized", "forbidden", "login", "auth",
        "登录", "未登录", "失效", "过期", "权限", "invalid session",
        "web_session",
    )
    network_markers = ("timeout", "timed out", "connection", "network", "dns", "ssl", "proxy", "超时", "网络")
    if any(marker in text for marker in network_markers) and not any(marker in text for marker in ("登录", "login", "auth", "失效")):
        return False
    return any(marker in text for marker in auth_markers)


def _check_single_account(db: Session, account: PlatformAccount, now: datetime) -> str:
    """Check one account's cookie validity. Returns the new status."""
    from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
    from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
    from backend.app.services.account_service import decode_cookie_text

    cookie_version = db.scalars(
        select(AccountCookieVersion)
        .where(AccountCookieVersion.platform_account_id == account.id)
        .order_by(AccountCookieVersion.created_at.desc())
    ).first()
    if cookie_version is None:
        old_status = account.status
        account.status = "expired"
        account.status_message = "No stored cookie version"
        account.updated_at = now
        # 返回旧状态，调用方据此判断是否需要发“新过期”通知
        return old_status

    adapter = XhsCreatorLoginAdapter() if account.sub_type == "creator" else XhsPcLoginAdapter()
    try:
        cookies_text = decrypt_text(cookie_version.encrypted_cookies)
        adapter.get_user_info(decode_cookie_text(cookies_text))
        old_status = account.status
        account.status = "active"
        account.status_message = ""
        account.updated_at = now
        return old_status
    except Exception as exc:
        old_status = account.status
        if _is_auth_failure(exc):
            # 仅认证失败才置 expired（BE-5）：网络抖动不应批量制造“过期”
            account.status = "expired"
            account.status_message = str(exc)[:300]
        else:
            # 网络错误：保留原状态，仅记录最近一次错误信息
            account.status_message = f"网络错误（状态保持 {account.status or 'unknown'}）: {exc}"[:300]
        account.updated_at = now
        return old_status


def check_all_account_cookies_once() -> None:
    """Scheduled job: check every account cookie, update status, notify on expiry."""
    db = SessionLocal()
    try:
        now = shanghai_now()
        # BE-5：只检查 XHS 账号——适配器只实现了 xhs 的登录态校验
        accounts = db.scalars(
            select(PlatformAccount)
            .where(PlatformAccount.platform == "xhs")
            .order_by(PlatformAccount.id.asc())
        ).all()
        checked = 0
        newly_expired = 0
        for account in accounts:
            try:
                old_status = _check_single_account(db, account, now)
                checked += 1
                if account.status == "expired" and old_status != "expired":
                    newly_expired += 1
                    db.add(Notification(
                        user_id=account.user_id,
                        title="账号 Cookie 过期",
                        body=f"账号「{account.nickname or account.external_user_id or account.id}」({account.sub_type or 'pc'}) Cookie 已失效，请重新绑定。",
                        level="warning",
                    ))
            except Exception as exc:
                logger.warning(f"Cookie check failed for account {account.id}: {exc}")
        db.commit()
        logger.info(f"Cookie check completed: {checked} accounts checked, {newly_expired} newly expired")
    except Exception as exc:
        logger.error(f"check_all_account_cookies_once failed: {exc}")
    finally:
        db.close()


def run_reconcile_once() -> None:
    """周期对账：复位进程崩溃/挂死时滞留在 publishing/uploading 的任务。"""
    try:
        publish_result = reconcile_stale_publish_jobs()
        from backend.app.douyin.publishing import reconcile_stale_tasks

        task_reset = reconcile_stale_tasks() or 0
        if publish_result.get("reset_publish_jobs") or task_reset:
            logger.info(
                "周期对账完成: publish_jobs=%s, douyin_tasks=%s",
                publish_result,
                task_reset,
            )
    except Exception as exc:
        logger.error(f"run_reconcile_once failed: {exc}")


def _run_sqlite_backup() -> None:
    from backend.app.services.backup import run_sqlite_backup_once

    try:
        run_sqlite_backup_once()
    except Exception as exc:
        logger.error(f"sqlite backup failed: {exc}")


def _run_media_prune() -> None:
    from backend.app.services.media_cleanup import run_media_prune_once

    try:
        run_media_prune_once()
    except Exception as exc:
        logger.error(f"media prune failed: {exc}")


def build_due_publish_scheduler(interval_seconds: int, job_func, monitoring_job_func=None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        job_func,
        "interval",
        seconds=interval_seconds,
        id="due_publish_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # max_instances=1 只对同一 job id 生效；未传监控函数时不得把发布函数
    # 再注册成第二个 id，否则两条 job 会并发执行同一逻辑。
    if monitoring_job_func is not None:
        scheduler.add_job(
            monitoring_job_func,
            "interval",
            seconds=interval_seconds,
            id="monitoring_refresh_runner",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        run_due_auto_tasks,
        "interval",
        seconds=60,
        id="auto_tasks_runner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        check_all_account_cookies_once,
        "interval",
        hours=2,
        id="cookie_health_checker",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # review P2：滞留任务对账此前只在进程启动时跑一次，长驻进程里卡死的发布任务
    # 要等到下次重启才恢复。改为周期对账（阈值 30 分钟，不会误伤正在执行的任务）。
    scheduler.add_job(
        run_reconcile_once,
        "interval",
        minutes=10,
        id="stale_task_reconciler",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # 媒体目录按年龄 + 容量周期清理，避免磁盘只增不减
    scheduler.add_job(
        _run_media_prune,
        "interval",
        hours=6,
        id="media_pruner",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # SQLite 每日在线备份（非 SQLite 后端自动跳过）
    scheduler.add_job(
        _run_sqlite_backup,
        "interval",
        hours=24,
        id="sqlite_backup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    return scheduler


def start_due_publish_scheduler(interval_seconds: int) -> BackgroundScheduler:
    scheduler = build_due_publish_scheduler(
        interval_seconds=interval_seconds,
        job_func=run_due_publish_jobs_once,
        monitoring_job_func=run_monitoring_refresh_once,
    )
    scheduler.start()
    return scheduler


def shutdown_due_publish_scheduler(scheduler: Optional[BackgroundScheduler]) -> None:
    if scheduler is not None and scheduler.running:
        scheduler.shutdown(wait=False)
