"""外链素材安全下载器（SEC-3）。

约束：
1. 仅 http/https，且域名必须在 ``media_url_allowed_hosts`` 白名单内；
2. 出站前做 DNS 解析，拒绝解析到私网/回环/链路本地/多播/保留地址的目标
   （防 DNS rebinding 与"白名单域名指向内网 IP"的绕过）；
3. 重定向不自动跟随：每一跳重新执行完整校验，最多跟随 3 跳；
4. 流式下载，单文件字节上限（图片 20MB / 视频 300MB，可配置），
   超限立即中止并删除临时文件；先写临时文件再原子重命名；
5. Content-Type 校验：拒绝 text/html 等页面响应，防止把内网页面当图片落盘。
"""
from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from loguru import logger

from backend.app.core.config import get_settings

DEFAULT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_VIDEO_MAX_BYTES = 300 * 1024 * 1024
MAX_REDIRECTS = 3
CHUNK_SIZE = 64 * 1024
# 拒绝的 Content-Type：HTML/文本页面（其余按扩展名白名单判断）
BLOCKED_CONTENT_TYPES = ("text/html", "application/xhtml", "text/plain")


class AssetDownloadRejected(Exception):
    """素材下载被安全策略拒绝。"""


def _host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    raw = getattr(get_settings(), "media_url_allowed_hosts", "") or ""
    suffixes = [s.strip().lower() for s in raw.split(",") if s.strip()]
    if not suffixes:
        # 与 core/media_source._allowed_host_suffixes 口径一致：空配置视为
        # 「未配置」回退默认白名单，而不是全部拒绝（两处此前表现矛盾）
        suffixes = ["xhscdn.com", "xiaohongshu.com"]
    return any(host == s or host.endswith("." + s) for s in suffixes)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_outbound_url(url: str) -> None:
    """校验出站 URL：协议、白名单、DNS 解析结果全部必须合法。

    不合法时抛 AssetDownloadRejected。
    """
    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise AssetDownloadRejected(f"URL 无法解析: {url[:120]}") from exc

    if parsed.scheme not in ("http", "https"):
        raise AssetDownloadRejected(f"不支持的协议: {parsed.scheme!r}")
    if not _host_allowed(url):
        raise AssetDownloadRejected(f"域名不在白名单内: {parsed.hostname or '(空)'}")

    host = parsed.hostname or ""
    try:
        addr_infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise AssetDownloadRejected(f"域名解析失败: {host}") from exc

    for info in addr_infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _is_public_ip(ip):
            raise AssetDownloadRejected(
                f"域名 {host} 解析到非公网地址 {ip}，已拒绝（防内网探测）"
            )


def _size_limit_for(asset_type: str) -> int:
    configured_image = int(
        getattr(get_settings(), "asset_download_image_max_bytes", 0) or DEFAULT_IMAGE_MAX_BYTES
    )
    configured_video = int(
        getattr(get_settings(), "asset_download_video_max_bytes", 0) or DEFAULT_VIDEO_MAX_BYTES
    )
    return configured_video if asset_type == "video" else configured_image


def _validate_content_type(content_type: str) -> None:
    ct = (content_type or "").lower().split(";")[0].strip()
    for blocked in BLOCKED_CONTENT_TYPES:
        if ct.startswith(blocked):
            raise AssetDownloadRejected(f"Content-Type 被拒绝: {ct}")


def _fetch_stream(url: str):
    import requests

    # allow_redirects=False：重定向必须逐跳重新校验，禁止直接跟随
    return requests.get(
        url,
        timeout=(10, 60),
        headers={"Referer": ""},
        allow_redirects=False,
        stream=True,
    )


def download_asset_to_local(url: str, user_id: int, asset_type: str) -> str | None:
    """下载素材到平台媒体目录；被安全策略拒绝或失败时返回 None。

    调用方（批量入库等）把 None 视为该项失败，继续处理剩余项。
    """
    try:
        return _download_impl(url, user_id, asset_type)
    except AssetDownloadRejected as exc:
        logger.warning(f"Asset download rejected: {exc} (url host only: {_safe_log_host(url)})")
        return None
    except Exception as exc:
        logger.warning(f"Asset download failed for {_safe_log_host(url)}: {exc}")
        return None


def _safe_log_host(url: str) -> str:
    """日志只记录 host（不含路径与查询串），避免泄露带签名的完整 URL。"""
    try:
        return urlparse(url).hostname or "(unparsable)"
    except ValueError:
        return "(unparsable)"


def _download_impl(url: str, user_id: int, asset_type: str) -> str | None:
    max_bytes = _size_limit_for(asset_type)
    current_url = url
    for _hop in range(MAX_REDIRECTS + 1):
        validate_outbound_url(current_url)
        resp = _fetch_stream(current_url)
        try:
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                resp.close()
                if not location:
                    return None
                current_url = _resolve_redirect(current_url, location)
                continue
            resp.raise_for_status()
            _validate_content_type(resp.headers.get("content-type", ""))
            return _stream_to_media_file(resp, user_id, asset_type, max_bytes)
        finally:
            resp.close()
    logger.warning(f"Asset download exceeded {MAX_REDIRECTS} redirects: {_safe_log_host(url)}")
    return None


def _resolve_redirect(base_url: str, location: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base_url, location)


def _stream_to_media_file(resp, user_id: int, asset_type: str, max_bytes: int) -> str | None:
    from backend.app.core.media_storage import media_dir as resolve_media_dir

    media_dir = resolve_media_dir()
    media_dir.mkdir(parents=True, exist_ok=True)

    ext = _guess_extension(
        str(resp.url),
        resp.headers.get("content-type", ""),
        asset_type,
    )
    file_name = f"xhs-asset-u{user_id}-{uuid4().hex}{ext}"
    final_path = media_dir / file_name

    total = 0
    tmp_fd, tmp_name = tempfile.mkstemp(dir=str(media_dir), prefix=".dl-", suffix=".part")
    try:
        with os.fdopen(tmp_fd, "wb") as out:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise AssetDownloadRejected(
                        f"文件超过大小上限 {max_bytes // (1024 * 1024)}MB，已中止"
                    )
                out.write(chunk)
        if total < 100:
            os.unlink(tmp_name)
            return None
        # 原子重命名：避免并发读者看到半成品文件
        os.replace(tmp_name, final_path)
        return file_name
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _guess_extension(url: str, content_type: str, asset_type: str) -> str:
    ct = content_type.lower()
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "png" in ct:
        return ".png"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    if "mp4" in ct:
        return ".mp4"
    if "quicktime" in ct or "mov" in ct:
        return ".mov"
    lower_url = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov"):
        if lower_url.endswith(ext):
            return ext
    return ".mp4" if asset_type == "video" else ".jpg"
