from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import get_session
from app.schemas.message import CreateMessageRequest, MessageResponse
from app.services.message_service import MessageService

router = APIRouter(prefix="/messages", tags=["messages"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_message(
    payload: CreateMessageRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    channels = request.app.state.channels
    service = MessageService(session, channels)
    record = await service.create_message(payload)
    await session.commit()

    # Kick off processing immediately (in production, this would be async via a queue)
    await service.process_message(record.id)
    await session.commit()

    return MessageResponse.from_record(record)


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    channels = request.app.state.channels
    service = MessageService(session, channels)
    record = await service.get_message(message_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="message not found")
    return MessageResponse.from_record(record)
