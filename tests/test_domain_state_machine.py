from datetime import datetime, timedelta, timezone

import pytest

from app.domain.message import MessagePolicy, MessageRecord
from app.domain.message_state import MessageState
from app.domain.state_machine import StateTransitionError, apply_transition, record_acknowledgement


def make_message() -> MessageRecord:
    return MessageRecord(
        id="msg-1",
        sender="ops@example.com",
        recipient="123456789",
        content="Database is down",
        policy=MessagePolicy(
            primary_channel="telegram",
            acknowledgement_condition="EXPLICIT_ACK",
            acknowledgement_deadline_seconds=300,
            fallback_channels=["sms"],
            priority="CRITICAL",
        ),
        current_state=MessageState.PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def test_state_machine_accepts_valid_path() -> None:
    message = make_message()
    apply_transition(message, MessageState.QUEUED, now=datetime.now(timezone.utc))
    apply_transition(message, MessageState.SENDING, now=datetime.now(timezone.utc))
    apply_transition(message, MessageState.SENT_TO_CHANNEL, now=datetime.now(timezone.utc))
    assert message.current_state == MessageState.SENT_TO_CHANNEL


def test_state_machine_rejects_invalid_transition() -> None:
    message = make_message()
    with pytest.raises(StateTransitionError):
        apply_transition(message, MessageState.ACKNOWLEDGED, now=datetime.now(timezone.utc))


def test_record_acknowledgement_works_after_escalation_starts() -> None:
    message = make_message()
    message.current_state = MessageState.ESCALATION_PENDING
    message.acknowledged_at = None
    now = datetime.now(timezone.utc)
    record_acknowledgement(message, now=now)
    assert message.acknowledged_at == now


def test_deadline_can_be_armed() -> None:
    message = make_message()
    now = datetime.now(timezone.utc)
    message.arm_deadline(now)
    assert message.ack_deadline_at == now + timedelta(seconds=300)
