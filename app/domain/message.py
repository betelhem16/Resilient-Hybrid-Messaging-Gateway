from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.domain.message_state import MessageState


@dataclass(slots=True)
class MessagePolicy:
    primary_channel: str
    acknowledgement_condition: str
    acknowledgement_deadline_seconds: int
    fallback_channels: list[str] = field(default_factory=list)
    priority: str = "NORMAL"


@dataclass(slots=True)
class MessageRecord:
    id: str
    sender: str
    recipient: str
    content: str
    policy: MessagePolicy
    current_state: MessageState = MessageState.PENDING
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    external_message_id: str | None = None
    idempotency_key: str | None = None
    retry_count: int = 0
    last_error: str | None = None
    next_retry_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def arm_deadline(self, now: datetime) -> None:
        self.ack_deadline_at = now + timedelta(seconds=self.policy.acknowledgement_deadline_seconds)

    def is_acknowledged(self) -> bool:
        return self.acknowledged_at is not None
