"""add unique idempotency key index

Revision ID: 20260912_000003
Revises: 20260809_000002
Create Date: 2026-09-12 00:00:00.000000

"""
from __future__ import annotations

from alembic import op

revision = "20260912_000003"
down_revision = "20260809_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_messages_idempotency_key",
        "messages",
        ["idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_messages_idempotency_key", table_name="messages")
