from __future__ import annotations

from typing import Any, Callable, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def paginated(items: Iterable[Any], page: int = 1, page_size: int = 20) -> dict:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)
    materialized = list(items)
    start = (safe_page - 1) * safe_page_size
    end = start + safe_page_size
    return {
        "total": len(materialized),
        "page": safe_page,
        "page_size": safe_page_size,
        "items": materialized[start:end],
    }


def paginate_query(
    db: Session,
    statement,
    *,
    page: int = 1,
    page_size: int = 20,
    serializer: Callable[[Any], Any],
    order_by: Any | None = None,
) -> dict:
    """PERF-2（P1-12）：SQL 侧 COUNT + LIMIT/OFFSET 分页。

    替代"全量 .all() 后内存切片"——10 万行时 page_size=20 的请求只读取 20 行。
    statement 应为尚未排序/未截断的基础查询。
    """
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)

    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0

    query = statement
    if order_by is not None:
        if isinstance(order_by, (tuple, list)):
            query = query.order_by(*order_by)
        else:
            query = query.order_by(order_by)
    rows = db.scalars(query.limit(safe_page_size).offset((safe_page - 1) * safe_page_size)).all()

    return {
        "total": int(total),
        "page": safe_page,
        "page_size": safe_page_size,
        "items": [serializer(row) for row in rows],
    }
