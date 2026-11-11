"""notes(user_id, platform, created_at) 复合索引（PERF-4 / P2-11）

列表/统计接口的热点查询路径：WHERE user_id = ? AND platform = ? ORDER BY created_at DESC。
单列索引已有；此复合索引让排序也走索引，10 万行级别避免 filesort。

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-11-11
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_notes_user_platform_created",
        "notes",
        ["user_id", "platform", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notes_user_platform_created", table_name="notes")
