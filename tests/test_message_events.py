from datetime import datetime, timezone

from app.domain.message_event import MessageEventRecord
from app.schemas.message_event import MessageEventResponse


def test_message_event_response_serializes_payload() -> None:
    event = MessageEventRecord(
        id=1,
        message_id="msg-123",
        event_type="MESSAGE_CREATED",
        payload={"state": "PENDING", "sender": "ops@example.com"},
        created_at=datetime.now(timezone.utc),
    )

    response = MessageEventResponse.model_validate(event)

    assert response.id == 1
    assert response.message_id == "msg-123"
    assert response.event_type == "MESSAGE_CREATED"
    assert response.payload["state"] == "PENDING"
