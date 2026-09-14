from __future__ import annotations

from app.channels.base import Channel
from app.channels.telegram import TelegramChannel


class ChannelRegistry:
    """Factory and registry for available communication channels.

    The processor uses this to look up the correct channel implementation
    based on the message's policy (primary_channel or fallback_channels).
    """

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, name: str, channel: Channel) -> None:
        """Register a channel by name."""
        self._channels[name] = channel

    def get(self, name: str) -> Channel | None:
        """Retrieve a channel by name, or None if not found."""
        return self._channels.get(name)

    def available(self) -> list[str]:
        """List all available channel names."""
        return list(self._channels.keys())


def create_registry(telegram_token: str) -> ChannelRegistry:
    """Create a fully initialized channel registry.

    This is called once at app startup. All channels that the system
    can use must be registered here.
    """
    registry = ChannelRegistry()

    if telegram_token:
        registry.register("telegram", TelegramChannel(telegram_token))

    # Placeholder for SMS, email, webhook, etc.
    # registry.register("sms", SMSChannel(...))
    # registry.register("email", EmailChannel(...))

    return registry
