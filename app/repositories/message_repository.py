from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.message import MessagePolicy, MessageRecord
from app.domain.message_state import MessageState
from app.infrastructure.models import Message


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, record: MessageRecord) -> MessageRecord:
        db_message = Message(
            id=record.id,
            sender=record.sender,
            recipient=record.recipient,
            content=record.content,
            priority=record.policy.priority,
            primary_channel=record.policy.primary_channel,
            acknowledgement_condition=record.policy.acknowledgement_condition,
            acknowledgement_deadline_seconds=record.policy.acknowledgement_deadline_seconds,
            fallback_channels=record.policy.fallback_channels,
            current_state=record.current_state,
            created_at=record.created_at or datetime.utcnow(),
            updated_at=record.updated_at or datetime.utcnow(),
            sent_at=record.sent_at,
            acknowledged_at=record.acknowledged_at,
            escalated_at=record.escalated_at,
            ack_deadline_at=record.ack_deadline_at,
            idempotency_key=record.idempotency_key,
            external_message_id=record.external_message_id,
            retry_count=record.retry_count,
            last_error=record.last_error,
            next_retry_at=record.next_retry_at,
        )
        self.session.add(db_message)
        await self.session.flush()
        return record

    async def get_by_id(self, message_id: str) -> MessageRecord | None:
        result = await self.session.execute(select(Message).where(Message.id == message_id))
        db_message = result.scalar_one_or_none()
        if db_message is None:
            return None
        return self._to_record(db_message)

    def _to_record(self, db_message: Message) -> MessageRecord:
        return MessageRecord(
            id=db_message.id,
            sender=db_message.sender,
            recipient=db_message.recipient,
            content=db_message.content,
            policy=MessagePolicy(
                primary_channel=db_message.primary_channel,
                acknowledgement_condition=db_message.acknowledgement_condition,
                acknowledgement_deadline_seconds=db_message.acknowledgement_deadline_seconds,
                fallback_channels=list(db_message.fallback_channels),
                priority=db_message.priority,
            ),
            current_state=db_message.current_state,
            created_at=db_message.created_at,
            updated_at=db_message.updated_at,
            sent_at=db_message.sent_at,
            acknowledged_at=db_message.acknowledged_at,
            escalated_at=db_message.escalated_at,
            ack_deadline_at=db_message.ack_deadline_at,
            external_message_id=db_message.external_message_id,
            idempotency_key=db_message.idempotency_key,
            retry_count=db_message.retry_count,
            last_error=db_message.last_error,
            next_retry_at=db_message.next_retry_at,
        )

    async def update(self, record: MessageRecord) -> MessageRecord:
        result = await self.session.execute(select(Message).where(Message.id == record.id))
        db_message = result.scalar_one_or_none()
        if db_message is None:
            raise ValueError(f"Message {record.id} not found")

        db_message.sender = record.sender
        db_message.recipient = record.recipient
        db_message.content = record.content
        db_message.priority = record.policy.priority
        db_message.primary_channel = record.policy.primary_channel
        db_message.acknowledgement_condition = record.policy.acknowledgement_condition
        db_message.acknowledgement_deadline_seconds = record.policy.acknowledgement_deadline_seconds
        db_message.fallback_channels = record.policy.fallback_channels
        db_message.current_state = record.current_state
        db_message.updated_at = record.updated_at or datetime.utcnow()
        db_message.sent_at = record.sent_at
        db_message.acknowledged_at = record.acknowledged_at
        db_message.escalated_at = record.escalated_at
        db_message.ack_deadline_at = record.ack_deadline_at
        db_message.external_message_id = record.external_message_id
        db_message.idempotency_key = record.idempotency_key
        db_message.retry_count = record.retry_count
        db_message.last_error = record.last_error
        db_message.next_retry_at = record.next_retry_at

        await self.session.flush()
        return record

    async def list_due_for_escalation(self, now: datetime) -> list[MessageRecord]:
        result = await self.session.execute(
            select(Message)
            .where(Message.current_state == MessageState.SENT_TO_CHANNEL)
            .where(Message.acknowledged_at.is_(None))
            .where(Message.ack_deadline_at.is_not(None))
            .where(Message.ack_deadline_at < now)
        )
        return [self._to_record(message) for message in result.scalars().all()]

    async def list_by_state(self, state: MessageState) -> list[MessageRecord]:
        """Fetch all messages in a given state."""
        result = await self.session.execute(
            select(Message).where(Message.current_state == state)
        )
        return [self._to_record(message) for message in result.scalars().all()]

    async def list_due_for_retry(self, now: datetime) -> list[MessageRecord]:
        """Fetch all messages that are due for a retry attempt.

        Returns messages where next_retry_at <= now.
        """
        result = await self.session.execute(
            select(Message)
            .where(Message.next_retry_at.is_not(None))
            .where(Message.next_retry_at <= now)
        )
        return [self._to_record(message) for message in result.scalars().all()]
