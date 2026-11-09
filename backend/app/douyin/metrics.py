"""指标服务：作品互动数据快照。

语义（设计规范 D1）：
- 每个字段独立可空：真实 0 保留 0，平台未返回为 None（不伪造 0）；
- availability: available（本次真实获取）/ unsupported（上游无该字段能力）；
- 刷新错误不污染最近一次成功快照：失败时抛错，由 API 层返回错误信息。
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import shanghai_now
from backend.app.douyin import accounts as accounts_service
from backend.app.douyin import references as references_service
from backend.app.douyin.contracts import DouyinAdapter, WorkStats
from backend.app.douyin.models import DouyinAccount, DouyinMetricSnapshot, DouyinReferenceWork


def _insert_snapshot(
    db: Session, user_id: int, reference_id: int, stats: WorkStats,
    availability: str = "available",
) -> DouyinMetricSnapshot:
    row = DouyinMetricSnapshot(
        user_id=user_id,
        reference_work_id=reference_id,
        digg_count=stats.digg_count,
        comment_count=stats.comment_count,
        share_count=stats.share_count,
        collect_count=stats.collect_count,
        availability=availability,
        collected_at=shanghai_now(),
    )
    db.add(row)
    return row


def refresh_reference(
    db: Session, user_id: int, reference: DouyinReferenceWork,
    account: DouyinAccount, adapter: DouyinAdapter,
) -> DouyinMetricSnapshot:
    """用采集接口刷新单个参考作品的指标；参考行更新与快照同一事务。"""
    cookie = accounts_service.account_cookie(account)
    snapshot = adapter.crawl_work(cookie, reference.work_url)
    if snapshot.provider_work_id and snapshot.provider_work_id != reference.provider_work_id:
        raise ValueError("采集到的作品 ID 与参考记录不一致")
    # 同步刷新参考行上的采集数据（保留用户 tags/note），与快照同一事务提交
    stored = references_service.upsert_from_snapshot(
        db, user_id, snapshot, account.id, commit=False
    )
    row = _insert_snapshot(
        db, user_id, stored.id,
        WorkStats(
            digg_count=snapshot.stats.digg_count,
            comment_count=snapshot.stats.comment_count,
            share_count=snapshot.stats.share_count,
            collect_count=snapshot.stats.collect_count,
        ),
    )
    db.commit()
    db.refresh(row)
    return row


def refresh_account_works(
    db: Session, user_id: int, account: DouyinAccount, adapter: DouyinAdapter,
    max_pages: int = 3,
) -> list[DouyinMetricSnapshot]:
    """拉取账号作品列表：新作品入库参考库+快照，整批同一事务。"""
    cookie = accounts_service.account_cookie(account)
    sec_uid = account.provider_account_id
    if not sec_uid:
        raise ValueError("账号缺少平台身份，请先重新授权确认")
    snapshots = adapter.list_own_works(cookie, sec_uid, max_pages=max_pages)
    created: list[DouyinMetricSnapshot] = []
    for item in snapshots:
        if not item.provider_work_id:
            continue
        reference = references_service.upsert_from_snapshot(
            db, user_id, item, account.id, commit=False
        )
        created.append(_insert_snapshot(db, user_id, reference.id, item.stats))
    db.commit()
    return created


def serialize_snapshot(row: DouyinMetricSnapshot) -> dict:
    return {
        "id": row.id,
        "reference_work_id": row.reference_work_id,
        "digg_count": row.digg_count,
        "comment_count": row.comment_count,
        "share_count": row.share_count,
        "collect_count": row.collect_count,
        "availability": row.availability,
        "collected_at": row.collected_at.isoformat() if row.collected_at else None,
    }


def latest_metrics_map(db: Session, user_id: int, reference_ids: list[int]) -> dict[int, dict]:
    """每个参考作品最近一次快照（无快照的键不存在，前端展示 not_collected）。"""
    result: dict[int, dict] = {}
    if not reference_ids:
        return result
    rows = db.scalars(
        select(DouyinMetricSnapshot)
        .where(
            DouyinMetricSnapshot.user_id == user_id,
            DouyinMetricSnapshot.reference_work_id.in_(reference_ids),
        )
        .order_by(DouyinMetricSnapshot.reference_work_id, DouyinMetricSnapshot.id)
    )
    for row in rows:
        result[row.reference_work_id] = serialize_snapshot(row)  # 后写覆盖 → 最新
    return result


def work_stats_from_reference(work: DouyinReferenceWork) -> dict:
    """参考行上采集时的 stats（采集时点，不替代快照）。"""
    data = json.loads(work.stats_json or "{}")
    return data
