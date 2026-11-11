from __future__ import annotations

from threading import Lock

from backend.app.core.config import get_settings
from backend.app.core.distributed_rate_limit import SlidingWindowLimiter

# 默认每账号抓取限速（次/分钟）。注意：scheduler_interval_seconds 是
# “调度间隔（秒）”，单位不同，不能作为每分钟次数的兜底值。
DEFAULT_CRAWL_PER_MINUTE = 5


class CrawlRateLimiter:
    """按账号的抓取限速。

    后端与认证限流一致：配置 REDIS_URL 时多进程共享计数，
    否则回退进程内存（单进程开发）。
    """

    def __init__(self, max_per_minute: int | None = None):
        # 构造参数优先（测试/单次调优），未显式传入时读配置
        self._explicit_max = max_per_minute
        self._max = max_per_minute if max_per_minute is not None else DEFAULT_CRAWL_PER_MINUTE
        self._limiter = SlidingWindowLimiter(prefix="crawl", window_seconds=60.0)

    @property
    def max_per_minute(self) -> int:
        if self._explicit_max is not None:
            return self._explicit_max
        try:
            # 显式配置 0 表示停抓，不能用 `or` 吞掉
            configured = getattr(get_settings(), "crawl_rate_limit_per_minute", None)
            if configured is None:
                return self._max
            return int(configured)
        except Exception:
            return self._max

    def allow(self, account_id: int) -> bool:
        return self._limiter.consume(str(account_id), self.max_per_minute) is not None

    def reset(self, account_id: int) -> None:
        self._limiter.reset(str(account_id))


_global_limiter: CrawlRateLimiter | None = None
_global_limiter_lock = Lock()


def get_rate_limiter() -> CrawlRateLimiter:
    """线程安全的懒初始化：FastAPI 线程池与调度器线程并发调用。"""
    global _global_limiter
    if _global_limiter is None:
        with _global_limiter_lock:
            if _global_limiter is None:
                _global_limiter = CrawlRateLimiter(max_per_minute=DEFAULT_CRAWL_PER_MINUTE)
    return _global_limiter
