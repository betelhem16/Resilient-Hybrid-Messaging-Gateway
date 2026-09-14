"""create messages and events

Revision ID: 20260819_000001
Revises: 
Create Date: 2026-08-19 00:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260819_000001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("primary_channel", sa.String(length=32), nullable=False),
        sa.Column("acknowledgement_condition", sa.String(length=32), nullable=False),
        sa.Column("acknowledgement_deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("fallback_channels", sa.JSON(), nullable=False),
        sa.Column(
            "current_state",
            sa.Enum(
                "PENDING",
                "QUEUED",
                "SENDING",
                "SENT_TO_CHANNEL",
                "ACKNOWLEDGED",
                "ESCALATION_PENDING",
                "FALLBACK_SENDING",
                "FALLBACK_DELIVERED",
                "FAILED",
                "DEAD_LETTER",
                "ESCALATION_DEFERRED",
                name="messagestate",
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ack_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("external_message_id", sa.String(length=128), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_sender"), "messages", ["sender"], unique=False)
    op.create_index(op.f("ix_messages_recipient"), "messages", ["recipient"], unique=False)
    op.create_index(op.f("ix_messages_current_state"), "messages", ["current_state"], unique=False)

    op.create_table(
        "message_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_message_events_message_id"),
        "message_events",
        ["message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_message_events_message_id"), table_name="message_events")
    op.drop_table("message_events")
    op.drop_index(op.f("ix_messages_current_state"), table_name="messages")
    op.drop_index(op.f("ix_messages_recipient"), table_name="messages")
    op.drop_index(op.f("ix_messages_sender"), table_name="messages")
    op.drop_table("messages")
