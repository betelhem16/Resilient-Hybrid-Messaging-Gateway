from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SendResult:
    """Outcome of a send attempt through a channel."""

    success: bool
    channel: str
    external_message_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


class Channel(ABC):
    """Abstract interface for a communication channel.

    Implementations handle the actual mechanics of sending a message through
    a specific medium (Telegram, SMS, email, etc.) and report back success/failure
    with metadata for audit trails.
    """

    @abstractmethod
    async def send(
        self,
        recipient: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a message through this channel.

        Args:
            recipient: channel-specific recipient ID (chat_id for Telegram, phone for SMS, etc.)
            content: message body
            metadata: optional extra data to pass to the channel (priority hints, formatting, etc.)

        Returns:
            SendResult containing success flag, external_message_id, and any error details.
        """
        ...
