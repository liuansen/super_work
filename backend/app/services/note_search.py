"""笔记关键词检索（单一实现）。

背景：关键词匹配此前散落在 keyword_groups / analytics / monitoring /
scheduler 四处，全部是「把用户的全部笔记载入内存，对 json.dumps(raw_json)
逐条匹配」。笔记几千条后每次监控刷新都是 O(目标数 × 全库) 全表扫。

这里的方案：
1. ``notes.search_text`` —— 写入时算好的规范化检索文本（标题 + 正文 + 作者 +
   note_id + 从 raw_json 提取的标签/话题）。查询只碰这一列，不再 json.dumps。
2. SQLite 上额外建 FTS5（trigram）索引，≥3 字的关键词走索引检索；
   短关键词（中文常见 2 字）或非 SQLite 后端回退到 ``LIKE %kw%``。
3. FTS 表缺失/不可用时静默回退 LIKE——索引是加速手段，不是正确性前提。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable

from sqlalchemy import func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.models import Note

logger = logging.getLogger(__name__)

# 检索文本长度上限：raw_json 里可能有超长字段，避免把 DB 撑爆
SEARCH_TEXT_MAX_CHARS = 60_000
# FTS5 trigram 的最小可用长度（更短的词无法命中索引）
FTS_MIN_QUERY_CHARS = 3

_TEXT_KEYS = ("tags", "topics", "keywords", "tag_list", "title", "desc", "content", "note_id")


def _collect_text(value: Any, out: list[str], depth: int = 0) -> None:
    """从 raw_json 里提取有检索价值的文本（标签/话题等），忽略嵌套过深的结构。"""
    if depth > 3:
        return
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, list):
        for item in value[:200]:
            _collect_text(item, out, depth + 1)
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in _TEXT_KEYS or isinstance(item, (list, dict)):
                _collect_text(item, out, depth + 1)
            elif isinstance(item, str) and item.strip():
                out.append(item.strip())


def build_search_text(
    *,
    title: str = "",
    content: str = "",
    author_name: str = "",
    note_id: str = "",
    raw_json: Any = None,
) -> str:
    """生成检索文本（小写、去重、截断）。

    对 raw_json 只提取标签/话题/短文本字段，不再保存整份 JSON 文本——
    这既保住了原「按标签也能搜到」的能力，又去掉了每行几十 KB 的检索负担。
    """
    parts: list[str] = [title or "", content or "", author_name or "", note_id or ""]
    if raw_json:
        extracted: list[str] = []
        _collect_text(raw_json, extracted)
        parts.extend(extracted)

    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        normalized = " ".join(str(part).split())
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(lowered)

    joined = "\n".join(deduped)
    return joined[:SEARCH_TEXT_MAX_CHARS]


def note_haystack(note: Note) -> str:
    """读取检索文本；旧数据（search_text 为空）现场构建一次。"""
    cached = (note.search_text or "").strip()
    if cached:
        return cached
    return build_search_text(
        title=note.title or "",
        content=note.content or "",
        author_name=note.author_name or "",
        note_id=note.note_id or "",
        raw_json=note.raw_json,
    )


def note_matches(note: Note, value: str) -> bool:
    needle = (value or "").strip().lower()
    if not needle:
        return False
    return needle in note_haystack(note)


def note_matches_any(note: Note, values: Iterable[str]) -> list[str]:
    """返回该笔记命中的关键词列表（一次构建 haystack）。"""
    haystack = note_haystack(note)
    return [v for v in values if (v or "").strip() and v.strip().lower() in haystack]


def _like_pattern(needle: str) -> str:
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def like_prefilter(needle: str):
    """search_text 上的 LIKE 条件（已转义通配符）。"""
    return func.lower(Note.search_text).like(_like_pattern(needle.lower()), escape="\\")


def _fts_available(db: Session) -> bool:
    bind = db.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return False
    try:
        exists = db.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notes_fts'")
        ).first()
    except Exception:
        return False
    return exists is not None


def _fts_query(needle: str) -> str:
    # trigram 索引按短语匹配；双引号需转义，否则会被当作 FTS 语法解析
    return '"' + needle.replace('"', '""') + '"'


def _fts_note_ids(db: Session, needle: str, limit: int) -> list[int] | None:
    """走 FTS 索引取候选 id；不可用/查询失败返回 None（调用方回退 LIKE）。"""
    if len(needle) < FTS_MIN_QUERY_CHARS or not _fts_available(db):
        return None
    try:
        rows = db.execute(
            text("SELECT rowid FROM notes_fts WHERE notes_fts MATCH :q LIMIT :limit"),
            {"q": _fts_query(needle), "limit": limit},
        ).all()
    except Exception as exc:  # FTS 语法/索引异常：回退 LIKE，不影响正确性
        logger.warning("FTS 查询失败，回退 LIKE: %s", exc)
        return None
    return [int(row[0]) for row in rows]


def candidate_notes(
    db: Session,
    *,
    user_id: int,
    platform: str,
    needle: str,
    limit: int,
    order_by_created: bool = True,
) -> list[Note]:
    """取关键词候选笔记（未做 Python 精筛）。

    优先 FTS 索引，回退 search_text LIKE。调用方仍需用 note_matches 精筛，
    因为 LIKE/FTS 都是子串级匹配，语义以 Python 为准。
    """
    needle = (needle or "").strip()
    if not needle:
        return []

    fts_ids = _fts_note_ids(db, needle, limit)
    stmt = select(Note).where(Note.user_id == user_id, Note.platform == platform)
    if fts_ids is not None:
        if not fts_ids:
            return []
        stmt = stmt.where(Note.id.in_(fts_ids))
    else:
        stmt = stmt.where(like_prefilter(needle))
    if order_by_created:
        stmt = stmt.order_by(Note.created_at.desc(), Note.id.desc())
    return db.scalars(stmt.limit(limit)).all()


def ensure_fts_index(engine: Engine | None = None) -> bool:
    """在 SQLite 上幂等地创建 FTS5（trigram）索引与同步触发器。

    返回 True 表示可用。非 SQLite、SQLite 未编译 FTS5、或老版本不支持
    trigram 时返回 False（检索自动回退 LIKE）。
    """
    if engine is None:
        from backend.app.core.database import engine as default_engine

        engine = default_engine
    if engine.dialect.name != "sqlite":
        return False
    ddl = [
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
            search_text,
            content='notes',
            content_rowid='id',
            tokenize='trigram'
        )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS notes_fts_ai AFTER INSERT ON notes BEGIN
            INSERT INTO notes_fts(rowid, search_text) VALUES (new.id, new.search_text);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS notes_fts_ad AFTER DELETE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS notes_fts_au AFTER UPDATE ON notes BEGIN
            INSERT INTO notes_fts(notes_fts, rowid, search_text) VALUES ('delete', old.id, old.search_text);
            INSERT INTO notes_fts(rowid, search_text) VALUES (new.id, new.search_text);
        END
        """,
    ]
    try:
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
            # 仅在索引与主表行数不一致时重建，避免每次启动全量重建
            note_count = conn.execute(text("SELECT count(*) FROM notes")).scalar() or 0
            fts_count = conn.execute(text("SELECT count(*) FROM notes_fts")).scalar() or 0
            if note_count != fts_count:
                conn.execute(text("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')"))
        return True
    except Exception as exc:
        logger.warning("FTS5 索引不可用（检索回退 LIKE）: %s", exc)
        return False


def _json_safe(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return ""


def rebuild_search_text_batch(db: Session, batch_size: int = 500) -> int:
    """为存量笔记回填 search_text（迁移/运维工具共用）。"""
    updated = 0
    while True:
        rows = db.scalars(
            select(Note).where(or_(Note.search_text == "", Note.search_text.is_(None))).limit(batch_size)
        ).all()
        if not rows:
            break
        for note in rows:
            note.search_text = build_search_text(
                title=note.title or "",
                content=note.content or "",
                author_name=note.author_name or "",
                note_id=note.note_id or "",
                raw_json=note.raw_json,
            )
            updated += 1
        db.commit()
    return updated
