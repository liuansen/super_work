"""抖音适配层契约：规范化类型、错误分类与适配器协议。

与上游解耦：上游原始 dict 只在本包与适配器内部流动，
业务模块只消费这里的规范化类型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


class DouyinAdapterError(Exception):
    """适配层错误基类。"""


class DouyinAuthError(DouyinAdapterError):
    """凭证无效/登录失效：需要用户重新提供 Cookie。"""


class DouyinNetworkError(DouyinAdapterError):
    """网络失败/超时：结果未知，不能当作未发布或已发布。"""


class DouyinUpstreamError(DouyinAdapterError):
    """上游返回异常或风控拦截。"""


@dataclass
class AccountIdentity:
    """账号身份确认结果。"""

    provider_account_id: str  # sec_uid
    nickname: str = ""
    avatar_url: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class WorkStats:
    """作品互动指标。缺失字段为 None（不伪造 0）。"""

    digg_count: Optional[int] = None
    comment_count: Optional[int] = None
    share_count: Optional[int] = None
    collect_count: Optional[int] = None


@dataclass
class WorkSnapshot:
    """规范化后的作品数据（采集与作品列表共用）。"""

    provider_work_id: str
    title: str = ""
    cover_url: str = ""
    author_nickname: str = ""
    author_sec_uid: str = ""
    work_url: str = ""
    duration_ms: Optional[int] = None
    publish_time_ms: Optional[int] = None
    stats: WorkStats = field(default_factory=WorkStats)
    raw: dict = field(default_factory=dict)


@dataclass
class PublishOutcome:
    """发布结果。ok=False 时 result_raw 仍可能携带上游信息。

    上游只返回 (success, msg, res_json)：无法区分"平台已受理但查询失败"
    之类的不明态；网络层异常由适配器抛 DouyinNetworkError，由调用方记为 unknown。
    """

    ok: bool
    message: str = ""
    provider_work_id: Optional[str] = None
    result_raw: dict = field(default_factory=dict)


class DouyinAdapter(Protocol):
    """抖音平台适配协议。真实实现包装 vendor 上游；测试实现完全离线。"""

    name: str

    def check_account(self, cookie: str) -> AccountIdentity:
        """校验 Cookie 并返回平台身份；失效抛 DouyinAuthError。"""
        ...

    def crawl_work(self, cookie: str, url: str) -> WorkSnapshot:
        """采集单作品；URL 无法解析或作品不存在抛 DouyinUpstreamError。"""
        ...

    def list_own_works(self, cookie: str, sec_uid: str, max_pages: int = 3) -> list[WorkSnapshot]:
        """分页拉取指定账号作品列表（含互动数据）。"""
        ...

    def publish_video(
        self, cookie: str, video_path: str, *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        """发布视频。timing=None 立即发布，否则为秒级时间戳的定时发布。"""
        ...

    def publish_images(
        self, cookie: str, image_paths: list[str], *, title: str, desc: str,
        visibility: int, allow_download: bool, timing: Optional[int] = None,
    ) -> PublishOutcome:
        """发布图集。timing 语义同 publish_video。"""
        ...
