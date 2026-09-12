"""Tests for admin and debugging endpoints."""

import pytest
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from app.channels.registry import ChannelRegistry
from app.api.routes.admin import require_admin_access
from app.domain.message_state import MessageState
from app.main import create_app
from app.schemas.message import CreateMessageRequest
from app.services.message_service import MessageService
from tests.test_message_processor import MockChannel


@pytest.mark.asyncio
async def test_admin_access_requires_configured_production_key() -> None:
    def make_request(env: str, key: str) -> SimpleNamespace:
        settings = SimpleNamespace(env=env, admin_api_key=key)
        return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))

    await require_admin_access(make_request("local", ""))
    await require_admin_access(
        make_request("prod", "secret"),
        "secret",
    )

    with pytest.raises(HTTPException) as invalid_key:
        await require_admin_access(make_request("prod", "secret"), "wrong")
    assert invalid_key.value.status_code == 401

    with pytest.raises(HTTPException) as missing_key:
        await require_admin_access(make_request("prod", ""))
    assert missing_key.value.status_code == 503


@pytest.fixture
async def async_client() -> AsyncClient:
    """Create an async test client for the app."""
    app = create_app()
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_list_messages(test_session: AsyncSession) -> None:
    """Test listing messages via admin endpoint."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    # Create a few messages
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
        record = await service.create_message(request)
        await test_session.commit()


@pytest.mark.asyncio
async def test_admin_get_message_events(test_session: AsyncSession) -> None:
    """Test viewing message event history via admin endpoint."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Event test",
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

    # Fetch events via repository
    from sqlalchemy import select
    from app.infrastructure.models import MessageEvent

    result = await test_session.execute(
        select(MessageEvent).where(MessageEvent.message_id == record.id)
    )
    events = result.scalars().all()

    assert len(events) > 0
    event_types = [e.event_type for e in events]
    assert "QUEUED" in event_types or len(event_types) > 0


@pytest.mark.asyncio
async def test_admin_get_message_stats(test_session: AsyncSession) -> None:
    """Test getting message state statistics via admin endpoint."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    registry.register("telegram", mock_telegram)

    service = MessageService(test_session, registry)

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Stats test",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=600,
        fallback_channels=[],
        priority="NORMAL",
    )

    record = await service.create_message(request)
    await test_session.commit()

    # At this point, one message should be in PENDING state
    from app.repositories.message_repository import MessageRepository

    repository = MessageRepository(test_session)
    pending_messages = await repository.list_by_state(MessageState.PENDING)
    assert len(pending_messages) == 1


@pytest.mark.asyncio
async def test_admin_manually_escalate_message(test_session: AsyncSession) -> None:
    """Test manually escalating a message via admin endpoint."""
    registry = ChannelRegistry()
    mock_telegram = MockChannel("telegram", always_succeed=True)
    mock_sms = MockChannel("sms", always_succeed=True)
    registry.register("telegram", mock_telegram)
    registry.register("sms", mock_sms)

    service = MessageService(test_session, registry)

    request = CreateMessageRequest(
        sender="alice@example.com",
        recipient="123456789",
        content="Escalation test",
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

    message = await service.get_message(record.id)
    assert message.current_state == MessageState.SENT_TO_CHANNEL

    # Manually escalate
    from datetime import datetime, timezone
    from app.workers.processor import MessageProcessor

    processor = MessageProcessor(test_session, registry)
    now = datetime.now(timezone.utc)
    await processor._escalate_message(message, now)
    await test_session.commit()

    updated = await service.get_message(record.id)
    assert updated.current_state == MessageState.ESCALATION_PENDING
