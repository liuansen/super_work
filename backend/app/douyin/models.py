"""抖音业务表：账号、参考作品、发布任务、指标快照。

与小红书表完全隔离；模型必须在 backend/app/models/__init__.py 显式导入，
保证 Alembic metadata 覆盖。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class DouyinAccount(Base):
    __tablename__ = "douyin_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_account_id", name="uq_douyin_accounts_user_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_account_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    nickname: Mapped[str] = mapped_column(String(128), default="")
    avatar_url: Mapped[str] = mapped_column(Text, default="")
    cookie_encrypted: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default="unknown")
    status_message: Mapped[str] = mapped_column(Text, default="")
    profile_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class DouyinReferenceWork(Base):
    __tablename__ = "douyin_reference_works"
    __table_args__ = (
        UniqueConstraint("user_id", "provider_work_id", name="uq_douyin_ref_user_work"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider_work_id: Mapped[str] = mapped_column(String(64), index=True)
    work_url: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    cover_url: Mapped[str] = mapped_column(Text, default="")
    author_nickname: Mapped[str] = mapped_column(String(128), default="")
    author_sec_uid: Mapped[str] = mapped_column(String(128), default="")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    publish_time_ms: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    source_account_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("douyin_accounts.id"), nullable=True
    )
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class DouyinPublishTask(Base):
    __tablename__ = "douyin_publish_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_douyin_ptask_user_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("douyin_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="video")
    media_names_json: Mapped[str] = mapped_column(Text, default="[]")
    title: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    visibility: Mapped[int] = mapped_column(Integer, default=1)
    allow_download: Mapped[bool] = mapped_column(Boolean, default=True)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    provider_work_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    dispatched_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)


class DouyinMetricSnapshot(Base):
    __tablename__ = "douyin_metric_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    reference_work_id: Mapped[int] = mapped_column(
        ForeignKey("douyin_reference_works.id"), index=True
    )
    digg_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    share_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    collect_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    availability: Mapped[str] = mapped_column(String(16), default="available")
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
