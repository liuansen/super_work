"""应用权限数据模型。

语义（默认全量开通 + 显式回收）：
- ``app_registry`` 是后台管理的应用目录：``enabled=False`` 表示全体禁用；
- ``user_app_permissions`` 是按账号的分配记录：**无记录 = 有权限**，
  ``granted=False`` = 明确拒绝（回收）。新增应用自动对所有人可见，
  管理员无需批量补记录。
- 账号可进入应用 ⟺ 目录 enabled 且未被该账号回收；管理员始终放行。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class AppRegistry(Base):
    __tablename__ = "app_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_key: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)


class UserAppPermission(Base):
    __tablename__ = "user_app_permissions"
    __table_args__ = (
        UniqueConstraint("user_id", "app_key", name="uq_user_app_permissions"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    app_key: Mapped[str] = mapped_column(String(32), index=True)
    granted: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now, onupdate=shanghai_now)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
