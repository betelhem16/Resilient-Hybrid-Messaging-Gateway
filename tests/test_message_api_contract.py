from app.domain.message import MessagePolicy, MessageRecord
from app.domain.message_state import MessageState
from app.schemas.message import CreateMessageRequest, MessageResponse


def test_create_message_request_validates_policy_fields() -> None:
    payload = CreateMessageRequest(
        sender="ops@example.com",
        recipient="123456789",
        content="Production database is down.",
        priority="CRITICAL",
        primary_channel="telegram",
        acknowledgement_condition="EXPLICIT_ACK",
        acknowledgement_deadline_seconds=300,
        fallback_channels=["sms"],
    )

    assert payload.priority == "CRITICAL"
    assert payload.primary_channel == "telegram"
    assert payload.acknowledgement_condition == "EXPLICIT_ACK"
    assert payload.acknowledgement_deadline_seconds == 300


def test_message_response_represents_durable_record() -> None:
    record = MessageRecord(
        id="msg-123",
        sender="ops@example.com",
        recipient="123456789",
        content="Production database is down.",
        policy=MessagePolicy(
            primary_channel="telegram",
            acknowledgement_condition="EXPLICIT_ACK",
            acknowledgement_deadline_seconds=300,
            fallback_channels=["sms"],
            priority="CRITICAL",
        ),
        current_state=MessageState.PENDING,
    )

    response = MessageResponse.model_validate(record)

    assert response.id == "msg-123"
    assert response.current_state == MessageState.PENDING
    assert response.primary_channel == "telegram"
    assert response.acknowledgement_condition == "EXPLICIT_ACK"
