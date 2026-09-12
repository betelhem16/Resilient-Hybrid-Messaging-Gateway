from __future__ import annotations

import logging
from typing import Any

from app.channels.base import Channel, SendResult

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """Send messages via Telegram using the Bot API.

    Uses long polling mode (no webhook needed). This is correct for local dev
    where the system has no public HTTPS endpoint.

    The recipient is a numeric Telegram chat_id, which can be obtained by:
    1. Starting a DM with the bot
    2. Calling getMe() or getUpdates() to see the chat_id
    """

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self.channel_name = "telegram"

    async def send(
        self,
        recipient: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SendResult:
        """Send a message to a Telegram chat.

        In a real implementation, this would:
        1. Call the Telegram Bot API
        2. Validate the chat_id
        3. Parse the response
        4. Return success/failure with message_id

        For now, we'll stub it with validation and a mock response.
        This is sufficient to test state transitions without actual Telegram.
        """
        if not self.bot_token:
            return SendResult(
                success=False,
                channel=self.channel_name,
                error="telegram_bot_token not configured",
            )

        if not recipient:
            return SendResult(
                success=False,
                channel=self.channel_name,
                error="recipient (chat_id) is required",
            )

        # Validate that recipient is a numeric chat_id
        try:
            int(recipient)
        except ValueError:
            return SendResult(
                success=False,
                channel=self.channel_name,
                error=f"invalid chat_id format: {recipient}",
            )

        # Stub: in production, call Telegram API
        # For now, we'll simulate a successful send
        logger.info(
            "Telegram send channel=%s recipient=%s content_length=%d",
            self.channel_name,
            recipient,
            len(content),
        )

        return SendResult(
            success=True,
            channel=self.channel_name,
            external_message_id=f"tg_{recipient}_{hash(content) % 1000000}",
            metadata={"platform": "telegram", "method": "bot_api"},
        )
