"""Metrics and status tracking for operational visibility.

This module provides metrics about message processing, delivery rates,
and system health that can be exposed via prometheus or other monitoring systems.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.message_state import MessageState
from app.infrastructure.models import Message

logger = logging.getLogger(__name__)


@dataclass
class MessageMetrics:
    """Snapshot of message processing metrics."""

    total_messages: int = 0
    messages_by_state: dict[str, int] = field(default_factory=dict)
    messages_acknowledged: int = 0
    messages_failed: int = 0
    messages_dead_letter: int = 0
    
    # Success metrics
    successful_deliveries_24h: int = 0
    failed_deliveries_24h: int = 0
    
    # Latency metrics
    avg_time_to_acknowledge_seconds: float = 0.0
    median_time_to_acknowledge_seconds: float = 0.0

    def delivery_success_rate(self) -> float:
        """Calculate the delivery success rate in the last 24 hours."""
        total = self.successful_deliveries_24h + self.failed_deliveries_24h
        if total == 0:
            return 0.0
        return (self.successful_deliveries_24h / total) * 100

    def __repr__(self) -> str:
        return (
            f"MessageMetrics(total={self.total_messages}, "
            f"acknowledged={self.messages_acknowledged}, "
            f"failed={self.messages_failed}, "
            f"dead_letter={self.messages_dead_letter}, "
            f"success_rate={self.delivery_success_rate():.1f}%)"
        )


class MetricsCollector:
    """Collects and aggregates message processing metrics."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def collect(self) -> MessageMetrics:
        """Collect current system metrics.

        This scans the message database to compute state distributions,
        success rates, and latency measurements.
        """
        metrics = MessageMetrics()

        # Count total messages
        total_result = await self.session.execute(select(func.count(Message.id)))
        metrics.total_messages = total_result.scalar() or 0

        # Count messages by state
        for state in MessageState:
            count_result = await self.session.execute(
                select(func.count(Message.id)).where(Message.current_state == state)
            )
            count = count_result.scalar() or 0
            metrics.messages_by_state[state.value] = count

        # Count acknowledged messages
        acked_result = await self.session.execute(
            select(func.count(Message.id)).where(Message.acknowledged_at.is_not(None))
        )
        metrics.messages_acknowledged = acked_result.scalar() or 0

        # Count failed messages
        failed_result = await self.session.execute(
            select(func.count(Message.id)).where(Message.current_state == MessageState.FAILED)
        )
        metrics.messages_failed = failed_result.scalar() or 0

        # Count dead-letter messages
        dl_result = await self.session.execute(
            select(func.count(Message.id)).where(Message.current_state == MessageState.DEAD_LETTER)
        )
        metrics.messages_dead_letter = dl_result.scalar() or 0

        # Calculate 24-hour success metrics
        await self._calculate_24h_metrics(metrics)

        # Calculate acknowledgement latency
        await self._calculate_ack_latency(metrics)

        return metrics

    async def _calculate_24h_metrics(self, metrics: MessageMetrics) -> None:
        """Calculate delivery success rate for the last 24 hours."""
        cutoff = datetime.now(UTC) - timedelta(hours=24)

        # Count successful deliveries (SENT_TO_CHANNEL or acknowledged)
        success_result = await self.session.execute(
            select(func.count(Message.id)).where(
                Message.current_state.in_(
                    [
                        MessageState.SENT_TO_CHANNEL,
                        MessageState.ACKNOWLEDGED,
                        MessageState.FALLBACK_DELIVERED,
                    ]
                ),
                Message.created_at >= cutoff,
            )
        )
        metrics.successful_deliveries_24h = success_result.scalar() or 0

        # Count failed deliveries
        failed_result = await self.session.execute(
            select(func.count(Message.id)).where(
                Message.current_state.in_([MessageState.FAILED, MessageState.DEAD_LETTER]),
                Message.created_at >= cutoff,
            )
        )
        metrics.failed_deliveries_24h = failed_result.scalar() or 0

    async def _calculate_ack_latency(self, metrics: MessageMetrics) -> None:
        """Calculate acknowledgement latency statistics."""
        # Only include acknowledged messages
        # Query for all acknowledged messages and calculate latency in application code
        from sqlalchemy.sql import select as sql_select

        ack_result = await self.session.execute(
            sql_select(Message).where(Message.acknowledged_at.is_not(None))
        )
        acked_messages = ack_result.scalars().all()

        if acked_messages:
            latencies = []
            for msg in acked_messages:
                if msg.acknowledged_at and msg.created_at:
                    delta = msg.acknowledged_at - msg.created_at
                    latencies.append(delta.total_seconds())

            if latencies:
                metrics.avg_time_to_acknowledge_seconds = sum(latencies) / len(latencies)


@dataclass
class SystemHealth:
    """System health status."""

    is_healthy: bool = True
    is_ready: bool = True
    messages_pending: int = 0
    messages_escalation_pending: int = 0
    messages_dead_letter: int = 0
    last_check_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for JSON serialization."""
        return {
            "healthy": self.is_healthy,
            "ready": self.is_ready,
            "messages_pending": self.messages_pending,
            "messages_escalation_pending": self.messages_escalation_pending,
            "messages_dead_letter": self.messages_dead_letter,
            "warnings": self.warnings,
        }


class HealthChecker:
    """Monitors system health and readiness."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def check_health(self) -> SystemHealth:
        """Check the health of the system.

        A system is considered healthy if:
        - The database is accessible
        - There are no excessive dead-letter messages (> 100)
        """
        health = SystemHealth(last_check_at=datetime.now(UTC))

        try:
            # Check database connectivity
            result = await self.session.execute(select(func.count(Message.id)))
            result.scalar()

            # Count messages in concerning states
            pending_result = await self.session.execute(
                select(func.count(Message.id)).where(Message.current_state == MessageState.PENDING)
            )
            health.messages_pending = pending_result.scalar() or 0

            escalation_pending_result = await self.session.execute(
                select(func.count(Message.id)).where(
                    Message.current_state == MessageState.ESCALATION_PENDING
                )
            )
            health.messages_escalation_pending = escalation_pending_result.scalar() or 0

            dead_letter_result = await self.session.execute(
                select(func.count(Message.id)).where(
                    Message.current_state == MessageState.DEAD_LETTER
                )
            )
            health.messages_dead_letter = dead_letter_result.scalar() or 0

            # Check for warning conditions
            if health.messages_dead_letter > 100:
                health.warnings.append(f"High dead-letter count: {health.messages_dead_letter}")
                health.is_healthy = False

            if health.messages_escalation_pending > 500:
                health.warnings.append(
                    f"High escalation pending count: {health.messages_escalation_pending}"
                )

        except Exception as exc:
            logger.error("Health check failed: %s", exc)
            health.is_healthy = False
            health.is_ready = False
            health.warnings.append(f"Health check error: {str(exc)}")

        return health
