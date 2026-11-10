from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from backend.app.core.time import shanghai_now


@dataclass
class TaskState:
    id: str
    status: str
    progress: int
    updated_at: datetime


# 终态任务保留上限：防止长驻进程中 _tasks 无界增长（内存缓慢泄漏）
_MAX_FINISHED_STATES = 500


class InProcessTaskRunner:
    def __init__(self) -> None:
        self._tasks: Dict[str, TaskState] = {}

    def register(self, task_id: str) -> TaskState:
        state = TaskState(task_id, "pending", 0, shanghai_now())
        self._tasks[task_id] = state
        self._evict_finished()
        return state

    def _evict_finished(self) -> None:
        finished = [
            (state.updated_at, task_id)
            for task_id, state in self._tasks.items()
            if state.status in ("completed", "failed", "cancelled")
        ]
        # 按 updated_at 从旧到新淘汰多余的已终结状态
        evict_count = max(0, len(finished) - _MAX_FINISHED_STATES)
        for _, task_id in sorted(finished, key=lambda item: item[0])[:evict_count]:
            self._tasks.pop(task_id, None)

    def get(self, task_id: str) -> Optional[TaskState]:
        return self._tasks.get(task_id)


task_runner = InProcessTaskRunner()
