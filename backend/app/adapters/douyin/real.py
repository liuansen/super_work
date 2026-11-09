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
    """调用 vendor 上游的真实适配器。所有上游调用都在这里收口。"""

    name = "real"

    def _auth(self, cookie: str, action: str):
        if not cookie or not cookie.strip():
            raise DouyinAuthError(f"{action} 缺少 Cookie")
        try:
            return upstream.auth_from_cookie(cookie.strip())
        except DouyinAuthError:
            raise
        except Exception as error:  # 上游构造期异常种类不可枚举
            raise _wrap(error, action) from error

    def check_account(self, cookie: str) -> AccountIdentity:
        api = upstream.douyin_api_cls()
        auth = self._auth(cookie, "身份确认")
        try:
            sec_uid = api.get_my_sec_uid(auth)
            if not sec_uid:
                raise DouyinAuthError("身份确认：上游未返回 sec_uid，Cookie 可能已失效")
            info = api.get_user_info(auth, f"https://www.douyin.com/user/{sec_uid}")
        except DouyinAdapterError:
            raise
        except Exception as error:
            raise _wrap(error, "身份确认") from error
        profile: dict = {}
        if isinstance(info, dict):
            candidate = info.get("user")
            profile = candidate if isinstance(candidate, dict) else info
        nickname = str(profile.get("nickname") or "")
        avatar = _first_url(profile.get("avatar_thumb"))
        return AccountIdentity(
            provider_account_id=str(sec_uid),
            nickname=nickname,
            avatar_url=avatar,
            raw=info if isinstance(info, dict) else {},
        )

    def crawl_work(self, cookie: str, url: str) -> WorkSnapshot:
        api = upstream.douyin_api_cls()
        auth = self._auth(cookie, "作品采集")
        # URL 会被上游用作请求头（Referer）：提前拒绝控制字符/空白，杜绝头注入面。
        if not url or any(ord(ch) < 33 for ch in url):
            raise DouyinUpstreamError("作品链接包含非法字符")
        if not _AWEME_ID_RE.search(url):
            raise DouyinUpstreamError(f"无法从链接解析作品 ID: {url}")
        try:
            raw = api.get_work_info(auth, url)
        except DouyinAdapterError:
            raise
        except Exception as error:
            raise _wrap(error, "作品采集") from error
        detail = raw.get("aweme_detail") if isinstance(raw, dict) else None
        if not isinstance(detail, dict) or not detail.get("aweme_id"):
            raise DouyinUpstreamError(f"作品不存在或已删除: {url}")
        return normalize_work(detail, work_url=url)

    def list_own_works(self, cookie: str, sec_uid: str, max_pages: int = 3) -> list[WorkSnapshot]:
        api = upstream.douyin_api_cls()
        auth = self._auth(cookie, "作品列表")
        user_url = f"https://www.douyin.com/user/{sec_uid}"
        snapshots: list[WorkSnapshot] = []
        cursor = "0"
        try:
            for _ in range(max(1, int(max_pages))):
                page = api.get_user_work_info(auth, user_url, cursor)
                aweme_list = page.get("aweme_list") if isinstance(page, dict) else None
                if isinstance(aweme_list, list):
                    snapshots.extend(normalize_work(item) for item in aweme_list if isinstance(item, dict))
                if not isinstance(page, dict) or page.get("has_more") != 1:
                    break
                cursor = str(page.get("max_cursor") or "0")
        except DouyinAdapterError:
            raise
        except Exception as error:
            raise _wrap(error, "作品列表") from error
        return snapshots

    def publish_video(
        self, cookie: str, video_path: str, *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        creator = upstream.douyin_creator_api_cls()
        auth = self._auth(cookie, "视频发布")
        try:
            ok, message, result = creator.post_video(
                auth, video_path, title=title, desc=desc,
                visibility=int(visibility), allow_download=bool(allow_download),
                timing=timing,
            )
        except DouyinAdapterError:
            raise
        except Exception as error:
            raise _wrap(error, "视频发布") from error
        return PublishOutcome(
            ok=bool(ok), message=str(message or ""),
            provider_work_id=extract_provider_work_id(result),
            result_raw=result if isinstance(result, dict) else {},
        )

    def publish_images(
        self, cookie: str, image_paths: list[str], *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        creator = upstream.douyin_creator_api_cls()
        auth = self._auth(cookie, "图集发布")
        try:
            ok, message, result = creator.post_images(
                auth, list(image_paths), title=title, desc=desc,
                visibility=int(visibility), allow_download=bool(allow_download),
                timing=timing,
            )
        except DouyinAdapterError:
            raise
        except Exception as error:
            raise _wrap(error, "图集发布") from error
        return PublishOutcome(
            ok=bool(ok), message=str(message or ""),
            provider_work_id=extract_provider_work_id(result),
            result_raw=result if isinstance(result, dict) else {},
        )
