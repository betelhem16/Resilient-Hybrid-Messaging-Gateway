"""Retry and backoff policies for message delivery.

This module defines how many times messages should be retried and
what delay strategies to use between attempts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behavior.

    Attributes:
        max_retries: Maximum number of retry attempts after the initial attempt
        initial_backoff_seconds: Initial delay before first retry
        max_backoff_seconds: Maximum delay between retries (backoff caps here)
        backoff_multiplier: Multiplier for exponential backoff (e.g., 2.0 for doubling)
    """

    max_retries: int = 3
    initial_backoff_seconds: int = 5
    max_backoff_seconds: int = 300
    backoff_multiplier: float = 2.0

    def should_retry(self, retry_count: int) -> bool:
        """Check if a message should be retried.

        Args:
            retry_count: Current number of retries attempted

        Returns:
            True if retry_count < max_retries
        """
        return retry_count < self.max_retries

    def next_retry_at(self, retry_count: int, now: datetime | None = None) -> datetime:
        """Calculate when the next retry should occur.

        Uses exponential backoff with a maximum delay cap.

        Args:
            retry_count: Current number of retries attempted
            now: Reference time (defaults to current UTC time)

        Returns:
            Datetime when the next retry should be attempted
        """
        if now is None:
            now = datetime.now(timezone.utc)

        # Calculate backoff: initial_backoff * (multiplier ^ retry_count)
        delay_seconds = self.initial_backoff_seconds * (self.backoff_multiplier ** retry_count)

        # Cap at max_backoff
        delay_seconds = min(delay_seconds, self.max_backoff_seconds)

        # Add jitter (up to 10% of the delay) to avoid thundering herd
        import random

        jitter = random.uniform(0, delay_seconds * 0.1)
        delay_seconds += jitter

        return now + timedelta(seconds=delay_seconds)


# Default retry policy for primary channel sends
PRIMARY_RETRY_POLICY = RetryPolicy(
    max_retries=3,
    initial_backoff_seconds=5,
    max_backoff_seconds=300,
    backoff_multiplier=2.0,
)

# Default retry policy for fallback channel sends
FALLBACK_RETRY_POLICY = RetryPolicy(
    max_retries=2,
    initial_backoff_seconds=10,
    max_backoff_seconds=600,
    backoff_multiplier=2.0,
)
