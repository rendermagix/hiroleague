"""Echo channel plugin.

Useful for development and integration testing of the plugin system.
Any outbound message sent to this channel is immediately echoed back
as an inbound message, prefixed with "[echo]".
"""

from __future__ import annotations

from typing import Any

from phb_channel_sdk.base import ChannelPlugin
from phb_channel_sdk.models import ChannelInfo, UnifiedMessage
from phb_commons.log import Logger

log = Logger.get("ECHO")


class EchoChannel(ChannelPlugin):
    """Trivial channel that reflects every outbound message back as inbound."""

    @property
    def info(self) -> ChannelInfo:
        return ChannelInfo(
            name="echo",
            version="0.1.0",
            description="Echo channel — reflects sent messages back as received.",
        )

    async def on_configure(self, config: dict[str, Any]) -> None:
        log.info("EchoChannel configured", config=config)

    async def on_start(self) -> None:
        log.info("EchoChannel started")

    async def on_stop(self) -> None:
        log.info("EchoChannel stopped")

    async def send(self, message: UnifiedMessage) -> None:
        """Reflect the outbound message back as an inbound echo."""
        log.debug("EchoChannel reflecting message", body=message.body)
        echo = message.model_copy(
            update={
                "direction": "inbound",
                "body": f"[echo] {message.body}",
                "sender_id": f"echo:{message.recipient_id or 'server'}",
                "recipient_id": message.sender_id,
            }
        )
        await self.emit(echo)
