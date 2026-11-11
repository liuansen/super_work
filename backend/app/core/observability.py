"""可观测性：请求 ID、结构化日志、Prometheus 指标。

排障时最痛的两件事：日志里串不起同一次请求的多条记录；没有 QPS/延迟/错误率
的时序数据。这里用零依赖的方式补齐（不引入 prometheus_client）。
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from contextvars import ContextVar
from typing import Any

REQUEST_ID_HEADER = "X-Request-ID"
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 注入每条日志记录。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(record.created))
            + f".{int(record.msecs):03d}",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )


def configure_logging() -> None:
    """配置根日志（幂等）。

    - ``LOG_LEVEL``：日志级别，默认 INFO
    - ``LOG_JSON=1``：输出 JSON 行（便于日志采集），默认人类可读
    """
    level_name = (os.getenv("LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    json_mode = (os.getenv("LOG_JSON") or "").strip().lower() in {"1", "true", "yes", "on"}

    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "_app_handler", False)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler._app_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    handler.setFormatter(JsonFormatter() if json_mode else TextFormatter())
    if not any(isinstance(f, RequestIdFilter) for f in handler.filters):
        handler.addFilter(RequestIdFilter())
    root.setLevel(level)

    # uvicorn 自带 handler（access 默认 propagate=False）：补上 request_id，
    # 否则访问日志与业务日志无法通过请求 ID 关联
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for h in logging.getLogger(name).handlers:
            if not any(isinstance(f, RequestIdFilter) for f in h.filters):
                h.addFilter(RequestIdFilter())
            if name == "uvicorn.access":
                h.setFormatter(
                    JsonFormatter()
                    if json_mode
                    else logging.Formatter(
                        "%(asctime)s %(levelname)s [%(request_id)s] %(message)s",
                        datefmt="%H:%M:%S",
                    )
                )
