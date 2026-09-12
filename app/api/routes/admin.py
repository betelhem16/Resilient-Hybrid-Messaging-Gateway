"""Admin and debugging endpoints for operational visibility.

These routes provide inspection and manual intervention capabilities
for message processing workflows. They're intended for operations staff
and should be gated behind authentication in production.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain.message_state import MessageState
from app.infrastructure.database import get_session
from app.infrastructure.models import Message, MessageEvent
from app.repositories.message_repository import MessageRepository
from app.schemas.message import MessageResponse

async def require_admin_access(
    request: Request,
    x_admin_api_key: str | None = Header(default=None),
) -> None:
    """Require the configured admin key in production and when configured."""
    settings: Settings = request.app.state.settings
    if not settings.admin_api_key and settings.env == "prod":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="admin API key is not configured",
        )
    if settings.admin_api_key and x_admin_api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin API key",
        )


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_access)],
)


@router.get("/messages", status_code=status.HTTP_200_OK)
async def list_messages(
    state: str | None = Query(None, description="Filter by message state"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[MessageResponse]:
    """List messages, optionally filtered by state.

    Args:
        state: Message state to filter by (e.g., 'SENT_TO_CHANNEL', 'ESCALATION_PENDING')
        limit: Number of messages to return (max 100)

    Returns:
        List of message records
    """
    query = select(Message)

    if state:
        try:
            state_enum = MessageState(state)
            query = query.where(Message.current_state == state_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid state: {state}",
            )

    query = query.order_by(Message.created_at.desc()).limit(limit)

    result = await session.execute(query)
    messages = result.scalars().all()

    repository = MessageRepository(session)
    return [MessageResponse.from_record(repository._to_record(m)) for m in messages]


@router.get("/messages/{message_id}/events", status_code=status.HTTP_200_OK)
async def get_message_events(
    message_id: str,
    limit: int = Query(50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Retrieve all events for a message.

    This provides the complete audit trail of state transitions and lifecycle events.

    Args:
        message_id: The message ID
        limit: Maximum number of events to return

    Returns:
        List of events with timestamps and payloads
    """
    # Verify the message exists
    repository = MessageRepository(session)
    message = await repository.get_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    # Fetch events
    result = await session.execute(
        select(MessageEvent)
        .where(MessageEvent.message_id == message_id)
        .order_by(MessageEvent.created_at.asc())
        .limit(limit)
    )

    events = result.scalars().all()

    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "payload": e.payload,
        }
        for e in events
    ]


@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_message_stats(session: AsyncSession = Depends(get_session)) -> dict[str, int]:
    """Get statistics on message states.

    Returns a count of messages in each state.
    """
    stats = {}

    for state in MessageState:
        result = await session.execute(
            select(Message).where(Message.current_state == state)
        )
        count = len(result.scalars().all())
        stats[state.value] = count

    return stats


@router.post("/messages/{message_id}/escalate", status_code=status.HTTP_200_OK)
async def manually_escalate_message(
    message_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Manually escalate a message to fallback delivery.

    This is useful for testing or recovering from edge cases.

    Args:
        message_id: The message ID to escalate

    Returns:
        Updated message record
    """
    from datetime import datetime, timezone
    from app.domain.state_machine import apply_transition, StateTransitionError
    from app.workers.processor import MessageProcessor

    repository = MessageRepository(session)
    message = await repository.get_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    if message.current_state != MessageState.SENT_TO_CHANNEL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot escalate from state {message.current_state.value}",
        )

    # Trigger escalation
    channels = request.app.state.channels
    processor = MessageProcessor(session, channels)
    now = datetime.now(timezone.utc)

    try:
        await processor._escalate_message(message, now)
        await session.commit()
    except StateTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    updated = await repository.get_by_id(message_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")
    return MessageResponse.from_record(updated)


@router.post("/messages/{message_id}/retry-fallback", status_code=status.HTTP_200_OK)
async def retry_fallback_delivery(
    message_id: str,
    request: Request,
    channel: str = Query(..., description="Fallback channel to attempt"),
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Manually attempt fallback delivery via a specific channel.

    Args:
        message_id: The message ID
        channel: The fallback channel to attempt

    Returns:
        Updated message record
    """
    from app.workers.processor import MessageProcessor

    repository = MessageRepository(session)
    message = await repository.get_by_id(message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")

    if message.current_state != MessageState.ESCALATION_PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message must be in ESCALATION_PENDING state, currently {message.current_state.value}",
        )

    # Attempt the fallback
    channels = request.app.state.channels
    processor = MessageProcessor(session, channels)

    try:
        await processor.attempt_fallback(message_id, channel)
        await session.commit()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    updated = await repository.get_by_id(message_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")
    return MessageResponse.from_record(updated)
