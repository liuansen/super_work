"""笔记入库（normalized dict → Note + NoteAsset + 本地素材）。

从 ``api/platforms/xhs/crawl.py`` 下沉：调度器/监控服务此前要 import API
层的 ``_save_normalized_notes`` 私有函数，API 任何重构都会打断后台任务。
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models import Note, NoteAsset, PlatformAccount

logger = logging.getLogger(__name__)

# 单次入库的外链下载预算（与 notes.batch-save 同口径）
INGEST_MAX_DOWNLOADS = 200


def raw_with_metrics(normalized: dict[str, Any]) -> dict[str, Any]:
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    return {
        **raw,
        "note_url": normalized.get("note_url", ""),
        "tags": normalized.get("tags", []),
        "likes": normalized.get("likes", 0),
        "collects": normalized.get("collects", 0),
        "comments": normalized.get("comments", 0),
        "shares": normalized.get("shares", 0),
    }


def image_urls(normalized: dict[str, Any]) -> list[str]:
    urls = normalized.get("image_urls")
    if isinstance(urls, list) and urls:
        return [str(url) for url in urls if url]
    cover_url = normalized.get("cover_url")
    return [str(cover_url)] if cover_url else []


def video_url(normalized: dict[str, Any]) -> str:
    return str(normalized.get("video_url") or normalized.get("video_addr") or "")


def _download_asset(url: str, user_id: int, asset_type: str) -> str | None:
    from backend.app.services.asset_downloader import download_asset_to_local

    return download_asset_to_local(url, user_id, asset_type)


def save_normalized_notes(
    db: Session,
    account: PlatformAccount,
    normalized_items: list[dict[str, Any]],
    *,
    max_downloads: int = INGEST_MAX_DOWNLOADS,
) -> list[Note]:
    """把规范化条目写入内容库（重复 note_id 更新），素材下载受总预算约束。"""
    saved: list[Note] = []
    downloaded: list[str] = []
    attempts = 0

    def _download(url: str, asset_type: str) -> str | None:
        nonlocal attempts
        attempts += 1
        if attempts > max_downloads:
            return None
        name = _download_asset(url, account.user_id, asset_type)
        if name:
            downloaded.append(name)
        return name

    try:
        for normalized in normalized_items:
            note_id = str(normalized.get("note_id") or "").strip()
            if not note_id:
                continue
            note = db.scalars(
                select(Note).where(Note.user_id == account.user_id, Note.note_id == note_id)
            ).first()
            if note is None:
                note = Note(
                    user_id=account.user_id,
                    platform_account_id=account.id,
                    platform=account.platform,
                    note_id=note_id,
                )
                db.add(note)
            note.title = str(normalized.get("title") or "")
            note.content = str(normalized.get("content") or "")
            note.author_name = str(normalized.get("author_name") or "")
            note.raw_json = raw_with_metrics(normalized)
            db.flush()
            db.execute(delete(NoteAsset).where(NoteAsset.note_id == note.id))
            for url in image_urls(normalized):
                local_name = _download(url, "image")
                db.add(NoteAsset(note_id=note.id, asset_type="image", url=url, local_path=local_name or ""))
            video = video_url(normalized)
            if video:
                local_name = _download(video, "video")
                db.add(NoteAsset(note_id=note.id, asset_type="video", url=video, local_path=local_name or ""))
            saved.append(note)
        db.commit()
    except Exception:
        db.rollback()
        # 入库失败时清理本轮已落盘文件，避免 media 目录产生孤儿
        from pathlib import Path

        from backend.app.core.media_storage import media_dir
        for name in downloaded:
            try:
                (media_dir / name).unlink(missing_ok=True)
            except OSError:
                logger.warning("清理孤儿媒体文件失败: %s", name)
        raise

    for note in saved:
        db.refresh(note)
    return saved
