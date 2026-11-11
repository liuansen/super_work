"""受控的后台执行器。

长任务（搜索 → AI 改写 → 发布）此前完整跑在请求线程里：上游慢时请求挂
数分钟，占满 FastAPI 线程池后整站失去响应。

这里用线程池执行，但保留「快速任务同步返回」的语义：
- 任务在阈值内完成 → 直接返回结果（前端/测试无需改造）；
- 超过阈值 → 返回 202 + 任务 id，前端到任务中心查看进度。
执行体自己创建 Session（不可跨线程复用请求的 session），并使用请求
session 的 bind 以确保测试的临时数据库同样生效。
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _worker_count() -> int:
    try:
        return max(1, int(os.getenv("TASK_WORKERS", "4")))
    except ValueError:
        return 4


_executor = ThreadPoolExecutor(max_workers=_worker_count(), thread_name_prefix="app-task")


def submit(fn: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
    return _executor.submit(fn, *args, **kwargs)


def sync_wait_seconds() -> float:
    """同步等待阈值（秒）：超过则返回 202 让前端轮询。"""
    try:
        return float(os.getenv("TASK_SYNC_WAIT_SECONDS", "90"))
    except ValueError:
        return 90.0


def shutdown(wait: bool = False) -> None:
    _executor.shutdown(wait=wait)


def pending_count() -> int:
    """当前排队中的任务数（指标/排障用）。"""
    return _executor._work_queue.qsize()  # noqa: SLF001
