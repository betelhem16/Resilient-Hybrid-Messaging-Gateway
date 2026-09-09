from __future__ import annotations

from datetime import datetime

from app.domain.message import MessageRecord
from app.domain.message_state import MessageState, can_record_acknowledgement, transition_state


class StateTransitionError(ValueError):
    pass


def apply_transition(message: MessageRecord, next_state: MessageState, *, now: datetime | None = None) -> MessageRecord:
    """Guarded state progression for the message lifecycle.

    We intentionally keep this as a pure domain function: no database access, no
    Redis access, no network I/O. That makes it easy to reason about and unit-test.
    """
    current = message.current_state
    try:
        message.current_state = transition_state(current, next_state)
    except ValueError as exc:
        raise StateTransitionError(str(exc)) from exc

    if now is not None:
        message.updated_at = now

    if next_state == MessageState.ACKNOWLEDGED:
        message.acknowledged_at = now or datetime.utcnow()
    elif next_state == MessageState.ESCALATION_PENDING:
        message.escalated_at = now or datetime.utcnow()

    return message


def record_acknowledgement(message: MessageRecord, *, now: datetime | None = None) -> MessageRecord:
    """A late ack is still a fact; it does not require a new state.

    The caller is responsible for deciding whether this should be persisted or
    ignored based on the current state's transition guard.
    """
    if not can_record_acknowledgement(message.current_state):
        raise StateTransitionError(f"Ack cannot be recorded while state is {message.current_state.value}")
    message.acknowledged_at = now or datetime.utcnow()
    message.updated_at = now or datetime.utcnow()
    return message
