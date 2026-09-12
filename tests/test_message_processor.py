"""Integration tests for the message processor.

These tests verify the entire lifecycle: creation, delivery, acknowledgement,
escalation, and fallback handling.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.base import Channel, SendResult
from app.channels.registry import ChannelRegistry
from app.domain.message_state import MessageState
from app.services.message_service import MessageService
from app.workers.events import EventType


class MockChannel(Channel):
    """Mock channel for testing without external dependencies."""

    def __init__(self, name: str, always_succeed: bool = True) -> None:
        self.channel_name = name
        self.always_succeed = always_succeed
        self.call_count = 0
        self.last_payload = None

    async def send(self, recipient: str, content: str, metadata: dict | None = None) -> SendResult:
        self.call_count += 1
        self.last_payload = {
            "recipient": recipient,
            "content": content,
            "metadata": metadata,
        }

        if self.always_succeed:
            return SendResult(
                success=True,
                channel=self.channel_name,
                external_message_id=f"{self.channel_name}_msg_{self.call_count}",
            )
        else:
            return SendResult(
                success=False,
                channel=self.channel_name,
                error=f"Mock {self.channel_name} send failed",
            )


@pytest.mark.asyncio
async def test_message_creation_and_delivery_flow(test_session: AsyncSession) -> None:
    """Test the happy path: create → queue → send → acknowledge."""
    # Setup
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create message
    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Hello, World!",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=["sms"],
        priority="CRITICAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # Verify initial state
    assert record.current_state == MessageState.PENDING
    assert record.ack_deadline_at is not None

    # Process the message (queue + attempt delivery)
    await service.process_message(record.id)
    await test_session.commit()

    # Verify state transitioned to SENT_TO_CHANNEL
    final_record = await service.get_message(record.id)
    assert final_record is not None
    assert final_record.current_state == MessageState.SENT_TO_CHANNEL
    assert final_record.sent_at is not None
    assert final_record.external_message_id is not None

    # Verify channel was called
    assert mock_telegram.call_count == 1
    assert mock_telegram.last_payload["recipient"] == "123456789"

    # Now acknowledge the message
    await service.acknowledge_message(final_record.id)
    await test_session.commit()

    # Verify final state
    acked_record = await service.get_message(record.id)
    assert acked_record is not None
    assert acked_record.current_state == MessageState.ACKNOWLEDGED
    assert acked_record.acknowledged_at is not None


@pytest.mark.asyncio
async def test_primary_channel_failure_escalates_to_fallback(test_session: AsyncSession) -> None:
    """Test that a failed primary send triggers escalation to fallback channel."""
    # Setup
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=False)
    mock_sms = MockChannel("sms", always_succeed=True)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    # Create message with SMS as fallback
    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Important alert",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=["sms"],
        priority="CRITICAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # Process (this will fail on primary and escalate to fallback)
    await service.process_message(record.id)
    await test_session.commit()

    # Verify primary channel was attempted and failed
    assert mock_telegram.call_count == 1

    # Verify message is now in ESCALATION_PENDING (not FAILED)
    escalated_record = await service.get_message(record.id)
    assert escalated_record is not None
    assert escalated_record.current_state == MessageState.ESCALATION_PENDING
    assert escalated_record.escalated_at is not None

    # Attempt fallback
    await service.processor.attempt_fallback(record.id, "sms")
    await test_session.commit()

    # Verify fallback was successful
    final_record = await service.get_message(record.id)
    assert final_record is not None
    assert final_record.current_state == MessageState.FALLBACK_DELIVERED
    assert mock_sms.call_count == 1


@pytest.mark.asyncio
async def test_missing_channel_marks_dead_letter(test_session: AsyncSession) -> None:
    """Test that an unavailable channel sends the message to dead-letter."""
    # Setup with empty registry
    registry = ChannelRegistry()
    service = MessageService(test_session, registry)

    # Create message with unavailable channel
    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="nobody",
        content="Test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=[],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # Try to process
    await service.process_message(record.id)
    await test_session.commit()

    # Verify it failed to find channel
    result = await service.get_message(record.id)
    assert result is not None
    assert result.current_state == MessageState.FAILED
    assert "not available" in result.last_error.lower()


@pytest.mark.asyncio
async def test_late_acknowledgement_recorded(test_session: AsyncSession) -> None:
    """Test that acknowledging a message after escalation is recorded as a fact."""
    # Setup
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create and deliver message
    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Check this out",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=["sms"],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()
    await service.process_message(record.id)
    await test_session.commit()

    # Escalate the message
    escalated = await service.get_message(record.id)
    assert escalated is not None
    await service.processor._escalate_message(escalated, datetime.now(timezone.utc))
    await test_session.commit()

    # Verify it's now in ESCALATION_PENDING
    pre_ack = await service.get_message(record.id)
    assert pre_ack.current_state == MessageState.ESCALATION_PENDING

    # Now acknowledge (late)
    await service.acknowledge_message(record.id)
    await test_session.commit()

    # Verify late ack was recorded but state didn't change
    final = await service.get_message(record.id)
    assert final.acknowledged_at is not None
    assert final.current_state == MessageState.ESCALATION_PENDING  # State unchanged


@pytest.mark.asyncio
async def test_event_recording(test_session: AsyncSession) -> None:
    """Test that all lifecycle events are recorded."""
    # Setup
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create message
    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Test events",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=[],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    message_id = record.id
    await test_session.commit()

    # Process
    await service.process_message(message_id)
    await test_session.commit()

    # Acknowledge
    await service.acknowledge_message(message_id)
    await test_session.commit()

    # Fetch events
    from sqlalchemy import select
    from app.infrastructure.models import MessageEvent

    result = await test_session.execute(
        select(MessageEvent).where(MessageEvent.message_id == message_id).order_by(MessageEvent.id)
    )
    events = result.scalars().all()

    # Verify event types
    event_types = [e.event_type for e in events]
    assert EventType.QUEUED in event_types
    assert EventType.SENDING in event_types
    assert EventType.SEND_ATTEMPT in event_types
    assert EventType.SEND_SUCCESS in event_types
    assert EventType.ACK_RECEIVED in event_types


@pytest.mark.asyncio
async def test_deadline_check_escalates_when_ack_deadline_passes(test_session: AsyncSession) -> None:
    """Messages past their deadline should be escalated when no ack has arrived."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    mock_sms = MockChannel("sms", always_succeed=True)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Deadline test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=1,
        fallback_channels=["sms"],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    await service.process_message(record.id)
    await test_session.commit()

    record = await service.get_message(record.id)
    assert record is not None
    assert record.current_state == MessageState.SENT_TO_CHANNEL

    # Force the deadline into the past so the processor sees it as expired.
    record.ack_deadline_at = datetime.now(timezone.utc) - timedelta(seconds=5)
    await service.repository.update(record)
    await test_session.commit()

    await service.processor.check_deadlines()
    await test_session.commit()

    updated = await service.get_message(record.id)
    assert updated is not None
    assert updated.current_state == MessageState.ESCALATION_PENDING
    assert updated.escalated_at is not None


@pytest.mark.asyncio
async def test_failed_fallback_schedules_retry_and_recovers(test_session: AsyncSession) -> None:
    """A temporary fallback failure should be deferred, then recover on retry."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=False)
    mock_sms = MockChannel("sms", always_succeed=False)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alerts",
        recipient="123456789",
        content="Retry test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=["sms"],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()
    await service.process_message(record.id)
    await test_session.commit()

    await service.processor.attempt_fallback(record.id, "sms")
    await test_session.commit()

    deferred = await service.get_message(record.id)
    assert deferred is not None
    assert deferred.current_state == MessageState.ESCALATION_DEFERRED
    assert deferred.retry_count == 1
    assert deferred.next_retry_at is not None
    assert deferred.next_retry_at > datetime.now(timezone.utc).replace(tzinfo=None)

    # Simulate the scheduler making the deferred message eligible again.
    await service.processor._escalate_message(deferred, datetime.now(timezone.utc))
    mock_sms.always_succeed = True
    await service.processor.attempt_fallback(record.id, "sms")
    await test_session.commit()

    recovered = await service.get_message(record.id)
    assert recovered is not None
    assert recovered.current_state == MessageState.FALLBACK_DELIVERED
    assert mock_sms.call_count == 2


@pytest.mark.asyncio
async def test_idempotency_key_returns_existing_message(test_session: AsyncSession) -> None:
    """Repeated submissions with one key must not create duplicate messages."""
    registry = ChannelRegistry()
    service = MessageService(test_session, registry)

    from app.schemas.message import CreateMessageRequest

    request = CreateMessageRequest(
        sender="alerts",
        recipient="123456789",
        content="Duplicate-safe alert",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=[],
        idempotency_key="alert-123",
        priority="NORMAL",
    )

    first = await service.create_message(request)
    await test_session.commit()
    second = await service.create_message(request)

    assert second.id == first.id
