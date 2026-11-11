from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.media_source import InvalidMediaSource, assert_owned_media_name
from backend.app.core.media_storage import media_dir
from backend.app.models import AiDraft, DraftAsset, Note, NoteAsset

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac"}


def asset_type_for(name: str) -> Optional[str]:
    ext = Path(name).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


def _existing_owned(name: str, user_id: int) -> Optional[tuple[str, int]]:
    """文件名归属校验 + 存在性校验；合法返回 (name, size)。"""
    try:
        assert_owned_media_name(name, user_id)
    except InvalidMediaSource:
        return None
    path = media_dir() / name
    if not path.is_file():
        return None
    return name, path.stat().st_size


def list_clip_assets(
    db: Session,
    user_id: int,
    *,
    q: str = "",
    asset_type: str = "",
    source: str = "",
    limit: int = 200,
) -> list[dict]:
    """聚合三类素材来源（内容库/草稿/本地上传），统一做归属与存在性过滤。"""
    needle = q.strip().lower()
    limit = max(1, min(int(limit), 200))
    items: dict[str, dict] = {}

    def add(name: str, kind: str, ref_id: str, title: str) -> None:
        checked = _existing_owned(name, user_id)
        if checked is None or name in items:
            return
        detected = asset_type_for(name)
        if detected is None:
            return
        if asset_type and detected != asset_type:
            return
        display = (title or name).strip()
        if needle and needle not in display.lower() and needle not in name.lower():
            return
        items[name] = {
            "id": f"{kind}:{ref_id}",
            "kind": kind,
            "ref_id": ref_id,
            "file_name": name,
            "asset_type": detected,
            "source": "note" if kind == "note_asset" else "draft" if kind == "draft_asset" else "upload",
            "title": display,
            "size_bytes": checked[1],
            "preview_url": f"/api/files/media/{name}",
        }

    if source in ("", "note"):
        rows = db.execute(
            select(NoteAsset, Note)
            .join(Note, Note.id == NoteAsset.note_id)
            .where(Note.user_id == user_id)
            .order_by(NoteAsset.id.desc())
        ).all()
        for asset, note in rows:
            add(Path(asset.local_path or "").name, "note_asset", str(asset.id), note.title)

    if source in ("", "draft"):
        rows = db.execute(
            select(DraftAsset, AiDraft)
            .join(AiDraft, AiDraft.id == DraftAsset.draft_id)
            .where(AiDraft.user_id == user_id)
            .order_by(DraftAsset.id.desc())
        ).all()
        for asset, draft in rows:
            add(Path(asset.local_path or "").name, "draft_asset", str(asset.id), draft.title)

    if source in ("", "upload"):
        directory = media_dir()
        if directory.is_dir():
            prefixes = (f"xhs-upload-u{user_id}-", f"xhs-image-u{user_id}-")
            # os.scandir：entry.stat() 复用目录枚举时的属性缓存，
            # 避免对每个文件额外一次 stat 系统调用（files.py 同款优化）
            import os

            try:
                with os.scandir(directory) as iterator:
                    for entry in iterator:
                        if entry.name.startswith(prefixes) and entry.is_file():
                            add(entry.name, "upload", entry.name, "")
            except OSError:
                return list(items.values())[:limit]

    return list(items.values())[:limit]


def resolve_clip_asset(
    db: Session,
    user_id: int,
    *,
    kind: str,
    ref_id: Optional[int] = None,
    file_name: Optional[str] = None,
) -> tuple[str, int]:
    """把选择项解析为归属当前用户且存在的媒体文件名。"""
    if kind == "note_asset" and ref_id is not None:
        asset = db.get(NoteAsset, ref_id)
        note = db.get(Note, asset.note_id) if asset else None
        name = Path(asset.local_path or "").name if asset and note and note.user_id == user_id else ""
    elif kind == "draft_asset" and ref_id is not None:
        asset = db.get(DraftAsset, ref_id)
        draft = db.get(AiDraft, asset.draft_id) if asset else None
        name = Path(asset.local_path or "").name if asset and draft and draft.user_id == user_id else ""
    elif kind == "upload" and file_name:
        name = Path(file_name).name
    else:
        raise InvalidMediaSource("无效的素材选择")

    if not name:
        raise InvalidMediaSource("素材不存在或不属于当前用户")
    checked = _existing_owned(name, user_id)
    if checked is None:
        raise InvalidMediaSource("素材不存在或不属于当前用户")
    return checked
