from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime
