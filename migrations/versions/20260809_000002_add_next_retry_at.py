"""add next_retry_at column

Revision ID: 20260809_000002
Revises: 20260819_000001
Create Date: 2026-08-09 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260809_000002"
down_revision = "20260819_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_messages_next_retry_at"),
        "messages",
        ["next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_next_retry_at"), table_name="messages")
    op.drop_column("messages", "next_retry_at")
