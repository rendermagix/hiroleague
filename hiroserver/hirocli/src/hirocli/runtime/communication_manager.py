"""CommunicationManager — central message router for hirocli.

Responsibilities:
  - Receives inbound UnifiedMessages from all channel plugins (via ChannelManager's
    on_message callback) and routes them by message_type.
  - message_type "message": sends immediate ack event, spawns an adapter task
    that enriches the message concurrently then places it on the inbound queue.
  - message_type "request": dispatches to injected RequestHandler.
  - message_type "event": dispatches to injected EventHandler.
  - Unknown message_type: logs and enqueues an error response to the sender.
  - Monitors the outbound queue and routes each message to the correct channel
    plugin via ChannelManager.send_to_channel.
  - Performs permission checks (placeholder — to be implemented).

The adapter pipeline runs in an asyncio.Task per message so receive() always
returns immediately, never blocking other incoming messages regardless of how
long transcription or image analysis takes.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_JSON,
    EVENT_TYPE_MESSAGE_RECEIVED,
    EVENT_TYPE_MESSAGE_TRANSCRIBED,
    MESSAGE_TYPE_EVENT,
    MESSAGE_TYPE_MESSAGE,
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
)
from hiro_channel_sdk.models import (
    ContentItem,
    EventPayload,
    MessageRouting,
    UnifiedMessage,
)
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from .channel_manager import ChannelManager
    from .event_handler import EventHandler
    from .message_adapter import MessageAdapterPipeline
    from .request_handler import RequestHandler

log = Logger.get("COMM_MAN")


def _check_permissions(msg: UnifiedMessage) -> None:
    """Placeholder for user/channel permission checks.

    Will enforce access control rules once the permission system is designed.
    Raise PermissionError to block the message.
    """


class CommunicationManager:
    """Routes messages between channel plugins and the application core.

    Usage::

        pipeline = MessageAdapterPipeline([AudioTranscriptionAdapter(), ...])
        request_handler = RequestHandler(comm, workspace_path)
        event_handler = EventHandler()

        comm = CommunicationManager(
            adapter_pipeline=pipeline,
            request_handler=request_handler,
            event_handler=event_handler,
        )
        channel_manager = ChannelManager(..., on_message=comm.receive)
        comm.set_channel_manager(channel_manager)

        await asyncio.gather(..., comm.run())
        await comm.enqueue_outbound(msg)
    """

    def __init__(
        self,
        adapter_pipeline: MessageAdapterPipeline | None = None,
        request_handler: RequestHandler | None = None,
        event_handler: EventHandler | None = None,
    ) -> None:
        self._channel_manager: ChannelManager | None = None
        self._adapter_pipeline = adapter_pipeline
        self._request_handler = request_handler
        self._event_handler = event_handler
        self.inbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()
        self.outbound_queue: asyncio.Queue[UnifiedMessage] = asyncio.Queue()

    def set_channel_manager(self, channel_manager: ChannelManager) -> None:
        """Bind the ChannelManager after both objects have been constructed."""
        self._channel_manager = channel_manager

    # ------------------------------------------------------------------
    # Inbound path  (channel plugin → hirocli core)
    # ------------------------------------------------------------------

    async def receive(self, data: dict[str, Any]) -> None:
        """Accept a raw params dict from ChannelManager's channel.receive handler.

        Validates it as a UnifiedMessage, runs the permission check, then
        routes by message_type. Returns immediately in all cases.
        """
        try:
            msg = UnifiedMessage.model_validate(data)
        except Exception as exc:
            log.warning("Dropping malformed inbound message", error=str(exc))
            return

        try:
            _check_permissions(msg)
        except PermissionError as exc:
            log.warning(
                "Inbound message blocked by permission check",
                channel=msg.routing.channel,
                sender=msg.routing.sender_id,
                error=str(exc),
            )
            return

        match msg.message_type:
            case _ if msg.message_type == MESSAGE_TYPE_MESSAGE:
                await self._handle_message(msg)

            case _ if msg.message_type == MESSAGE_TYPE_REQUEST:
                if self._request_handler is not None:
                    asyncio.create_task(
                        self._safe_handle_request(msg),
                        name=f"request-{msg.routing.id}",
                    )
                else:
                    log.warning("No RequestHandler configured, dropping request", msg_id=msg.routing.id)

            case _ if msg.message_type == MESSAGE_TYPE_EVENT:
                if self._event_handler is not None:
                    asyncio.create_task(
                        self._safe_handle_event(msg),
                        name=f"event-{msg.routing.id}",
                    )
                else:
                    log.info(
                        "Inbound event dropped (no EventHandler)",
                        msg_id=msg.routing.id,
                        event_type=msg.event.type if msg.event else None,
                    )

            case _:
                log.warning(
                    "Unknown message_type, dropping",
                    message_type=msg.message_type,
                    msg_id=msg.routing.id,
                )
                await self._enqueue_error_response(
                    msg, f"Unknown message_type: {msg.message_type}"
                )

    async def _handle_message(self, msg: UnifiedMessage) -> None:
        """Ack immediately and spawn adapter pipeline as a background task."""
        await self._send_ack_event(msg)

        asyncio.create_task(
            self._adapt_and_queue(msg),
            name=f"adapt-{msg.routing.id}",
        )
        log.info(
            "Message acked, adapter task spawned",
            msg_id=msg.routing.id,
            channel=msg.routing.channel,
            sender=msg.routing.sender_id,
            items=len(msg.content),
        )

    async def _adapt_and_queue(self, msg: UnifiedMessage) -> None:
        """Run the adapter pipeline then place the enriched message on inbound_queue."""
        try:
            if self._adapter_pipeline is not None:
                msg = await self._adapter_pipeline.process(msg)

            # Emit message.transcribed events for any audio items that were
            # successfully transcribed by the adapter pipeline.
            for item in msg.content:
                if item.content_type == "audio" and "description" in item.metadata:
                    transcript_event = UnifiedMessage(
                        message_type=MESSAGE_TYPE_EVENT,
                        routing=MessageRouting(
                            channel=msg.routing.channel,
                            direction="outbound",
                            sender_id="server",
                            recipient_id=msg.routing.sender_id,
                            metadata=msg.routing.metadata,
                        ),
                        event=EventPayload(
                            type=EVENT_TYPE_MESSAGE_TRANSCRIBED,
                            ref_id=msg.routing.id,
                            data={"transcript": item.metadata["description"]},
                        ),
                    )
                    await self.enqueue_outbound(transcript_event)
                    log.info(
                        "Transcript event enqueued",
                        msg_id=msg.routing.id,
                        transcript_len=len(item.metadata["description"]),
                    )

            self.inbound_queue.put_nowait(msg)
            log.info(
                "Inbound message queued after adaptation",
                msg_id=msg.routing.id,
                channel=msg.routing.channel,
                sender=msg.routing.sender_id,
            )
        except Exception as exc:
            log.error(
                "Adapter pipeline failed",
                msg_id=msg.routing.id,
                error=str(exc),
                exc_info=True,
            )
            await self._enqueue_error_response(msg, f"Adapter pipeline error: {exc}")

    async def _safe_handle_request(self, msg: UnifiedMessage) -> None:
        try:
            await self._request_handler.handle(msg)
        except Exception as exc:
            log.error("RequestHandler raised unexpectedly", error=str(exc), exc_info=True)

    async def _safe_handle_event(self, msg: UnifiedMessage) -> None:
        try:
            await self._event_handler.handle(msg)
        except Exception as exc:
            log.error("EventHandler raised unexpectedly", error=str(exc), exc_info=True)

    # ------------------------------------------------------------------
    # Ack / error helpers
    # ------------------------------------------------------------------

    async def _send_ack_event(self, msg: UnifiedMessage) -> None:
        """Send a message.received event back to the sender immediately."""
        ack = UnifiedMessage(
            message_type=MESSAGE_TYPE_EVENT,
            routing=MessageRouting(
                channel=msg.routing.channel,
                direction="outbound",
                sender_id="server",
                recipient_id=msg.routing.sender_id,
                metadata=msg.routing.metadata,
            ),
            event=EventPayload(
                type=EVENT_TYPE_MESSAGE_RECEIVED,
                ref_id=msg.routing.id,
            ),
        )
        await self.enqueue_outbound(ack)

    async def _enqueue_error_response(self, msg: UnifiedMessage, reason: str) -> None:
        """Enqueue an error response back to the sender."""
        body = json.dumps({"status": "error", "error": {"code": "routing_error", "message": reason}})
        error_msg = UnifiedMessage(
            message_type=MESSAGE_TYPE_RESPONSE,
            request_id=msg.request_id,
            routing=MessageRouting(
                channel=msg.routing.channel,
                direction="outbound",
                sender_id="server",
                recipient_id=msg.routing.sender_id,
                metadata=msg.routing.metadata,
            ),
            content=[ContentItem(content_type=CONTENT_TYPE_JSON, body=body)],
        )
        await self.enqueue_outbound(error_msg)

    # ------------------------------------------------------------------
    # Outbound path  (hirocli core → channel plugin)
    # ------------------------------------------------------------------

    async def enqueue_outbound(self, msg: UnifiedMessage) -> None:
        """Place a message on the outbound queue to be sent to its channel."""
        await self.outbound_queue.put(msg)
        log.info(
            "Outbound message queued",
            msg_id=msg.routing.id,
            channel=msg.routing.channel,
            recipient=msg.routing.recipient_id,
            items=len(msg.content),
        )

    async def _outbound_worker(self) -> None:
        """Continuously drain the outbound queue and dispatch to channel plugins."""
        while True:
            msg = await self.outbound_queue.get()
            try:
                try:
                    _check_permissions(msg)
                except PermissionError as exc:
                    log.warning(
                        "Outbound message blocked by permission check",
                        channel=msg.routing.channel,
                        recipient=msg.routing.recipient_id,
                        error=str(exc),
                    )
                    continue

                if self._channel_manager is None:
                    log.warning("Outbound message dropped — no ChannelManager set")
                    continue

                log.info(
                    "Dispatching outbound message",
                    msg_id=msg.routing.id,
                    channel=msg.routing.channel,
                    recipient=msg.routing.recipient_id,
                    items=len(msg.content),
                )
                await self._channel_manager.send_to_channel(
                    msg.routing.channel, msg.model_dump(mode="json")
                )
            finally:
                self.outbound_queue.task_done()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Run the outbound worker. Add to asyncio.gather alongside ChannelManager."""
        log.info("CommunicationManager started")
        await self._outbound_worker()
