from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Table, Text, Column, event
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


note_tags = Table(
    "note_tags",
    Base.metadata,
    Column("note_id", ForeignKey("notes.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # DB-1/W0-3：账号删除时保留笔记（引用置空），因此可空
    platform_account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("platform_accounts.id"), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(32), index=True)
    note_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(String(512), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(128), default="")
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # 写入时计算的规范化检索文本（标题/正文/作者/note_id/标签），
    # 关键词检索只碰这一列，不再对 raw_json 做 json.dumps + LIKE。
    # 由 services/note_search.py 的 before_insert/before_update 钩子维护。
    search_text: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class NoteAsset(Base):
    __tablename__ = "note_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class NoteComment(Base):
    __tablename__ = "note_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id"), index=True)
    comment_id: Mapped[str] = mapped_column(String(128), index=True)
    user_name: Mapped[str] = mapped_column(String(128), default="")
    user_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    like_count: Mapped[int] = mapped_column(Integer, default=0)
    parent_comment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at_remote: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    color: Mapped[str] = mapped_column(String(24), default="#111111")


@event.listens_for(Note, "before_insert")
@event.listens_for(Note, "before_update")
def _populate_note_search_text(mapper, connection, target: Note) -> None:  # noqa: ARG001
    """写入时维护检索文本（services/note_search.py 提供构建逻辑）。

    放在 model 事件里而不是各个 API 写入点，是为了覆盖所有落库路径
    （爬取、批量入库、监控刷新、测试构造），不会有哪条链路漏填。
    """
    from backend.app.services.note_search import build_search_text

    target.search_text = build_search_text(
        title=target.title or "",
        content=target.content or "",
        author_name=target.author_name or "",
        note_id=target.note_id or "",
        raw_json=target.raw_json,
    )
