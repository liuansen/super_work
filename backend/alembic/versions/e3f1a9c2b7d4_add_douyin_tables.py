"""add douyin tables

Revision ID: e3f1a9c2b7d4
Revises: 60cd5c95fde1
Create Date: 2026-11-09

抖音运营应用：账号、参考作品、发布任务、指标快照。
只新增表与索引，不修改既有表。
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e3f1a9c2b7d4'
down_revision: Union[str, None] = '60cd5c95fde1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('douyin_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider_account_id', sa.String(length=128), nullable=True),
    sa.Column('nickname', sa.String(length=128), nullable=False),
    sa.Column('avatar_url', sa.Text(), nullable=False),
    sa.Column('cookie_encrypted', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('status_message', sa.Text(), nullable=False),
    sa.Column('profile_json', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'provider_account_id', name='uq_douyin_accounts_user_provider')
    )
    op.create_index(op.f('ix_douyin_accounts_id'), 'douyin_accounts', ['id'], unique=False)
    op.create_index(op.f('ix_douyin_accounts_user_id'), 'douyin_accounts', ['user_id'], unique=False)

    op.create_table('douyin_reference_works',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('provider_work_id', sa.String(length=64), nullable=False),
    sa.Column('work_url', sa.Text(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('cover_url', sa.Text(), nullable=False),
    sa.Column('author_nickname', sa.String(length=128), nullable=False),
    sa.Column('author_sec_uid', sa.String(length=128), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('publish_time_ms', sa.BigInteger(), nullable=True),
    sa.Column('stats_json', sa.Text(), nullable=False),
    sa.Column('tags_json', sa.Text(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('raw_json', sa.Text(), nullable=False),
    sa.Column('source_account_id', sa.Integer(), nullable=True),
    sa.Column('collected_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['source_account_id'], ['douyin_accounts.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'provider_work_id', name='uq_douyin_ref_user_work')
    )
    op.create_index(op.f('ix_douyin_reference_works_id'), 'douyin_reference_works', ['id'], unique=False)
    op.create_index(op.f('ix_douyin_reference_works_user_id'), 'douyin_reference_works', ['user_id'], unique=False)
    op.create_index(op.f('ix_douyin_reference_works_provider_work_id'), 'douyin_reference_works', ['provider_work_id'], unique=False)

    op.create_table('douyin_publish_tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('account_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('media_names_json', sa.Text(), nullable=False),
    sa.Column('title', sa.String(length=128), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('visibility', sa.Integer(), nullable=False),
    sa.Column('allow_download', sa.Boolean(), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('idempotency_key', sa.String(length=64), nullable=False),
    sa.Column('provider_work_id', sa.String(length=64), nullable=True),
    sa.Column('result_json', sa.Text(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('dispatched_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['account_id'], ['douyin_accounts.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'idempotency_key', name='uq_douyin_ptask_user_key')
    )
    op.create_index(op.f('ix_douyin_publish_tasks_id'), 'douyin_publish_tasks', ['id'], unique=False)
    op.create_index(op.f('ix_douyin_publish_tasks_user_id'), 'douyin_publish_tasks', ['user_id'], unique=False)
    op.create_index(op.f('ix_douyin_publish_tasks_account_id'), 'douyin_publish_tasks', ['account_id'], unique=False)
    op.create_index(op.f('ix_douyin_publish_tasks_status'), 'douyin_publish_tasks', ['status'], unique=False)

    op.create_table('douyin_metric_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('reference_work_id', sa.Integer(), nullable=False),
    sa.Column('digg_count', sa.Integer(), nullable=True),
    sa.Column('comment_count', sa.Integer(), nullable=True),
    sa.Column('share_count', sa.Integer(), nullable=True),
    sa.Column('collect_count', sa.Integer(), nullable=True),
    sa.Column('availability', sa.String(length=16), nullable=False),
    sa.Column('collected_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['reference_work_id'], ['douyin_reference_works.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_douyin_metric_snapshots_id'), 'douyin_metric_snapshots', ['id'], unique=False)
    op.create_index(op.f('ix_douyin_metric_snapshots_user_id'), 'douyin_metric_snapshots', ['user_id'], unique=False)
    op.create_index(op.f('ix_douyin_metric_snapshots_reference_work_id'), 'douyin_metric_snapshots', ['reference_work_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_douyin_metric_snapshots_reference_work_id'), table_name='douyin_metric_snapshots')
    op.drop_index(op.f('ix_douyin_metric_snapshots_user_id'), table_name='douyin_metric_snapshots')
    op.drop_index(op.f('ix_douyin_metric_snapshots_id'), table_name='douyin_metric_snapshots')
    op.drop_table('douyin_metric_snapshots')

    op.drop_index(op.f('ix_douyin_publish_tasks_status'), table_name='douyin_publish_tasks')
    op.drop_index(op.f('ix_douyin_publish_tasks_account_id'), table_name='douyin_publish_tasks')
    op.drop_index(op.f('ix_douyin_publish_tasks_user_id'), table_name='douyin_publish_tasks')
    op.drop_index(op.f('ix_douyin_publish_tasks_id'), table_name='douyin_publish_tasks')
    op.drop_table('douyin_publish_tasks')

    op.drop_index(op.f('ix_douyin_reference_works_provider_work_id'), table_name='douyin_reference_works')
    op.drop_index(op.f('ix_douyin_reference_works_user_id'), table_name='douyin_reference_works')
    op.drop_index(op.f('ix_douyin_reference_works_id'), table_name='douyin_reference_works')
    op.drop_table('douyin_reference_works')

    op.drop_index(op.f('ix_douyin_accounts_user_id'), table_name='douyin_accounts')
    op.drop_index(op.f('ix_douyin_accounts_id'), table_name='douyin_accounts')
    op.drop_table('douyin_accounts')
