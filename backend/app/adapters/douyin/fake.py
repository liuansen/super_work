"""离线假适配器：确定性替身，测试与无凭证开发使用。

约定（可由 cookie/url 内容触发）：
- cookie 含 "invalid"  → check_account/任何操作抛 DouyinAuthError
- cookie 含 "netfail"  → 抛 DouyinNetworkError
- cookie 含 "upfail"   → 抛 DouyinUpstreamError
- cookie 含 "pubnetfail" → 身份确认正常，但发布阶段抛 DouyinNetworkError
  （模拟"授权有效、发送中断"的不明结果场景）
- publish 的 title 含 "boom" → 发布失败（ok=False）
其余情况返回可预期的固定数据，同一输入永远同一输出。
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

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


def _tag(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _fail(cookie: str, action: str) -> None:
    if "pubnetfail" in cookie:
        return  # 授权有效；仅发布阶段失败（见 publish_* 方法）
    if "invalid" in cookie:
        raise DouyinAuthError(f"{action}: cookie invalid")
    if "netfail" in cookie:
        raise DouyinNetworkError(f"{action}: network unreachable (结果未知)")
    if "upfail" in cookie:
        raise DouyinUpstreamError(f"{action}: upstream rejected")


class FakeDouyinAdapter:
    name = "fake"

    def check_account(self, cookie: str) -> AccountIdentity:
        _fail(cookie, "身份确认")
        tag = _tag(cookie)
        return AccountIdentity(
            provider_account_id=f"sec-{tag}",
            nickname=f"测试账号-{tag[:4]}",
            avatar_url=f"https://example.com/avatar/{tag}.jpg",
            raw={"source": "fake"},
        )

    def crawl_work(self, cookie: str, url: str) -> WorkSnapshot:
        _fail(cookie, "作品采集")
        match = _AWEME_ID_RE.search(url or "")
        if not match:
            raise DouyinUpstreamError(f"无法从链接解析作品 ID: {url}")
        work_id = match.group(1)
        tag = _tag(work_id)
        return WorkSnapshot(
            provider_work_id=work_id,
            title=f"假作品-{tag}",
            cover_url=f"https://example.com/cover/{tag}.jpg",
            author_nickname="假作者",
            author_sec_uid=f"sec-{tag}",
            work_url=f"https://www.douyin.com/video/{work_id}",
            duration_ms=45_000,
            publish_time_ms=1_700_000_000_000,
            stats=WorkStats(
                digg_count=1000 + int(tag[:3], 16),
                comment_count=100 + int(tag[3:5], 16),
                share_count=10 + int(tag[5:6], 16),
                collect_count=50 + int(tag[6:8], 16),
            ),
            raw={"source": "fake", "aweme_id": work_id},
        )

    def list_own_works(self, cookie: str, sec_uid: str, max_pages: int = 3) -> list[WorkSnapshot]:
        _fail(cookie, "作品列表")
        base = int(_tag(sec_uid), 16)
        works = []
        for index in range(3):
            work_id = str(7100000000000000000 + base % 100000 + index)
            works.append(
                WorkSnapshot(
                    provider_work_id=work_id,
                    title=f"我的假作品-{index + 1}",
                    cover_url=f"https://example.com/cover/{work_id}.jpg",
                    author_nickname="我自己",
                    author_sec_uid=sec_uid,
                    work_url=f"https://www.douyin.com/video/{work_id}",
                    duration_ms=30_000 * (index + 1),
                    publish_time_ms=1_700_000_000_000 + index * 86_400_000,
                    stats=WorkStats(
                        digg_count=500 - index * 100,
                        comment_count=50 - index * 10,
                        share_count=5 - index,
                        collect_count=20 - index * 5,
                    ),
                    raw={"source": "fake", "aweme_id": work_id},
                )
            )
        return works

    def publish_video(
        self, cookie: str, video_path: str, *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        if "pubnetfail" in cookie:
            raise DouyinNetworkError("视频发布: connection reset during upload (结果未知)")
        _fail(cookie, "视频发布")
        if "boom" in title:
            return PublishOutcome(ok=False, message="平台拒绝：内容检测未通过", result_raw={"code": 403})
        work_id = f"7200{_tag(cookie + video_path + title)}"
        return PublishOutcome(
            ok=True, message="发布成功",
            provider_work_id=work_id,
            result_raw={"aweme_id": work_id, "source": "fake", "timing": timing or 0},
        )

    def publish_images(
        self, cookie: str, image_paths: list[str], *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        if "pubnetfail" in cookie:
            raise DouyinNetworkError("图集发布: connection reset during upload (结果未知)")
        _fail(cookie, "图集发布")
        if "boom" in title:
            return PublishOutcome(ok=False, message="平台拒绝：内容检测未通过", result_raw={"code": 403})
        work_id = f"7300{_tag(cookie + ''.join(image_paths) + title)}"
        return PublishOutcome(
            ok=True, message="发布成功",
            provider_work_id=work_id,
            result_raw={"aweme_id": work_id, "source": "fake", "timing": timing or 0},
        )
