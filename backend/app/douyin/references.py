"""参考作品库服务：采集入库、列表、用户标签与备注。

幂等：同一用户同一 provider_work_id 只有一行；重复采集保留用户标签/备注，
仅刷新平台数据。
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.douyin.contracts import WorkSnapshot
from backend.app.douyin.models import DouyinReferenceWork


def serialize_reference(work: DouyinReferenceWork, latest_metrics: Optional[dict] = None) -> dict:
    data = {
        "id": work.id,
        "provider_work_id": work.provider_work_id,
        "work_url": work.work_url,
        "title": work.title,
        "cover_url": work.cover_url,
        "author_nickname": work.author_nickname,
        "author_sec_uid": work.author_sec_uid,
        "duration_ms": work.duration_ms,
        "publish_time_ms": work.publish_time_ms,
        "stats": json.loads(work.stats_json or "{}"),
        "tags": json.loads(work.tags_json or "[]"),
        "note": work.note,
        "collected_at": work.collected_at.isoformat() if work.collected_at else None,
    }
    if latest_metrics is not None:
        data["latest_metrics"] = latest_metrics
    return data


def get_owned_reference(
    db: Session, user_id: int, reference_id: int
) -> Optional[DouyinReferenceWork]:
    return db.scalar(
        select(DouyinReferenceWork).where(
            DouyinReferenceWork.id == reference_id,
            DouyinReferenceWork.user_id == user_id,
        )
    )


def list_references(
    db: Session, user_id: int, keyword: str = "", tag: str = "", limit: int = 200
) -> list[DouyinReferenceWork]:
    stmt = (
        select(DouyinReferenceWork)
        .where(DouyinReferenceWork.user_id == user_id)
        .order_by(DouyinReferenceWork.id.desc())
    )
    # review 复核 P2：过滤必须发生在 limit 之前——先截断再过滤会让
    # 「只命中被截断掉的旧记录」的关键词永远搜不到（语义上是搜不到而非不存在）。
    # keyword 下推 SQL LIKE；tag 是受控 JSON 数组（元素为不含转义引号的
    # 纯文本标签），用 `"tag"` 子串匹配等价于元素相等。
    if keyword:
        # LIKE 通配符转义，保持与原「子串包含」语义一致
        escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(DouyinReferenceWork.title.ilike(f"%{escaped}%", escape="\\"))
    if tag:
        stmt = stmt.where(DouyinReferenceWork.tags_json.contains(json.dumps(tag, ensure_ascii=False)))
    stmt = stmt.limit(limit)
    rows = list(db.scalars(stmt))
    # tag 的 LIKE 匹配是超集（子串撞名），Python 精筛保证最终结果准确
    if tag:
        rows = [r for r in rows if tag in json.loads(r.tags_json or "[]")]
    return rows


def upsert_from_snapshot(
    db: Session, user_id: int, snapshot: WorkSnapshot, account_id: Optional[int],
    commit: bool = True,
) -> DouyinReferenceWork:
    """采集入库；重复采集保留用户标签/备注，刷新平台字段。

    commit=False 供调用方把"参考行更新+指标快照"放进同一事务。
    """
    existing = db.scalar(
        select(DouyinReferenceWork).where(
            DouyinReferenceWork.user_id == user_id,
            DouyinReferenceWork.provider_work_id == snapshot.provider_work_id,
        )
    )
    if existing is None:
        existing = DouyinReferenceWork(
            user_id=user_id,
            provider_work_id=snapshot.provider_work_id,
            tags_json="[]",
            note="",
        )
        db.add(existing)
    existing.work_url = snapshot.work_url or existing.work_url
    existing.title = snapshot.title or existing.title
    existing.cover_url = snapshot.cover_url or existing.cover_url
    existing.author_nickname = snapshot.author_nickname or existing.author_nickname
    existing.author_sec_uid = snapshot.author_sec_uid or existing.author_sec_uid
    existing.duration_ms = snapshot.duration_ms if snapshot.duration_ms is not None else existing.duration_ms
    existing.publish_time_ms = (
        snapshot.publish_time_ms if snapshot.publish_time_ms is not None else existing.publish_time_ms
    )
    existing.stats_json = json.dumps(
        {
            "digg_count": snapshot.stats.digg_count,
            "comment_count": snapshot.stats.comment_count,
            "share_count": snapshot.stats.share_count,
            "collect_count": snapshot.stats.collect_count,
        },
        ensure_ascii=False,
    )
    existing.raw_json = json.dumps(snapshot.raw, ensure_ascii=False, default=str)
    existing.source_account_id = account_id if account_id is not None else existing.source_account_id
    existing.collected_at = shanghai_now()
    if commit:
        db.commit()
        db.refresh(existing)
    else:
        # 不提交时也要 flush：保证新建行拿到主键，供同事务内的快照外键引用。
        db.flush()
    return existing


def update_user_fields(
    db: Session, user_id: int, reference_id: int, *, tags: Optional[list[str]] = None,
    note: Optional[str] = None,
) -> Optional[DouyinReferenceWork]:
    work = get_owned_reference(db, user_id, reference_id)
    if work is None:
        return None
    if tags is not None:
        work.tags_json = json.dumps([str(t) for t in tags], ensure_ascii=False)
    if note is not None:
        work.note = str(note)
    db.commit()
    db.refresh(work)
    return work


def snapshot_to_dict(snapshot: WorkSnapshot) -> dict:
    """采集当次返回给前端的规范化数据（不落库 raw）。"""
    return {
        "provider_work_id": snapshot.provider_work_id,
        "title": snapshot.title,
        "cover_url": snapshot.cover_url,
        "author_nickname": snapshot.author_nickname,
        "work_url": snapshot.work_url,
        "publish_time_ms": snapshot.publish_time_ms,
        "stats": {
            "digg_count": snapshot.stats.digg_count,
            "comment_count": snapshot.stats.comment_count,
            "share_count": snapshot.stats.share_count,
            "collect_count": snapshot.stats.collect_count,
        },
        "collected_at": shanghai_now().isoformat(timespec="seconds"),
    }
