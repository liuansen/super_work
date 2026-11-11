"""真实抖音适配器：包装 vendor/DouYin_Spider 固定快照。

本文件是业务代码与上游之间唯一的调用边界：
- 输入输出只用 contracts 的规范化类型，不向上游泄漏业务对象；
- 上游异常统一翻译为 contracts 的错误分类；
- 上游原始 dict 只保存在 WorkSnapshot.raw / PublishOutcome.result_raw 中。
"""
from __future__ import annotations

import re
from typing import Any, Optional

from backend.app.douyin import upstream
from backend.app.douyin.contracts import (
    AccountIdentity,
    DouyinAdapterError,
    DouyinAuthError,
    DouyinNetworkError,
    DouyinUpstreamError,
    PublishOutcome,
    WorkSnapshot,
    WorkStats,
)

_AWEME_ID_RE = re.compile(r"(\d{6,32})")


def _wrap(error: Exception, action: str) -> Exception:
    """把任意上游异常翻译为契约错误。网络/超时类必须与业务类区分开。"""
    text = str(error)
    lowered = text.lower()
    network_markers = ("timeout", "timed out", "connection", "getaddrinfo", "ssl", "proxy", "unreachable")
    if any(marker in lowered for marker in network_markers):
        return DouyinNetworkError(f"{action} 网络失败（结果未知）: {text}")
    if "cookie" in lowered or "登录" in text or "uifid" in lowered:
        return DouyinAuthError(f"{action} 凭证失效: {text}")
    return DouyinUpstreamError(f"{action} 上游异常: {text}")


def _pick_int(source: dict, *keys: str) -> Optional[int]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _first_url(source: Any) -> str:
    """上游封面/播放地址常见 url_list 嵌套，取第一个。"""
    if isinstance(source, dict):
        urls = source.get("url_list")
        if isinstance(urls, list) and urls and isinstance(urls[0], str):
            return urls[0]
        for value in source.values():
            found = _first_url(value)
            if found:
                return found
    if isinstance(source, list):
        for item in source:
            found = _first_url(item)
            if found:
                return found
    return ""


def normalize_work(raw: dict, work_url: str = "") -> WorkSnapshot:
    """把上游 aweme dict 规范化为 WorkSnapshot；字段缺失保持 None/空串。

    上游 create_time 为 Unix 秒，统一换算为毫秒（与字段名 publish_time_ms 一致）。
    """
    stats_raw = raw.get("statistics") if isinstance(raw.get("statistics"), dict) else {}
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    video = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    duration = _pick_int(video, "duration")
    create_time = _pick_int(raw, "create_time")
    return WorkSnapshot(
        provider_work_id=str(raw.get("aweme_id") or raw.get("aid") or ""),
        title=str(raw.get("desc") or ""),
        cover_url=_first_url(video.get("cover") or raw.get("image_infos") or ""),
        author_nickname=str(author.get("nickname") or ""),
        author_sec_uid=str(author.get("sec_uid") or ""),
        work_url=work_url or (f"https://www.douyin.com/video/{raw.get('aweme_id')}" if raw.get("aweme_id") else ""),
        duration_ms=duration,
        publish_time_ms=create_time * 1000 if create_time is not None else None,
        stats=WorkStats(
            digg_count=_pick_int(stats_raw, "digg_count"),
            comment_count=_pick_int(stats_raw, "comment_count"),
            share_count=_pick_int(stats_raw, "share_count"),
            collect_count=_pick_int(stats_raw, "collect_count"),
        ),
        raw=raw,
    )


def extract_provider_work_id(result: Optional[dict]) -> Optional[str]:
    """从 create_v2 响应中尽力提取作品 ID；取不到保持 None（不编造）。"""
    if not isinstance(result, dict):
        return None
    for key in ("aweme_id", "item_id", "aweme_id_str"):
        value = result.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    data = result.get("data")
    if isinstance(data, dict):
        return extract_provider_work_id(data)
    return None


class RealDouyinAdapter:
    """调用 vendor 上游的真实适配器（经子进程隔离）。

    所有上游调用都走 ``upstream.call_vendor``：vendor 代码在独立进程里执行，
    崩溃/线程污染不会影响 backend，且每个操作都有硬性超时。
    规范化（normalize_work）仍在父进程，便于单元测试。
    """

    name = "real"

    @staticmethod
    def _require_cookie(cookie: str, action: str) -> str:
        if not cookie or not cookie.strip():
            raise DouyinAuthError(f"{action} 缺少 Cookie")
        return cookie.strip()

    def _call(self, op: str, payload: dict, action: str) -> dict:
        """执行上游调用并把子进程错误翻译成契约错误。"""
        try:
            return upstream.call_vendor(op, payload)
        except upstream.VendorCallTimeout as exc:
            # 超时属于「结果未知」：归为网络类，发布链路不会自动重发
            raise DouyinNetworkError(f"{action} 超时，结果未知: {exc}") from exc
        except upstream.VendorCallFailed as exc:
            if exc.kind == "auth":
                raise DouyinAuthError(f"{action} 凭证失效: {exc}") from exc
            if exc.kind == "network":
                raise DouyinNetworkError(f"{action} 网络失败: {exc}") from exc
            raise _wrap(exc, action) from exc

    def check_account(self, cookie: str) -> AccountIdentity:
        cookie = self._require_cookie(cookie, "身份确认")
        result = self._call("check_account", {"cookie": cookie}, "身份确认")
        sec_uid = str(result.get("sec_uid") or "")
        if not sec_uid:
            raise DouyinAuthError("身份确认：上游未返回 sec_uid，Cookie 可能已失效")
        info = result.get("info") or {}
        profile: dict = {}
        if isinstance(info, dict):
            candidate = info.get("user")
            profile = candidate if isinstance(candidate, dict) else info
        return AccountIdentity(
            provider_account_id=sec_uid,
            nickname=str(profile.get("nickname") or ""),
            avatar_url=_first_url(profile.get("avatar_thumb")),
            raw=info if isinstance(info, dict) else {},
        )

    def crawl_work(self, cookie: str, url: str) -> WorkSnapshot:
        cookie = self._require_cookie(cookie, "作品采集")
        # URL 会被上游用作请求头（Referer）：提前拒绝控制字符/空白，杜绝头注入面。
        if not url or any(ord(ch) < 33 for ch in url):
            raise DouyinUpstreamError("作品链接包含非法字符")
        if not _AWEME_ID_RE.search(url):
            raise DouyinUpstreamError(f"无法从链接解析作品 ID: {url}")
        result = self._call("crawl_work", {"cookie": cookie, "url": url}, "作品采集")
        raw = result.get("raw") or {}
        detail = raw.get("aweme_detail") if isinstance(raw, dict) else None
        if not isinstance(detail, dict) or not detail.get("aweme_id"):
            raise DouyinUpstreamError(f"作品不存在或已删除: {url}")
        return normalize_work(detail, work_url=url)

    def list_own_works(self, cookie: str, sec_uid: str, max_pages: int = 3) -> list[WorkSnapshot]:
        cookie = self._require_cookie(cookie, "作品列表")
        result = self._call(
            "list_own_works",
            {"cookie": cookie, "sec_uid": sec_uid, "max_pages": max(1, int(max_pages))},
            "作品列表",
        )
        items = result.get("items") or []
        return [normalize_work(item) for item in items if isinstance(item, dict)]

    def publish_video(
        self, cookie: str, video_path: str, *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        cookie = self._require_cookie(cookie, "视频发布")
        result = self._call(
            "publish_video",
            {
                "cookie": cookie,
                "path": video_path,
                "title": title,
                "desc": desc,
                "visibility": int(visibility),
                "allow_download": bool(allow_download),
                "timing": timing,
            },
            "视频发布",
        )
        return PublishOutcome(
            ok=bool(result.get("ok")),
            message=str(result.get("message") or ""),
            provider_work_id=extract_provider_work_id(result.get("result") or {}),
            result_raw=result.get("result") if isinstance(result.get("result"), dict) else {},
        )

    def publish_images(
        self, cookie: str, image_paths: list[str], *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        cookie = self._require_cookie(cookie, "图集发布")
        result = self._call(
            "publish_images",
            {
                "cookie": cookie,
                "paths": list(image_paths),
                "title": title,
                "desc": desc,
                "visibility": int(visibility),
                "allow_download": bool(allow_download),
                "timing": timing,
            },
            "图集发布",
        )
        return PublishOutcome(
            ok=bool(result.get("ok")),
            message=str(result.get("message") or ""),
            provider_work_id=extract_provider_work_id(result.get("result") or {}),
            result_raw=result.get("result") if isinstance(result.get("result"), dict) else {},
        )
