"""add app permissions: users.is_admin, app_registry, user_app_permissions

Revision ID: b7d8e9f0a1b2
Revises: a9c1e2f3b4d5
Create Date: 2026-11-12
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b7d8e9f0a1b2"
down_revision: Union[str, None] = "a9c1e2f3b4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 与 backend/app/services/app_perms.py DEFAULT_APPS 保持一致（有意复制：
# 迁移不 import 应用代码，避免未来漂移影响历史迁移的可重放性）
_SEED_APPS = [
    (0, "xhs", "小红书运营", "采集、内容管理、创作与发布的一站式运营工作台"),
    (1, "douyin", "抖音运营", "多账号采集参考、审核发布与真实数据复盘"),
    (2, "clip", "剪辑工坊", "从内容库选素材，剪辑成片并送入小红书或抖音发布"),
]


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0")
        )
    # 首个注册用户（最低 id）为管理员；空表时无行可更新，安全。
    # 派生表包裹：MySQL 禁止 UPDATE 的子查询直接引用目标表（ERROR 1093）
    op.execute(
        "UPDATE users SET is_admin = 1 WHERE id ="
        " (SELECT min_id FROM (SELECT MIN(id) AS min_id FROM users) AS first_user)"
    )

    op.create_table(
        "app_registry",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("app_key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("app_key", name="uq_app_registry_key"),
    )

    op.create_table(
        "user_app_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("app_key", sa.String(length=32), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "app_key", name="uq_user_app_permissions"),
    )
    op.create_index("ix_user_app_permissions_user_id", "user_app_permissions", ["user_id"])
    op.create_index("ix_user_app_permissions_app_key", "user_app_permissions", ["app_key"])

    # 时间口径与模型 default shanghai_now（naive 北京时间）对齐
    stamp = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")
    for sort_order, key, name, description in _SEED_APPS:
        op.execute(
            "INSERT INTO app_registry (app_key, name, description, enabled, sort_order,"
            " updated_at, created_at) VALUES"
            f" ('{key}', '{name}', '{description}', 1, {sort_order},"
            f" '{stamp}', '{stamp}')"
        )


def downgrade() -> None:
    op.drop_table("user_app_permissions")
    op.drop_table("app_registry")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_admin")
