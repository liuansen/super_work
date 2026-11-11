"""媒体文件路径解析（单一入口）。

此前有 7 处各自拼 ``storage_dir / "media"``，任何目录结构调整都要全仓搜索。
集中到这里后，未来按用户分片（``media/u{id}/``）只需改这一个函数。

注意：所有对外 URL 仍是 ``/api/files/media/<file_name>``，文件名本身携带
``xhs-<kind>-u{user_id}-`` 前缀，归属校验在 core/media_source.py。
"""
from __future__ import annotations

from pathlib import Path


def media_dir() -> Path:
    from backend.app.core.config import get_settings

    return Path(get_settings().storage_dir) / "media"


def media_path(file_name: str) -> Path:
    """文件名 → 绝对路径（只接受纯文件名，调用方须先校验归属）。"""
    return media_dir() / file_name


def media_url(file_name: str) -> str:
    from backend.app.core.media_source import MEDIA_URL_PATH_PREFIX

    return f"{MEDIA_URL_PATH_PREFIX}{file_name}"
