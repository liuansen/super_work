"""小红书领域对象的序列化/指标提取（纯函数）。

从 ``api/platforms/xhs/monitoring.py`` 下沉：monitoring 服务层此前需要
import API 层私有符号来构造快照 payload，依赖方向是反的。
"""
from __future__ import annotations

from typing import Any

from backend.app.models import MonitoringSnapshot, MonitoringTarget, Note


def serialize_target(target: MonitoringTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "platform": target.platform,
        "target_type": target.target_type,
        "name": target.name,
        "value": target.value,
        "status": target.status,
        "config": target.config or {},
        "last_refreshed_at": target.last_refreshed_at.isoformat() if target.last_refreshed_at else None,
        "created_at": target.created_at.isoformat(),
        "updated_at": target.updated_at.isoformat(),
        "platform_account_id": target.platform_account_id,
        "crawl_interval_minutes": target.crawl_interval_minutes,
        "consecutive_failures": target.consecutive_failures,
        "last_crawl_error": target.last_crawl_error,
    }


def serialize_snapshot(snapshot: MonitoringSnapshot) -> dict[str, Any]:
    return {
        "id": snapshot.id,
        "target_id": snapshot.target_id,
        "payload": snapshot.payload or {},
        "created_at": snapshot.created_at.isoformat(),
    }


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


def note_metrics(note: Note) -> dict[str, int]:
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


def serialize_monitoring_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "note_id": note.note_id,
        "title": note.title,
        "author_name": note.author_name,
        "created_at": note.created_at.isoformat(),
        **note_metrics(note),
    }
