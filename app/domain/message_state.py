from __future__ import annotations

from enum import Enum


class MessageState(str, Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    SENDING = "SENDING"
    SENT_TO_CHANNEL = "SENT_TO_CHANNEL"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATION_PENDING = "ESCALATION_PENDING"
    FALLBACK_SENDING = "FALLBACK_SENDING"
    FALLBACK_DELIVERED = "FALLBACK_DELIVERED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"
    ESCALATION_DEFERRED = "ESCALATION_DEFERRED"


_VALID_TRANSITIONS: dict[MessageState, set[MessageState]] = {
    MessageState.PENDING: {MessageState.QUEUED, MessageState.FAILED},
    MessageState.QUEUED: {MessageState.SENDING, MessageState.FAILED},
    MessageState.SENDING: {MessageState.SENT_TO_CHANNEL, MessageState.FAILED},
    MessageState.SENT_TO_CHANNEL: {
        MessageState.ACKNOWLEDGED,
        MessageState.ESCALATION_PENDING,
        MessageState.FAILED,
    },
    MessageState.ACKNOWLEDGED: set(),
    MessageState.ESCALATION_PENDING: {
        MessageState.FALLBACK_SENDING,
        MessageState.ESCALATION_DEFERRED,
        MessageState.FAILED,
    },
    MessageState.FALLBACK_SENDING: {
        MessageState.FALLBACK_DELIVERED,
        MessageState.DEAD_LETTER,
        MessageState.ESCALATION_DEFERRED,
        MessageState.FAILED,
    },
    MessageState.FALLBACK_DELIVERED: set(),
    MessageState.FAILED: set(),
    MessageState.DEAD_LETTER: set(),
    MessageState.ESCALATION_DEFERRED: {
        MessageState.ESCALATION_PENDING,
        MessageState.FAILED,
        MessageState.DEAD_LETTER,
    },
}


def transition_state(current: MessageState, next_state: MessageState) -> MessageState:
    """Restrict updates to the explicit state machine.

    This is intentionally strict: a malformed transition is a bug, not a policy.
    """
    allowed = _VALID_TRANSITIONS.get(current, set())
    if next_state not in allowed:
        raise ValueError(
            f"Illegal state transition: {current.value} -> {next_state.value}. "
            f"Allowed: {[state.value for state in sorted(allowed, key=lambda s: s.value)]}"
        )
    return next_state


def can_record_acknowledgement(current: MessageState) -> bool:
    """Late acknowledgements are still valid fact records even after escalation starts.

    We do not create a dedicated 'late ACK' state. Instead, we record the fact in
    the timestamp field and leave the current_state to reflect the delivery policy's
    current stage. This keeps the state machine explicit and avoids state explosion.
    """
    return current not in {MessageState.ACKNOWLEDGED, MessageState.FALLBACK_DELIVERED, MessageState.FAILED, MessageState.DEAD_LETTER}
