from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.message import MessageRecord
from app.domain.message_state import MessageState


def default_fallback_channels() -> list[Literal["sms"]]:
    return ["sms"]


class CreateMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sender: str = Field(..., min_length=1, max_length=255)
    recipient: str = Field(..., min_length=1, max_length=255)
    content: str = Field(..., min_length=1, max_length=4000)
    priority: Literal["CRITICAL", "NORMAL"] = "NORMAL"
    primary_channel: Literal["telegram", "sms"] = "telegram"
    acknowledgement_condition: Literal["EXPLICIT_ACK"] = "EXPLICIT_ACK"
    acknowledgement_deadline_seconds: int = Field(..., ge=1, le=86400)
    fallback_channels: list[Literal["sms"]] = Field(default_factory=default_fallback_channels)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    sender: str
    recipient: str
    content: str
    priority: str
    primary_channel: str
    acknowledgement_condition: str
    acknowledgement_deadline_seconds: int
    fallback_channels: list[str]
    current_state: MessageState
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    escalated_at: datetime | None = None
    ack_deadline_at: datetime | None = None
    external_message_id: str | None = None
    retry_count: int = 0
    last_error: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_record(cls, value: object) -> object:
        if isinstance(value, MessageRecord):
            return {
                "id": value.id,
                "sender": value.sender,
                "recipient": value.recipient,
                "content": value.content,
                "priority": value.policy.priority,
                "primary_channel": value.policy.primary_channel,
                "acknowledgement_condition": value.policy.acknowledgement_condition,
                "acknowledgement_deadline_seconds": value.policy.acknowledgement_deadline_seconds,
                "fallback_channels": value.policy.fallback_channels,
                "current_state": value.current_state,
                "created_at": value.created_at,
                "updated_at": value.updated_at,
                "sent_at": value.sent_at,
                "acknowledged_at": value.acknowledged_at,
                "escalated_at": value.escalated_at,
                "ack_deadline_at": value.ack_deadline_at,
                "external_message_id": value.external_message_id,
                "retry_count": value.retry_count,
                "last_error": value.last_error,
            }
        return value

    @classmethod
    def from_record(cls, record: MessageRecord) -> "MessageResponse":
        return cls(
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
            created_at=record.created_at,
            updated_at=record.updated_at,
            sent_at=record.sent_at,
            acknowledged_at=record.acknowledged_at,
            escalated_at=record.escalated_at,
            ack_deadline_at=record.ack_deadline_at,
            external_message_id=record.external_message_id,
            retry_count=record.retry_count,
            last_error=record.last_error,
        )
