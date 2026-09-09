from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, DeclarativeBase, mapped_column, relationship

from app.domain.message_state import MessageState


class Base(DeclarativeBase):
    pass


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sender: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False)
    primary_channel: Mapped[str] = mapped_column(String(32), nullable=False)
    acknowledgement_condition: Mapped[str] = mapped_column(String(32), nullable=False)
    acknowledgement_deadline_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_channels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    current_state: Mapped[MessageState] = mapped_column(
        Enum(MessageState), default=MessageState.PENDING, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ack_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    events: Mapped[list["MessageEvent"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="MessageEvent.created_at.asc()",
    )


class MessageEvent(Base):
    __tablename__ = "message_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped[Message] = relationship(back_populates="events")
