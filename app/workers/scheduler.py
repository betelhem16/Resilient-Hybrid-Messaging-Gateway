"""Background task scheduler for message processing pipeline.

This module runs periodic tasks such as:
- Checking for messages past their acknowledgement deadline
- Processing escalations (attempting fallback channels)
- Polling for messages stuck in intermediate states
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.channels.registry import ChannelRegistry
from app.domain.message_state import MessageState
from app.repositories.message_repository import MessageRepository
from app.workers.processor import MessageProcessor

logger = logging.getLogger(__name__)


class MessageScheduler:
    """Runs background tasks for message processing.

    This should be instantiated once per application and run in a background task.
    It handles:
    1. Periodic deadline checks (every ~10 seconds)
    2. Periodic fallback escalation attempts (every ~20 seconds)
    3. Retrying messages that failed (every ~30 seconds)
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        channels: ChannelRegistry,
        deadline_check_interval: int = 10,
        fallback_attempt_interval: int = 15,
        retry_check_interval: int = 20,
    ) -> None:
        self.session_factory = session_factory
        self.channels = channels
        self.deadline_check_interval = deadline_check_interval
        self.fallback_attempt_interval = fallback_attempt_interval
        self.retry_check_interval = retry_check_interval
        self.running = False

    async def start(self) -> None:
        """Start the background scheduler.

        This spawns background tasks that run until stop() is called.
        """
        self.running = True
        logger.info("Starting message scheduler")

        try:
            await asyncio.gather(
                self._deadline_check_loop(),
                self._fallback_attempt_loop(),
                self._retry_check_loop(),
            )
        except asyncio.CancelledError:
            logger.info("Message scheduler cancelled")
            self.running = False

    async def stop(self) -> None:
        """Stop the background scheduler."""
        logger.info("Stopping message scheduler")
        self.running = False

    async def _deadline_check_loop(self) -> None:
        """Periodically check for messages past their deadline.

        Messages in SENT_TO_CHANNEL that have not been acknowledged and are past
        their deadline are escalated to ESCALATION_PENDING so fallback attempts
        can be made.
        """
        while self.running:
            try:
                await self._check_deadlines_once()
            except Exception as exc:
                logger.exception("Error in deadline check loop: %s", exc)

            try:
                await asyncio.sleep(self.deadline_check_interval)
            except asyncio.CancelledError:
                break

    async def _check_deadlines_once(self) -> None:
        """Run one iteration of deadline checking."""
        async with self.session_factory() as session:
            try:
                processor = MessageProcessor(session, self.channels)
                await processor.check_deadlines()
                await session.commit()
            except Exception as exc:
                logger.error("Failed to check deadlines: %s", exc)
                await session.rollback()

    async def _fallback_attempt_loop(self) -> None:
        """Periodically attempt to send messages via fallback channels.

        Messages in ESCALATION_PENDING are processed by attempting their
        first available fallback channel.
        """
        while self.running:
            try:
                await self._attempt_fallbacks_once()
            except Exception as exc:
                logger.exception("Error in fallback attempt loop: %s", exc)

            try:
                await asyncio.sleep(self.fallback_attempt_interval)
            except asyncio.CancelledError:
                break

    async def _attempt_fallbacks_once(self) -> None:
        """Run one iteration of fallback attempts."""
        async with self.session_factory() as session:
            try:
                repository = MessageRepository(session)
                processor = MessageProcessor(session, self.channels)

                # Find all messages in ESCALATION_PENDING
                escalation_pending = await repository.list_by_state(MessageState.ESCALATION_PENDING)

                for message in escalation_pending:
                    if message.policy.fallback_channels:
                        # Try the first fallback channel
                        fallback_channel = message.policy.fallback_channels[0]
                        logger.info(
                            "Attempting fallback delivery for %s via %s",
                            message.id,
                            fallback_channel,
                        )
                        await processor.attempt_fallback(message.id, fallback_channel)

                await session.commit()
            except Exception as exc:
                logger.error("Failed to attempt fallbacks: %s", exc)
                await session.rollback()

    async def _retry_check_loop(self) -> None:
        """Periodically check for messages due for retry.

        Messages that have failed but have retries remaining are re-attempted
        according to their retry schedule.
        """
        while self.running:
            try:
                await self._attempt_retries_once()
            except Exception as exc:
                logger.exception("Error in retry check loop: %s", exc)

            try:
                await asyncio.sleep(self.retry_check_interval)
            except asyncio.CancelledError:
                break

    async def _attempt_retries_once(self) -> None:
        """Run one iteration of retry attempts."""

        async with self.session_factory() as session:
            try:
                repository = MessageRepository(session)
                processor = MessageProcessor(session, self.channels)
                now = datetime.now(UTC)

                # Find all messages due for retry
                due_for_retry = await repository.list_due_for_retry(now)

                for message in due_for_retry:
                    if message.current_state == MessageState.QUEUED:
                        logger.info(
                            "Retrying message %s (attempt %d)",
                            message.id,
                            message.retry_count + 1,
                        )
                        await processor.attempt_delivery(message.id)
                    elif message.current_state == MessageState.ESCALATION_DEFERRED:
                        logger.info(
                            "Retrying escalation for message %s (attempt %d)",
                            message.id,
                            message.retry_count + 1,
                        )
                        await processor._escalate_message(message, now)

                await session.commit()
            except Exception as exc:
                logger.error("Failed to attempt retries: %s", exc)
                await session.rollback()
