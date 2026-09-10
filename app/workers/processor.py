from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import ChannelRegistry
from app.domain.message import MessageRecord
from app.domain.message_state import MessageState
from app.domain.retry_policy import FALLBACK_RETRY_POLICY
from app.domain.state_machine import apply_transition, StateTransitionError
from app.repositories.message_repository import MessageRepository
from app.workers.events import EventRecorder, EventType

logger = logging.getLogger(__name__)


class MessageProcessor:
    """Orchestrates message delivery, state transitions, and escalation.

    This is the core business logic engine. It:
    1. Fetches messages ready for processing
    2. Attempts delivery through the primary channel
    3. Records outcomes as events
    4. Manages state transitions
    5. Triggers escalation when deadlines pass
    6. Ensures all state changes are durable

    This processor is intentionally synchronous per message to keep the logic
    clear and testable. Concurrency is handled at a higher level (worker pool).
    """

    def __init__(
        self,
        session: AsyncSession,
        channels: ChannelRegistry,
    ) -> None:
        self.session = session
        self.channels = channels
        self.repository = MessageRepository(session)
        self.events = EventRecorder(session)

    async def process_new_message(self, message_id: str) -> None:
        """Process a newly created message: move it to QUEUED, then attempt delivery.

        This is the entry point when a message is first submitted by the sender.
        """
        message = await self.repository.get_by_id(message_id)
        if message is None:
            logger.error(f"Message {message_id} not found")
            return

        now = datetime.now(timezone.utc)

        # Transition: PENDING → QUEUED
        try:
            apply_transition(message, MessageState.QUEUED, now=now)
        except StateTransitionError as exc:
            logger.error(f"Failed to queue message {message_id}: {exc}")
            return

        await self.repository.update(message)
        await self.events.record(
            message_id,
            EventType.QUEUED,
            {"previous_state": "PENDING"},
        )
        logger.info(f"Message {message_id} queued for delivery")

    async def attempt_delivery(self, message_id: str) -> None:
        """Attempt to deliver a message through its primary channel.

        This is called when the message is ready to be sent. It:
        1. Validates the channel is available
        2. Calls the channel send method
        3. Records the attempt and result
        4. Transitions state based on outcome
        """
        message = await self.repository.get_by_id(message_id)
        if message is None:
            logger.error(f"Message {message_id} not found")
            return

        now = datetime.now(timezone.utc)
        channel_name = message.policy.primary_channel

        # Transition: QUEUED → SENDING
        try:
            apply_transition(message, MessageState.SENDING, now=now)
        except StateTransitionError as exc:
            logger.error(f"Cannot transition {message_id} to SENDING: {exc}")
            return

        await self.repository.update(message)
        await self.events.record(
            message_id,
            EventType.SENDING,
            {"channel": channel_name},
        )

        # Get the channel implementation
        channel = self.channels.get(channel_name)
        if channel is None:
            logger.error(f"Channel '{channel_name}' not configured")
            await self._mark_failed(
                message,
                f"Channel '{channel_name}' not available",
                now,
            )
            return

        # Attempt the send
        logger.info(f"Sending message {message_id} via {channel_name}")
        result = await channel.send(
            recipient=message.recipient,
            content=message.content,
            metadata={"message_id": message_id, "priority": message.policy.priority},
        )

        # Record the send attempt
        await self.events.record(
            message_id,
            EventType.SEND_ATTEMPT,
            {
                "channel": channel_name,
                "success": result.success,
                "external_message_id": result.external_message_id,
                "error": result.error,
            },
        )

        if result.success:
            # Transition: SENDING → SENT_TO_CHANNEL
            message.sent_at = now
            message.external_message_id = result.external_message_id
            try:
                apply_transition(message, MessageState.SENT_TO_CHANNEL, now=now)
            except StateTransitionError as exc:
                logger.error(f"Cannot transition {message_id} to SENT_TO_CHANNEL: {exc}")
                return

            await self.repository.update(message)
            await self.events.record(
                message_id,
                EventType.SEND_SUCCESS,
                {
                    "channel": channel_name,
                    "external_message_id": result.external_message_id,
                },
            )
            logger.info(f"Message {message_id} sent successfully via {channel_name}")
        else:
            # Primary send failed. Check if fallbacks are available.
            if message.policy.fallback_channels:
                # Mark as sent to channel (attempt was made) then escalate
                message.sent_at = now
                try:
                    apply_transition(message, MessageState.SENT_TO_CHANNEL, now=now)
                except StateTransitionError as exc:
                    logger.error(f"Cannot transition {message_id} to SENT_TO_CHANNEL: {exc}")
                    return
                
                await self.repository.update(message)
                await self.events.record(
                    message_id,
                    EventType.SEND_FAILED,
                    {
                        "channel": channel_name,
                        "error": result.error,
                    },
                )
                
                # Now escalate to fallback
                await self._escalate_message(message, now)
            else:
                # No fallbacks, mark as failed
                await self._mark_failed(message, result.error or "unknown error", now)

    async def check_deadlines(self) -> None:
        """Scan for messages past their acknowledgement deadline.

        This runs periodically (e.g., every 10 seconds). For each message
        that has exceeded its deadline without acknowledgement, trigger
        escalation or mark as dead-letter.

        In production, this would use SELECT ... FOR UPDATE SKIP LOCKED
        to avoid thundering herd issues.
        """
        now = datetime.now(timezone.utc)
        due_messages = await self.repository.list_due_for_escalation(now)

        for message in due_messages:
            logger.info("Escalating message %s because its deadline has passed", message.id)
            await self._escalate_message(message, now)

    async def acknowledge_message(
        self,
        message_id: str,
        acknowledged_at: datetime | None = None,
    ) -> None:
        """Record an acknowledgement for a message.

        This is called when the recipient confirms receipt/reading of the message.
        If the message is in SENT_TO_CHANNEL, transition to ACKNOWLEDGED.
        If it is past that point, just record the late ack as a fact.
        """
        message = await self.repository.get_by_id(message_id)
        if message is None:
            logger.error(f"Message {message_id} not found")
            return

        now = acknowledged_at or datetime.now(timezone.utc)

        if message.current_state == MessageState.SENT_TO_CHANNEL:
            try:
                apply_transition(message, MessageState.ACKNOWLEDGED, now=now)
            except StateTransitionError as exc:
                logger.error(f"Cannot acknowledge {message_id}: {exc}")
                return

            await self.repository.update(message)
            await self.events.record(
                message_id,
                EventType.ACK_RECEIVED,
                {"acknowledged_at": now.isoformat()},
            )
            logger.info(f"Message {message_id} acknowledged")
        else:
            # Late ack: record but don't transition state
            message.acknowledged_at = now
            await self.repository.update(message)
            await self.events.record(
                message_id,
                EventType.ACK_RECEIVED,
                {
                    "acknowledged_at": now.isoformat(),
                    "current_state": message.current_state.value,
                    "note": "late_acknowledgement",
                },
            )
            logger.info(
                f"Message {message_id} acknowledged late (state={message.current_state.value})"
            )

    async def _escalate_message(
        self,
        message: MessageRecord,
        now: datetime,
    ) -> None:
        """Trigger escalation: move to fallback channel or mark deferred.

        Escalation is called when:
        1. The acknowledgement deadline has passed, or
        2. The primary send failed and fallback channels are available

        This respects the sender's policy.
        """
        # Check if there are fallback channels
        if not message.policy.fallback_channels:
            # No fallback, so mark as dead-letter
            await self._mark_dead_letter(message, "no_fallback_channels", now)
            return

        # Transition: SENT_TO_CHANNEL → ESCALATION_PENDING
        try:
            apply_transition(message, MessageState.ESCALATION_PENDING, now=now)
        except StateTransitionError as exc:
            logger.error(f"Cannot escalate {message.id}: {exc}")
            return

        message.escalated_at = now
        await self.repository.update(message)
        await self.events.record(
            message.id,
            EventType.ESCALATION_TRIGGERED,
            {
                "reason": "deadline_passed",
                "fallback_channels": message.policy.fallback_channels,
            },
        )
        logger.info(f"Message {message.id} escalated to fallback")

    async def attempt_fallback(self, message_id: str, channel_name: str) -> None:
        """Attempt delivery via a fallback channel.

        Similar to attempt_delivery but called when the primary channel
        failed or the deadline passed.
        """
        message = await self.repository.get_by_id(message_id)
        if message is None:
            logger.error(f"Message {message_id} not found")
            return

        if message.current_state != MessageState.ESCALATION_PENDING:
            logger.warning(
                f"Message {message_id} is in state {message.current_state.value}, "
                "not ESCALATION_PENDING; skipping fallback attempt"
            )
            return

        now = datetime.now(timezone.utc)

        # Transition: ESCALATION_PENDING → FALLBACK_SENDING
        try:
            apply_transition(message, MessageState.FALLBACK_SENDING, now=now)
        except StateTransitionError as exc:
            logger.error(f"Cannot transition {message_id} to FALLBACK_SENDING: {exc}")
            return

        await self.repository.update(message)
        await self.events.record(
            message_id,
            EventType.FALLBACK_ATTEMPT,
            {"channel": channel_name},
        )

        # Get the fallback channel
        channel = self.channels.get(channel_name)
        if channel is None:
            logger.error(f"Fallback channel '{channel_name}' not configured")
            await self._mark_dead_letter(message, f"fallback channel '{channel_name}' not available", now)
            return

        # Attempt the send
        logger.info(f"Attempting fallback send via {channel_name}")
        result = await channel.send(
            recipient=message.recipient,
            content=message.content,
            metadata={"message_id": message_id, "priority": message.policy.priority, "is_fallback": True},
        )

        await self.events.record(
            message_id,
            EventType.FALLBACK_ATTEMPT,
            {
                "channel": channel_name,
                "success": result.success,
                "external_message_id": result.external_message_id,
                "error": result.error,
            },
        )

        if result.success:
            # Transition: FALLBACK_SENDING → FALLBACK_DELIVERED
            message.external_message_id = result.external_message_id
            try:
                apply_transition(message, MessageState.FALLBACK_DELIVERED, now=now)
            except StateTransitionError as exc:
                logger.error(f"Cannot transition {message_id} to FALLBACK_DELIVERED: {exc}")
                return

            await self.repository.update(message)
            await self.events.record(
                message_id,
                EventType.FALLBACK_SUCCESS,
                {"channel": channel_name},
            )
            logger.info(f"Message {message_id} delivered via fallback: {channel_name}")
        else:
            message.last_error = f"fallback send failed: {result.error or 'unknown'}"
            message.retry_count += 1

            if FALLBACK_RETRY_POLICY.should_retry(message.retry_count):
                message.next_retry_at = FALLBACK_RETRY_POLICY.next_retry_at(
                    message.retry_count - 1,
                    now,
                )
                try:
                    apply_transition(message, MessageState.ESCALATION_DEFERRED, now=now)
                except StateTransitionError as exc:
                    logger.error(f"Cannot defer fallback retry for {message_id}: {exc}")
                    return

                await self.repository.update(message)
                await self.events.record(
                    message_id,
                    EventType.ESCALATION_DEFERRED,
                    {
                        "channel": channel_name,
                        "retry_count": message.retry_count,
                        "next_retry_at": message.next_retry_at.isoformat(),
                        "error": message.last_error,
                    },
                )
                logger.info(
                    "Fallback retry scheduled for %s at %s",
                    message_id,
                    message.next_retry_at.isoformat(),
                )
            else:
                await self._mark_dead_letter(message, message.last_error, now)

    async def _mark_failed(
        self,
        message: MessageRecord,
        error: str,
        now: datetime,
    ) -> None:
        """Mark a message as failed (will not be retried or escalated)."""
        try:
            apply_transition(message, MessageState.FAILED, now=now)
        except StateTransitionError as exc:
            logger.error(f"Cannot mark {message.id} as FAILED: {exc}")
            return

        message.last_error = error
        await self.repository.update(message)
        await self.events.record(
            message.id,
            EventType.SEND_FAILED,
            {"error": error},
        )
        logger.info(f"Message {message.id} marked as FAILED: {error}")

    async def _mark_dead_letter(
        self,
        message: MessageRecord,
        reason: str,
        now: datetime,
    ) -> None:
        """Mark a message as dead-letter (no more processing possible)."""
        try:
            apply_transition(message, MessageState.DEAD_LETTER, now=now)
        except StateTransitionError as exc:
            logger.error(f"Cannot mark {message.id} as DEAD_LETTER: {exc}")
            return

        message.last_error = reason
        await self.repository.update(message)
        await self.events.record(
            message.id,
            EventType.DEAD_LETTER,
            {"reason": reason},
        )
        logger.info(f"Message {message.id} sent to dead-letter: {reason}")
