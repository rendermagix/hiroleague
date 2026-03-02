"""CommunicationManager — central message router for phbcli.

Responsibilities:
  - Receives inbound UnifiedMessages from all channel plugins (via PluginManager's
    on_message callback) and places them on the inbound queue.
  - Monitors the outbound queue and routes each message to the correct channel
    plugin via PluginManager.send_to_channel.
  - Performs permission checks (placeholder — to be implemented).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from phb_channel_sdk.models import UnifiedMessage

if TYPE_CHECKING:
    from .plugin_manager import PluginManager

logger = logging.getLogger(__name__)


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for user/channel permission checks.

    Will enforce access control rules once the permission system is designed.
    Raise PermissionError to block the message.
    """


class CommunicationManager:
    """Routes messages between channel plugins and the application core.

    Usage::

        comm = CommunicationManager()
        plugin_manager = PluginManager(..., on_message=comm.receive)
        comm.set_plugin_manager(plugin_manager)

        # Add to the main asyncio.gather so the outbound worker runs
        await asyncio.gather(..., comm.run())

        # Enqueue an outbound message from anywhere in the application
        await comm.enqueue_outbound(msg)
    """

    def __init__(self) -> None:
        self._plugin_manager: PluginManager | None = None
        self.inbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()
        self.outbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    def set_plugin_manager(self, plugin_manager: PluginManager) -> None:
        """Bind the PluginManager after both objects have been constructed."""
        self._plugin_manager = plugin_manager

    # ------------------------------------------------------------------
    # Inbound path  (channel plugin → phbcli core)
    # ------------------------------------------------------------------

    async def receive(self, data: dict[str, Any]) -> None:
        """Accept a raw params dict from PluginManager's channel.receive handler.

        Validates it as a UnifiedMessage, runs the permission check, then
        places it on the inbound queue for downstream consumers.
        """
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            logger.warning("Dropping malformed inbound message: %s", exc)
            return

        try:
            _check_permissions(msg)
        except PermissionError as exc:
            logger.warning(
                "Inbound message blocked by permission check "
                "[channel=%s sender=%s]: %s",
                msg.channel,
                msg.sender_id,
                exc,
            )
            return

        logger.debug(
            "Inbound [channel=%s sender=%s content_type=%s]",
            msg.channel,
            msg.sender_id,
            msg.content_type,
        )
        self.inbound_queue.put_nowait(msg)
        logger.info(
            "Inbound message queued [msg_id=%s channel=%s sender=%s content_type=%s]",
            msg.id,
            msg.channel,
            msg.sender_id,
            msg.content_type,
        )

    # ------------------------------------------------------------------
    # Outbound path  (phbcli core → channel plugin)
    # ------------------------------------------------------------------

    async def enqueue_outbound(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue to be sent to its channel."""
        await self.outbound_queue.put(msg)
        logger.info(
            "Outbound message queued [msg_id=%s channel=%s recipient=%s content_type=%s]",
            msg.id,
            msg.channel,
            msg.recipient_id,
            msg.content_type,
        )

    async def _outbound_worker(self) -> None:
        """Continuously drain the outbound queue and dispatch to channel plugins."""
        while True:
            msg = await self.outbound_queue.get()
            try:
                try:
                    _check_permissions(msg)
                except PermissionError as exc:
                    logger.warning(
                        "Outbound message blocked by permission check "
                        "[channel=%s recipient=%s]: %s",
                        msg.channel,
                        msg.recipient_id,
                        exc,
                    )
                    continue

                logger.debug(
                    "Outbound [channel=%s recipient=%s content_type=%s]",
                    msg.channel,
                    msg.recipient_id,
                    msg.content_type,
                )
                if self._plugin_manager is None:
                    logger.warning("Outbound message dropped: no PluginManager set.")
                    continue
                logger.info(
                    "Dispatching outbound message [msg_id=%s channel=%s recipient=%s content_type=%s]",
                    msg.id,
                    msg.channel,
                    msg.recipient_id,
                    msg.content_type,
                )
                await self._plugin_manager.send_to_channel(
                    msg.channel, msg.model_dump(mode="json")
                )
            finally:
                self.outbound_queue.task_done()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the outbound worker. Add to asyncio.gather alongside PluginManager."""
        logger.info("CommunicationManager started.")
        await self._outbound_worker()
