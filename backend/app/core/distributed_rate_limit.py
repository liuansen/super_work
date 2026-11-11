"""滑动窗口限流（进程内 / Redis 双后端）。

背景：``auth_throttle`` 与 ``CrawlRateLimiter`` 都是纯进程内存实现，多
worker / 多副本部署时每个进程独立计数——登录限流阈值实际放大 N 倍，
抓取限速同样失效（账号风控风险）。

这里提供统一实现：配置 ``REDIS_URL`` 时走 Redis ZSET 滑动窗口（Lua 脚本
保证原子性），否则回退进程内存（单进程开发场景）。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque

logger = logging.getLogger(__name__)

# 进程内实现的内存上限：超过后按最久未活动淘汰（IP 兜底键由调用方前缀区分）
_MAX_TRACKED_KEYS = 100_000

_redis_client = None
_redis_lock = threading.Lock()
_redis_disabled = False


def _get_redis():
    """懒初始化 Redis 客户端；不可用时返回 None 并只告警一次。"""
    global _redis_client, _redis_disabled
    if _redis_disabled:
        return None
    if _redis_client is not None:
        return _redis_client

    from backend.app.core.config import get_settings

    url = (getattr(get_settings(), "redis_url", "") or "").strip()
    if not url:
        _redis_disabled = True
        return None

    with _redis_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            import redis  # 可选依赖

            client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2)
            client.ping()
            _redis_client = client
            logger.info("限流使用 Redis 后端: %s", url.split("@")[-1])
            return client
        except Exception as exc:
            logger.warning("Redis 不可用，限流回退进程内存实现（多 worker 下阈值会放大）: %s", exc)
            _redis_disabled = True
            return None


# KEYS[1]=窗口键  ARGV: now, window秒, limit, member
_CONSUME_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)
local count = redis.call('ZCARD', key)
if count >= limit then
  return 0
end
redis.call('ZADD', key, now, ARGV[4])
redis.call('PEXPIRE', key, math.floor(window * 1000) + 1000)
return 1
"""


class SlidingWindowLimiter:
    """按 key 的滑动窗口计数器；consume 返回本次时间戳（供精确 release）。"""

    def __init__(
        self,
        *,
        prefix: str,
        window_seconds: float = 60.0,
        protected_key_prefixes: tuple[str, ...] = (),
    ):
        self._prefix = prefix
        self._window = window_seconds
        # 这些前缀的键是全局兜底键，不允许被内存淘汰（淘汰等于防护归零）
        self._protected = protected_key_prefixes
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = {}

    def _redis_key(self, key: str) -> str:
        return f"ratelimit:{self._prefix}:{key}"

    def _prune(self, queue: deque[float], now: float) -> None:
        cutoff = now - self._window
        while queue and queue[0] < cutoff:
            queue.popleft()

    def _evict_if_needed(self) -> None:
        if len(self._windows) <= _MAX_TRACKED_KEYS:
            return
        removable = [k for k in self._windows if not k.startswith(self._protected)]
        if not removable:
            return
        stale = sorted(removable, key=lambda k: self._windows[k][-1] if self._windows[k] else float("-inf"))
        for key in stale[: max(len(removable) // 10, 1)]:
            self._windows.pop(key, None)

    def consume(self, key: str, limit: int, now: float | None = None) -> float | None:
        """记录一次尝试。放行返回时间戳，超限返回 None。"""
        if limit <= 0:
            return 0.0
        client = _get_redis()
        stamp = now if now is not None else time.time()

        if client is not None:
            try:
                member = f"{stamp:.6f}:{uuid.uuid4().hex[:8]}"
                allowed = client.eval(
                    _CONSUME_LUA, 1, self._redis_key(key), stamp, self._window, limit, member
                )
                return stamp if int(allowed) == 1 else None
            except Exception as exc:
                logger.warning("Redis 限流调用失败，本次回退内存判断: %s", exc)

        # 内存实现：保证单调时钟口径，避免系统时间回拨
        monotonic_now = time.monotonic()
        with self._lock:
            queue = self._windows.setdefault(key, deque())
            self._prune(queue, monotonic_now)
            if len(queue) >= limit:
                return None
            queue.append(monotonic_now)
            self._evict_if_needed()
            return monotonic_now

    def release(self, key: str, timestamp: float | None) -> None:
        """精确撤销 consume 返回的那次记录。"""
        if timestamp is None:
            return
        client = _get_redis()
        if client is not None:
            try:
                client.zremrangebyscore(self._redis_key(key), timestamp, timestamp)
                return
            except Exception as exc:
                logger.warning("Redis 限流释放失败: %s", exc)
        with self._lock:
            queue = self._windows.get(key)
            if not queue:
                return
            try:
                queue.remove(timestamp)
            except ValueError:
                pass
            if not queue:
                self._windows.pop(key, None)

    def reset(self, key: str) -> None:
        client = _get_redis()
        if client is not None:
            try:
                client.delete(self._redis_key(key))
                return
            except Exception:
                pass
        with self._lock:
            self._windows.pop(key, None)

    def reset_all(self) -> None:
        """测试辅助：清空全部窗口（Redis 后端只清无前缀键，生产勿用）。"""
        with self._lock:
            self._windows.clear()
