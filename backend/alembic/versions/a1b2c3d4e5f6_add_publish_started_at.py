"""add publish_started_at to publish_jobs

Revision ID: a1b2c3d4e5f6
Revises: e3f1a9c2b7d4
Create Date: 2026-11-10

启动对账需要知道任务何时被领取（置为 publishing/uploading），
用于识别进程重启后滞留的僵尸任务。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "e3f1a9c2b7d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.add_column(sa.Column("publish_started_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("publish_jobs") as batch_op:
        batch_op.drop_column("publish_started_at")
