from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from backend.app.core.config import get_settings

# 默认每账号抓取限速（次/分钟）。注意：scheduler_interval_seconds 是
# “调度间隔（秒）”，单位不同，不能作为每分钟次数的兜底值。
DEFAULT_CRAWL_PER_MINUTE = 5


class CrawlRateLimiter:
    def __init__(self, max_per_minute: int | None = None):
        self._max = max_per_minute or DEFAULT_CRAWL_PER_MINUTE
        self._lock = Lock()
        self._windows: dict[int, list[float]] = defaultdict(list)

    @property
    def max_per_minute(self) -> int:
        try:
            return int(getattr(get_settings(), "crawl_rate_limit_per_minute", 0)) or self._max
        except Exception:
            return self._max

    def allow(self, account_id: int) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        with self._lock:
            window = self._windows[account_id]
            self._windows[account_id] = [t for t in window if t > cutoff]
            if len(self._windows[account_id]) >= self.max_per_minute:
                return False
            self._windows[account_id].append(now)
            return True

    def reset(self, account_id: int) -> None:
        with self._lock:
            self._windows.pop(account_id, None)


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
