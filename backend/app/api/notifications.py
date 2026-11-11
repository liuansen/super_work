from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.models import Notification, User

logger = logging.getLogger(__name__)
from backend.app.schemas.common import paginate_query, paginated

router = APIRouter(prefix="/notifications", tags=["notifications"])


def serialize_notification(n: Notification) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "level": n.level,
        "source_task_id": n.source_task_id,
        "source_type": n.source_type,
        "source_id": n.source_id,
        "read": n.read,
        "created_at": n.created_at.isoformat(),
    }


@router.get("")
def list_notifications(
    unread: Optional[bool] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Notification).where(Notification.user_id == current_user.id)
    if unread is not None:
        # unread=True 表示“只看未读”，因此过滤条件是 read == (not unread)。
        # 早期只处理 unread=True，传 false 时返回全部（含未读），过滤语义失效。
        stmt = stmt.where(Notification.read == (not unread))
    # PERF-2：SQL 侧分页
    return paginate_query(
        db,
        stmt,
        page=page,
        page_size=page_size,
        serializer=serialize_notification,
        order_by=(Notification.created_at.desc(), Notification.id.desc()),
    )


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    n.read = True
    db.commit()
    db.refresh(n)
    return serialize_notification(n)


@router.post("/read-all")
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 单条 UPDATE 完成，避免把全部未读对象加载进内存逐条置位
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read == False)
        .values(read=True)
    )
    db.commit()
    return {"marked": result.rowcount or 0}


# ---------------------------------------------------------------------------
# 通知流（SSE）
# ---------------------------------------------------------------------------

# 单连接最长 30 分钟；前端在超时/网络恢复后自动重连。
# 三个值都可用环境变量覆盖（测试用小值，避免长连接挂住用例）。
def _env_float(name: str, default: float) -> float:
    import os

    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


_STREAM_MAX_SECONDS = _env_float("NOTIFICATION_STREAM_MAX_SECONDS", 30 * 60)
_STREAM_POLL_SECONDS = _env_float("NOTIFICATION_STREAM_POLL_SECONDS", 5.0)
_STREAM_HEARTBEAT_SECONDS = _env_float("NOTIFICATION_STREAM_HEARTBEAT_SECONDS", 15.0)


def _sse(data: dict[str, Any] | None = None, *, comment: str | None = None) -> str:
    if comment is not None:
        return f": {comment}\n\n"
    return f"data: {json.dumps(data or {}, ensure_ascii=False)}\n\n"


def _notification_stream(user_id: int, bind) -> Iterator[str]:
    """先补发未读，再增量推送新通知。

    用同步生成器（Starlette 会放到线程池迭代），与抓取链路 SSE 一致：
    避免 async 生成器里做阻塞 DB 查询卡住事件循环。
    """
    from sqlalchemy.orm import Session as _Session

    # 用请求 session 的 bind 建新 session：流式迭代时请求 session 已关闭，
    # 而 bind 让测试的临时库同样生效（直接 SessionLocal 会绕过依赖覆盖）
    db = _Session(bind=bind)
    try:
        # 连接建立时先发未读列表（前端无需再单独拉一次）
        unread_rows = db.scalars(
            select(Notification)
            .where(Notification.user_id == user_id, Notification.read == False)  # noqa: E712
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .limit(20)
        ).all()
        yield _sse({"type": "snapshot", "items": [serialize_notification(n) for n in unread_rows]})
        last_id = db.scalar(
            select(Notification.id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.id.desc())
            .limit(1)
        ) or 0

        deadline = time.monotonic() + _STREAM_MAX_SECONDS
        last_beat = time.monotonic()
        # 客户端断开由 Starlette 关闭生成器触发 GeneratorExit，无需轮询 is_disconnected
        while time.monotonic() < deadline:
            time.sleep(_STREAM_POLL_SECONDS)
            rows = db.scalars(
                select(Notification)
                .where(Notification.user_id == user_id, Notification.id > last_id)
                .order_by(Notification.id.asc())
                .limit(50)
            ).all()
            if rows:
                last_id = rows[-1].id
                yield _sse({"type": "new", "items": [serialize_notification(n) for n in rows]})
                last_beat = time.monotonic()
            elif time.monotonic() - last_beat >= _STREAM_HEARTBEAT_SECONDS:
                yield _sse(comment="ping")
                last_beat = time.monotonic()
    except GeneratorExit:
        # 客户端断开：正常收尾，不记录异常
        raise
    except Exception:
        logger.warning("通知流异常终止", exc_info=True)
        yield _sse({"type": "error"})
    finally:
        db.close()


@router.get("/stream")
def stream_notifications(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """长连接推送未读/新通知（SSE）。

    替代前端 30s 轮询：一条空闲连接换掉每用户每分钟 2 次请求。
    客户端用 fetch + ReadableStream 读取（需要 Authorization 头，
    原生 EventSource 无法携带）。
    """
    return StreamingResponse(
        _notification_stream(current_user.id, db.get_bind()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
