"""notes.platform_account_id 改为可空（DB-1 / W0-3 决策）

删除账号时保留已采集笔记（账号引用置空），而不是阻止删除或级联删笔记。
配合 delete_account 的显式清理：notes/publish_jobs/monitoring_targets
的账号引用 SET NULL，auto_tasks 引用时拒绝删除账号。

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notes") as batch_op:
        batch_op.alter_column("platform_account_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # 回滚前清空悬挂引用，否则 NOT NULL 约束失败
    connection = op.get_bind()
    connection.execute(
        sa.text("DELETE FROM notes WHERE platform_account_id IS NULL")
    )
    with op.batch_alter_table("notes") as batch_op:
        batch_op.alter_column("platform_account_id", existing_type=sa.Integer(), nullable=False)
