"""add clip_sessions and clip_exports

Revision ID: a9c1e2f3b4d5
Revises: f6a7b8c9d0e1
Create Date: 2026-11-11
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9c1e2f3b4d5"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clip_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("manifest_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="issued"),
        sa.Column("handoff_jti", sa.String(length=64), nullable=False),
        sa.Column("handoff_expires_at", sa.DateTime(), nullable=False),
        sa.Column("session_expires_at", sa.DateTime(), nullable=True),
        sa.Column("exchanged_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_clip_sessions_user_id", "clip_sessions", ["user_id"])
    op.create_index("ix_clip_sessions_status", "clip_sessions", ["status"])
    op.create_index("ix_clip_sessions_handoff_jti", "clip_sessions", ["handoff_jti"], unique=True)
    op.create_index("ix_clip_sessions_handoff_expires_at", "clip_sessions", ["handoff_expires_at"])

    op.create_table(
        "clip_exports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("clip_sessions.id"), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("file_name", sa.String(length=180), nullable=False, unique=True),
        sa.Column("mime", sa.String(length=64), nullable=False, server_default="video/mp4"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
        sa.Column("linked_draft_id", sa.Integer(), sa.ForeignKey("ai_drafts.id"), nullable=True),
        sa.Column("client_export_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("session_id", "client_export_id", name="uq_clip_exports_session_client"),
    )
    op.create_index("ix_clip_exports_user_id", "clip_exports", ["user_id"])
    op.create_index("ix_clip_exports_session_id", "clip_exports", ["session_id"])


def downgrade() -> None:
    op.drop_table("clip_exports")
    op.drop_table("clip_sessions")
