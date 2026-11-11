"""认证接口限流（SEC-6）。

按 ``IP + username`` 维度限制登录/注册尝试频率，并对纯 IP 维度做兜底。

后端选择：配置 ``REDIS_URL`` 时走 Redis（多 worker/多副本共享计数），
否则回退进程内存（单进程开发场景）。实现见 core/distributed_rate_limit.py。
"""
from __future__ import annotations

from backend.app.core.distributed_rate_limit import SlidingWindowLimiter

# IP 维度是全局兜底键：内存淘汰时必须保护，被淘汰等于防护归零
_IP_KEY_PREFIX = "ip:"

_limiter = SlidingWindowLimiter(
    prefix="auth",
    window_seconds=60.0,
    protected_key_prefixes=(_IP_KEY_PREFIX,),
)


def check_rate_limit(key: str, limit_per_minute: int, now: float | None = None) -> bool:
    """滑动窗口限流。返回 True 表示放行（已记录本次尝试），False 表示已超限。"""
    return _limiter.consume(key, limit_per_minute, now=now) is not None


def consume_rate_limit(key: str, limit_per_minute: int, now: float | None = None) -> float | None:
    """同 check_rate_limit，但返回本次记录的时间戳（超限返回 None）。

    配合 release_rate_limit_at 精确撤销「本次」占用的名额。
    """
    return _limiter.consume(key, limit_per_minute, now=now)


def release_rate_limit_at(key: str, timestamp: float | None) -> None:
    """精确移除 consume_rate_limit 返回的那次记录。"""
    _limiter.release(key, timestamp)


def release_rate_limit(key: str, now: float | None = None) -> None:
    """撤销最近一次记录的尝试（旧接口，保留给测试/非并发场景）。"""
    # 内存后端：时间戳即 monotonic；Redis 后端按当前时钟回退一次近似释放
    import time

    _limiter.release(key, now if now is not None else time.monotonic())


def reset_rate_limit(key: str) -> None:
    """测试辅助：清空指定键的尝试记录。"""
    _limiter.reset(key)


def reset_all() -> None:
    """测试辅助：清空全部限流状态（含 IP 兜底键）。"""
    _limiter.reset_all()


def auth_attempt_key(client_ip: str, username: str) -> str:
    return f"{client_ip}:{username.strip().lower()}"


def check_ip_rate_limit(client_ip: str, limit_per_minute: int, now: float | None = None) -> bool:
    """纯 IP 维度的滑动窗口（review P2-5）：防止轮换用户名绕过按用户的限流。

    限值通常是按用户限值的若干倍（正常用户很少在 1 分钟内从同一 IP
    尝试几十个不同账号），超限返回 False。
    """
    return _limiter.consume(f"{_IP_KEY_PREFIX}{client_ip}", limit_per_minute, now=now) is not None


def consume_ip_rate_limit(client_ip: str, limit_per_minute: int, now: float | None = None) -> float | None:
    """IP 维度的 consume 版本：返回本次时间戳供精确退还。"""
    return _limiter.consume(f"{_IP_KEY_PREFIX}{client_ip}", limit_per_minute, now=now)


def release_ip_rate_limit_at(client_ip: str, timestamp: float | None) -> None:
    """精确退还 consume_ip_rate_limit 占用的名额。"""
    _limiter.release(f"{_IP_KEY_PREFIX}{client_ip}", timestamp)


def release_ip_rate_limit(client_ip: str, now: float | None = None) -> None:
    release_rate_limit(f"{_IP_KEY_PREFIX}{client_ip}", now=now)
