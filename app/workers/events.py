from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.models import MessageEvent


class EventRecorder:
    """Records lifecycle events for audit and debugging.

    Every important action (send attempt, ack received, escalation triggered, etc.)
    is recorded as an immutable fact. This forms the audit trail and enables
    deep debugging of delivery issues.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        message_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Record an event for a message.

        Args:
            message_id: the message this event belongs to
            event_type: type of event (send_attempt, ack_received, escalation_triggered, etc.)
            payload: optional structured data about the event
        """
        event = MessageEvent(
            message_id=message_id,
            event_type=event_type,
            payload=payload or {},
            created_at=datetime.now(UTC),
        )
        self.session.add(event)
        await self.session.flush()


class EventType:
    """Standardized event type constants.

    Using string constants here prevents typos and makes it easy to search
    the codebase for specific event types.
    """

    CREATED = "created"
    QUEUED = "queued"
    SENDING = "sending"
    SEND_ATTEMPT = "send_attempt"
    SEND_SUCCESS = "send_success"
    SEND_FAILED = "send_failed"
    ACK_RECEIVED = "ack_received"
    ESCALATION_TRIGGERED = "escalation_triggered"
    ESCALATION_DEFERRED = "escalation_deferred"
    FALLBACK_ATTEMPT = "fallback_attempt"
    FALLBACK_SUCCESS = "fallback_success"
    FALLBACK_FAILED = "fallback_failed"
    DEADLINE_PASSED = "deadline_passed"
    STATE_TRANSITION = "state_transition"
    DEAD_LETTER = "dead_letter"
