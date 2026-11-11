"""auto_tasks.claimed_at 原子领取 + publish_jobs.user_id 收紧 NOT NULL

SCH-2：自动运营任务执行前需要原子领取（条件 UPDATE claimed_at），
防止调度器与手动运行并发重复执行。
DB-2：publish_jobs.user_id 在 ae358e965bef 已回填，这里收紧为 NOT NULL
与模型声明一致（SQLite 走 batch 模式重建表）。

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("auto_tasks") as batch_op:
        batch_op.add_column(sa.Column("claimed_at", sa.DateTime(), nullable=True))

    # publish_jobs.user_id 收紧：先兜底回填（理论上 ae358e965bef 已处理过），
    # 无法回填的悬挂行按策略删除（无账号也无草稿来源的任务无法归属任何用户）
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE publish_jobs SET user_id = ("
            "  SELECT pa.user_id FROM platform_accounts pa"
            "  WHERE pa.id = publish_jobs.platform_account_id)"
            " WHERE user_id IS NULL AND platform_account_id IS NOT NULL"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE publish_jobs SET user_id = ("
            "  SELECT d.user_id FROM ai_drafts d WHERE d.id = publish_jobs.source_draft_id)"
            " WHERE user_id IS NULL AND source_draft_id IS NOT NULL"
        )
    )
    connection.execute(sa.text("DELETE FROM publish_assets WHERE publish_job_id IN (SELECT id FROM publish_jobs WHERE user_id IS NULL)"))
    connection.execute(sa.text("DELETE FROM publish_jobs WHERE user_id IS NULL"))

    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.alter_column("user_id", existing_type=sa.Integer(), nullable=True)
    with op.batch_alter_table("auto_tasks") as batch_op:
        batch_op.drop_column("claimed_at")
