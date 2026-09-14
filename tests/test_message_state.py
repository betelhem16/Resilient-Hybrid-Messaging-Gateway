import pytest

from app.domain.message_state import MessageState, can_record_acknowledgement, transition_state


def test_valid_transition_sequence() -> None:
    assert transition_state(MessageState.PENDING, MessageState.QUEUED) == MessageState.QUEUED
    assert transition_state(MessageState.QUEUED, MessageState.SENDING) == MessageState.SENDING
    assert (
        transition_state(MessageState.SENDING, MessageState.SENT_TO_CHANNEL)
        == MessageState.SENT_TO_CHANNEL
    )
    assert (
        transition_state(MessageState.SENT_TO_CHANNEL, MessageState.ACKNOWLEDGED)
        == MessageState.ACKNOWLEDGED
    )


def test_escalation_sequence_is_valid() -> None:
    assert (
        transition_state(MessageState.SENT_TO_CHANNEL, MessageState.ESCALATION_PENDING)
        == MessageState.ESCALATION_PENDING
    )
    assert (
        transition_state(MessageState.ESCALATION_PENDING, MessageState.FALLBACK_SENDING)
        == MessageState.FALLBACK_SENDING
    )
    assert (
        transition_state(MessageState.FALLBACK_SENDING, MessageState.FALLBACK_DELIVERED)
        == MessageState.FALLBACK_DELIVERED
    )


def test_invalid_transition_is_rejected() -> None:
    with pytest.raises(ValueError):
        transition_state(MessageState.SENT_TO_CHANNEL, MessageState.QUEUED)

    with pytest.raises(ValueError):
        transition_state(MessageState.ACKNOWLEDGED, MessageState.ESCALATION_PENDING)


def test_late_ack_recording_is_allowed_even_after_escalation_has_started() -> None:
    assert can_record_acknowledgement(MessageState.SENT_TO_CHANNEL) is True
    assert can_record_acknowledgement(MessageState.ESCALATION_PENDING) is True
    assert can_record_acknowledgement(MessageState.FALLBACK_SENDING) is True
    assert can_record_acknowledgement(MessageState.ACKNOWLEDGED) is False
