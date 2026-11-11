"""媒体素材来源校验。

发布/上传链路接受三种素材来源：
1. http(s) URL —— 仅允许配置白名单内的平台 CDN 域名（防 SSRF）；
2. ``/api/files/media/<file_name>`` —— 平台媒体目录内的文件；
3. 纯文件名 —— 同样解析到平台媒体目录。

绝对路径、带 ``..``/分隔符/盘符的路径一律拒绝（防任意文件读取）。
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

MEDIA_URL_PATH_PREFIX = "/api/files/media/"


class InvalidMediaSource(ValueError):
    """素材来源不合法（路径越界或域名不在白名单）。"""


def _allowed_host_suffixes() -> tuple[str, ...]:
    from backend.app.core.config import get_settings

    raw = getattr(get_settings(), "media_url_allowed_hosts", "") or ""
    suffixes = tuple(h.strip().lower() for h in raw.split(",") if h.strip())
    return suffixes or ("xhscdn.com", "xiaohongshu.com")


def _host_allowed(host: str) -> bool:
    host = (host or "").lower()
    if not host:
        return False
    return any(host == s or host.endswith("." + s) for s in _allowed_host_suffixes())


def validate_media_file_name(name: str) -> str:
    """校验纯文件名：不允许任何路径成分。"""
    if not name or not name.strip():
        raise InvalidMediaSource("媒体文件名不能为空")
    stripped = name.strip()
    if (
        Path(stripped).name != stripped
        or ".." in stripped
        or "/" in stripped
        or "\\" in stripped
        or ":" in stripped
    ):
        raise InvalidMediaSource(f"非法的媒体文件名: {name!r}")
    return stripped


_OWNED_MEDIA_RE = re.compile(r"^xhs-[a-z]+-u(\d+)-")


def assert_owned_media_name(name: str, user_id: int) -> str:
    """校验媒体文件名属于当前用户（文件名必须携带 xhs-*-u{user_id}- 前缀）。

    防止用户 A 通过裸文件名引用用户 B 已上传的媒体（跨用户读文件）。
    """
    stripped = validate_media_file_name(name)
    match = _OWNED_MEDIA_RE.match(stripped)
    if match is None or int(match.group(1)) != int(user_id):
        raise InvalidMediaSource(f"媒体文件不属于当前用户: {stripped[:64]}")
    return stripped


def validate_media_source(file_path: str) -> None:
    """校验发布素材来源；不合法时抛 InvalidMediaSource。"""
    if not file_path or not file_path.strip():
        raise InvalidMediaSource("素材路径不能为空")
    fp = file_path.strip()

    if fp.startswith(("http://", "https://")):
        parsed = urlparse(fp)
        if parsed.scheme not in ("http", "https"):
            raise InvalidMediaSource(f"不支持的素材协议: {parsed.scheme!r}")
        if not _host_allowed(parsed.hostname):
            raise InvalidMediaSource(
                f"素材 URL 域名不在白名单内: {parsed.hostname or '(空)'}"
            )
        return

    if fp.startswith(MEDIA_URL_PATH_PREFIX):
        validate_media_file_name(fp[len(MEDIA_URL_PATH_PREFIX):])
        return

    # 其余情况一律视为媒体目录内的纯文件名
    validate_media_file_name(fp)


def validate_owned_media_source(source: str, user_id: int) -> str:
    """素材来源校验 + 本地文件名归属校验（SEC-2 跨用户隔离）。

    URL 形态只做白名单校验；本地文件名（含 /api/files/media/ 前缀形态）
    还必须属于当前用户。校验失败抛 InvalidMediaSource。
    """
    fp = source.strip()
    validate_media_source(fp)
    if fp.startswith(("http://", "https://")):
        return fp
    if fp.startswith(MEDIA_URL_PATH_PREFIX):
        assert_owned_media_name(fp[len(MEDIA_URL_PATH_PREFIX):], user_id)
    else:
        assert_owned_media_name(fp, user_id)
    return fp
