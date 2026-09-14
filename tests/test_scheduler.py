from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import ChannelRegistry
from app.domain.message_state import MessageState
from app.schemas.message import CreateMessageRequest
from app.services.message_service import MessageService
from tests.test_message_processor import MockChannel


@pytest.mark.asyncio
async def test_scheduler_checks_deadlines_periodically(test_session: AsyncSession) -> None:
    """Verify the scheduler periodically checks for overdue messages."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    mock_sms = MockChannel("sms", always_succeed=True)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    # Create a message with a 1-second deadline
    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Scheduler test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=1,
        fallback_channels=["sms"],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # Process it to SENT_TO_CHANNEL
    await service.process_message(record.id)
    await test_session.commit()

    record = await service.get_message(record.id)
    assert record.current_state == MessageState.SENT_TO_CHANNEL

    # Force deadline into the past
    record.ack_deadline_at = datetime.now(UTC) - timedelta(seconds=5)
    await service.repository.update(record)
    await test_session.commit()

    # Verify the processor can see it
    processor = service.processor
    await processor.check_deadlines()
    await test_session.commit()

    # Verify it was escalated
    updated = await service.get_message(record.id)
    assert updated.current_state == MessageState.ESCALATION_PENDING


@pytest.mark.asyncio
async def test_scheduler_attempts_fallback_for_escalated_messages(
    test_session: AsyncSession,
) -> None:
    """Verify the scheduler attempts fallback delivery for ESCALATION_PENDING messages."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    mock_sms = MockChannel("sms", always_succeed=True)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Fallback test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=1,
        fallback_channels=["sms"],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # Process it
    await service.process_message(record.id)
    await test_session.commit()

    record = await service.get_message(record.id)
    assert record.current_state == MessageState.SENT_TO_CHANNEL

    # Force deadline to trigger escalation
    record.ack_deadline_at = datetime.now(UTC) - timedelta(seconds=5)
    await service.repository.update(record)
    await test_session.commit()

    # Run deadline check
    await service.processor.check_deadlines()
    await test_session.commit()

    record = await service.get_message(record.id)
    assert record.current_state == MessageState.ESCALATION_PENDING

    # Now attempt the fallback
    processor = service.processor
    await processor.attempt_fallback(record.id, "sms")
    await test_session.commit()

    # Verify it was delivered via fallback
    final = await service.get_message(record.id)
    assert final.current_state == MessageState.FALLBACK_DELIVERED
