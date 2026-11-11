from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base
from backend.app.core.time import shanghai_now


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # review P2：令牌版本号。写入 JWT 的 ver 声明，与库内值不一致即失效。
    # 用于“暂停所有会话”（logout-all）/ 凭证泄露后的吊销——无状态 JWT
    # 此前一旦签发就只能在 7 天后自然过期。
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=shanghai_now)
