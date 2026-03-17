"""Echo channel plugin.

Useful for development and integration testing of the plugin system.
Any outbound message sent to this channel is immediately echoed back
as an inbound message, with "[echo]" prepended to each text content item.
"""

from __future__ import annotations

from typing import Any

from hiro_channel_sdk.base import ChannelPlugin
from hiro_channel_sdk.models import ChannelInfo, ContentItem, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

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
        echoed_content = [
            ContentItem(
                content_type=item.content_type,
                # Prefix text items with "[echo]"; pass other content types through unchanged.
                body=f"[echo] {item.body}" if item.content_type == "text" else item.body,
                metadata=item.metadata,
            )
            for item in message.content
        ]
        log.debug("EchoChannel reflecting message", items=len(echoed_content))
        echo = UnifiedMessage(
            routing=MessageRouting(
                channel=message.routing.channel,
                direction="inbound",
                sender_id=f"echo:{message.routing.recipient_id or 'server'}",
                recipient_id=message.routing.sender_id,
                metadata=message.routing.metadata,
            ),
            content=echoed_content,
        )
        await self.emit(echo)
