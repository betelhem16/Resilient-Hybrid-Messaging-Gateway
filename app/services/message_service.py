from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import ChannelRegistry
from app.domain.message import MessagePolicy, MessageRecord
from app.domain.message_state import MessageState
from app.domain.state_machine import apply_transition
from app.repositories.message_repository import MessageRepository
from app.schemas.message import CreateMessageRequest
from app.workers.processor import MessageProcessor


class MessageService:
    def __init__(
        self,
        session: AsyncSession,
        channels: ChannelRegistry,
    ) -> None:
        self.session = session
        self.channels = channels
        self.repository = MessageRepository(session)
        self.processor = MessageProcessor(session, channels)

    async def create_message(self, payload: CreateMessageRequest) -> MessageRecord:
        if payload.idempotency_key:
            existing = await self.repository.get_by_idempotency_key(payload.idempotency_key)
            if existing is not None:
                return existing

        message_id = str(uuid4())
        now = datetime.now(timezone.utc)

        record = MessageRecord(
            id=message_id,
            sender=payload.sender,
            recipient=payload.recipient,
            content=payload.content,
            policy=MessagePolicy(
                primary_channel=payload.primary_channel,
                acknowledgement_condition=payload.acknowledgement_condition,
                acknowledgement_deadline_seconds=payload.acknowledgement_deadline_seconds,
                fallback_channels=list(payload.fallback_channels),
                priority=payload.priority,
            ),
            current_state=MessageState.PENDING,
            created_at=now,
            updated_at=now,
            idempotency_key=payload.idempotency_key,
        )

        record.arm_deadline(now)
        record = await self.repository.create(record)
        return record

    async def get_message(self, message_id: str) -> MessageRecord | None:
        return await self.repository.get_by_id(message_id)

    async def process_message(self, message_id: str) -> None:
        """Start processing a newly created message.

        This moves it through PENDING → QUEUED → SENDING → SENT_TO_CHANNEL,
        attempting delivery via the primary channel.
        """
        await self.processor.process_new_message(message_id)
        await self.processor.attempt_delivery(message_id)

    async def acknowledge_message(
        self,
        message_id: str,
        acknowledged_at: datetime | None = None,
    ) -> None:
        """Record an acknowledgement for a message."""
        await self.processor.acknowledge_message(message_id, acknowledged_at)
