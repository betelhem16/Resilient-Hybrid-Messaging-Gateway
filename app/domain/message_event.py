from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class MessageEventRecord:
    id: int
    message_id: str
    event_type: str
    payload: dict[str, object]
    created_at: datetime
