from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class ClipSession(Base):
    __tablename__ = "clip_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    manifest_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True)
    handoff_jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    handoff_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    session_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    exchanged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class ClipExport(Base):
    __tablename__ = "clip_exports"
    __table_args__ = (
        UniqueConstraint("session_id", "client_export_id", name="uq_clip_exports_session_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("clip_sessions.id"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="")
    file_name: Mapped[str] = mapped_column(String(180), unique=True)
    mime: Mapped[str] = mapped_column(String(64), default="video/mp4")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="available")
    linked_draft_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_drafts.id"), nullable=True)
    client_export_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
