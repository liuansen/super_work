from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ).replace(tzinfo=None)


def to_naive_shanghai(value: datetime) -> datetime:
    """把带时区的时间统一转为无时区北京时间（与库内存储口径一致）。

    naive 值视为已是北京时间，原样返回。
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
