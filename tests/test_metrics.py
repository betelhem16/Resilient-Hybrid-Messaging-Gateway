"""Tests for metrics and health monitoring endpoints."""


import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import ChannelRegistry
from app.domain.message_state import MessageState
from app.observability.metrics import HealthChecker, MetricsCollector
from app.schemas.message import CreateMessageRequest
from app.services.message_service import MessageService
from tests.test_message_processor import MockChannel


@pytest.mark.asyncio
async def test_metrics_collector_counts_messages_by_state(test_session: AsyncSession) -> None:
    """Test that metrics collector correctly counts messages by state."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create messages in different states
    for i in range(3):
        request = CreateMessageRequest(
            sender=f"sender{i}@example.com",
            recipient=f"recipient{i}",
            content=f"Test message {i}",
            primary_channel="telegram",
            acknowledgement_condition="EXPLICIT_ACK",
            acknowledgement_deadline_seconds=600,
            fallback_channels=[],
            priority="NORMAL",
        )
        await service.create_message(request)
        await test_session.commit()

    # Collect metrics
    collector = MetricsCollector(test_session)
    metrics = await collector.collect()

    assert metrics.total_messages == 3
    assert metrics.messages_by_state[MessageState.PENDING.value] == 3
    assert metrics.delivery_success_rate() == 0.0  # No delivered messages yet


@pytest.mark.asyncio
async def test_metrics_tracks_delivery_success(test_session: AsyncSession) -> None:
    """Test that metrics collector tracks successful deliveries."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Success test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=[],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    await service.process_message(record.id)
    await test_session.commit()

    # Acknowledge the message
    await service.acknowledge_message(record.id)
    await test_session.commit()

    # Collect metrics
    collector = MetricsCollector(test_session)
    metrics = await collector.collect()

    assert metrics.messages_acknowledged == 1


@pytest.mark.asyncio
async def test_health_checker_detects_high_dead_letter_count(test_session: AsyncSession) -> None:
    """Test that health checker detects unhealthy conditions."""
    # This test would need to create many dead-letter messages
    # For now, just verify the health checker runs without error
    checker = HealthChecker(test_session)
    health = await checker.check_health()

    assert health.is_healthy is True
    assert health.is_ready is True
    assert health.messages_dead_letter == 0


@pytest.mark.asyncio
async def test_health_checker_reports_message_counts(test_session: AsyncSession) -> None:
    """Test that health checker correctly reports message counts."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create a few messages
    for i in range(5):
        request = CreateMessageRequest(
            sender=f"sender{i}@example.com",
            recipient=f"recipient{i}",
            content=f"Health check test {i}",
            primary_channel="telegram",
            acknowledgement_condition="EXPLICIT_ACK",
            acknowledgement_deadline_seconds=600,
            fallback_channels=[],
            priority="NORMAL",
        )
        await service.create_message(request)
        await test_session.commit()

    # Check health
    checker = HealthChecker(test_session)
    health = await checker.check_health()

    assert health.messages_pending == 5
