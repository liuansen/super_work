"""notes.search_text + FTS5 全文索引（优化：关键词检索不再扫 raw_json）

背景：关键词匹配此前把用户全部笔记载入内存，对 json.dumps(raw_json)
逐条 LIKE/子串匹配，笔记几千条后监控刷新是 O(目标 × 全库)。

本迁移：
1. 新增 ``notes.search_text``（写入时由 model 事件维护的规范化检索文本）；
2. 用与线上一致的规则回填存量行（Python 逻辑内联，避免迁移依赖会变的业务代码）；
3. SQLite 上创建 FTS5 trigram 虚拟表 + 同步触发器并全量重建；
   非 SQLite 或未编译 FTS5 时跳过（检索自动回退 LIKE）。

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-11-11
"""
from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None

_SEARCH_TEXT_MAX_CHARS = 60_000
_TEXT_KEYS = ("tags", "topics", "keywords", "tag_list", "title", "desc", "content", "note_id")


def _collect_text(value: Any, out: list[str], depth: int = 0) -> None:
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


def _build_search_text(row: Any) -> str:
    parts = [
        row.title or "",
        row.content or "",
        row.author_name or "",
        row.note_id or "",
    ]
    raw = row.raw_json
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = None
    if raw:
        extracted: list[str] = []
        _collect_text(raw, extracted)
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
    return "\n".join(deduped)[:_SEARCH_TEXT_MAX_CHARS]


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.add_column(
            sa.Column("search_text", sa.Text(), nullable=False, server_default="")
        )

    bind = op.get_bind()

    # 回填存量行（分批，避免大表一次性锁住）
    rows = bind.execute(
        sa.text("SELECT id, title, content, author_name, note_id, raw_json FROM notes")
    ).fetchall()
    for row in rows:
        bind.execute(
            sa.text("UPDATE notes SET search_text = :text WHERE id = :id"),
            {"text": _build_search_text(row), "id": row.id},
        )

    if bind.dialect.name != "sqlite":
        # MySQL 等后端：FTS 加速暂不启用，检索走 search_text LIKE
        return

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
    for statement in ddl:
        bind.execute(sa.text(statement))
    bind.execute(sa.text("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for statement in (
            "DROP TRIGGER IF EXISTS notes_fts_au",
            "DROP TRIGGER IF EXISTS notes_fts_ad",
            "DROP TRIGGER IF EXISTS notes_fts_ai",
            "DROP TABLE IF EXISTS notes_fts",
        ):
            bind.execute(sa.text(statement))
    with op.batch_alter_table("notes") as batch_op:
        batch_op.drop_column("search_text")
