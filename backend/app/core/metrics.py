"""极简 Prometheus 指标（零依赖）。

只暴露运维最需要的三类：
- ``app_requests_total{method,status,route}`` 计数器
- ``app_request_duration_seconds_sum/count{route}`` 延迟累计
- ``app_inflight_requests`` 并发度

刻意不做直方图分桶——需要 P95 时请把指标接到真正的 Prometheus +
histogram，或在日志侧做聚合；这里保证「有数据、可告警」的最低门槛。
"""
from __future__ import annotations

import threading
from collections import defaultdict

_lock = threading.Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_durations: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])  # route -> [sum, count]
_inflight = 0

_MAX_ROUTES = 500


def inc_inflight() -> None:
    global _inflight
    with _lock:
        _inflight += 1


def dec_inflight() -> None:
    global _inflight
    with _lock:
        _inflight = max(_inflight - 1, 0)


def record_request(method: str, status: int, route: str, duration_seconds: float) -> None:
    key = (method.upper(), str(status), route)
    with _lock:
        if len(_requests) < _MAX_ROUTES or key in _requests:
            _requests[key] += 1
        bucket = _durations[route]
        bucket[0] += duration_seconds
        bucket[1] += 1


def render_prometheus() -> str:
    """生成 Prometheus 文本格式（text/plain; version=0.0.4）。"""
    lines = [
        "# HELP app_requests_total Total HTTP requests.",
        "# TYPE app_requests_total counter",
    ]
    with _lock:
        for (method, status, route), count in sorted(_requests.items()):
            lines.append(
                f'app_requests_total{{method="{method}",status="{status}",route="{route}"}} {count}'
            )
        lines.append("# HELP app_request_duration_seconds_sum Total time spent on requests.")
        lines.append("# TYPE app_request_duration_seconds_sum counter")
        lines.append("# HELP app_request_duration_seconds_count Number of timed requests.")
        lines.append("# TYPE app_request_duration_seconds_count counter")
        for route, (total, count) in sorted(_durations.items()):
            lines.append(f'app_request_duration_seconds_sum{{route="{route}"}} {total:.6f}')
            lines.append(f'app_request_duration_seconds_count{{route="{route}"}} {count}')
        lines.append("# HELP app_inflight_requests Requests currently being processed.")
        lines.append("# TYPE app_inflight_requests gauge")
        lines.append(f"app_inflight_requests {_inflight}")
    return "\n".join(lines) + "\n"


def reset_metrics() -> None:
    """测试辅助。"""
    global _inflight
    with _lock:
        _requests.clear()
        _durations.clear()
        _inflight = 0
