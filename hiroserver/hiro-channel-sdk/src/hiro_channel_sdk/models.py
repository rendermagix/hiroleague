"""Shared Pydantic models — the lingua franca of the plugin system."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .constants import JSONRPC_VERSION, MESSAGE_TYPE_MESSAGE


class MessageRouting(BaseModel):
    """Routing and identification envelope for a UnifiedMessage.

    Carries who sent the message, where it came from, and where it should go.
    ``direction`` is always from the perspective of hirocli:
      - "inbound"  — arriving FROM the third party (e.g., user sent a Telegram msg)
      - "outbound" — to be SENT TO the third party (e.g., send a Telegram reply)
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    channel: str
    direction: str  # "inbound" | "outbound"
    sender_id: str
    recipient_id: str | None = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContentItem(BaseModel):
    """A single piece of content within a UnifiedMessage.

    Multiple items can be present in one message, for example a text caption
    alongside several images and a PDF file.
    """

    content_type: str  # "text" | "image" | "audio" | "video" | "file" | "location" | …
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedMessage(BaseModel):
    """Canonical cross-channel message format v0.1.

    Structured as two distinct concerns:
      - ``routing``      — who/where/when: channel, direction, sender, recipient, timestamp
      - ``content``      — ordered list of content items (text, images, audio, files, …)

    ``version`` allows future parsers to handle multiple schema generations.
    ``message_type`` identifies the communication intent. Currently only
    ``"message"`` (content exchange) is implemented; ``"request"``,
    ``"response"``, and ``"stream"`` are reserved for future use.
    """

    version: str = "0.1"
    message_type: str = MESSAGE_TYPE_MESSAGE
    routing: MessageRouting
    content: list[ContentItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def _require_content_for_message_type(self) -> Self:
        # "message" type must carry at least one content item; future types
        # (request, response, stream) may have different requirements.
        if self.message_type == MESSAGE_TYPE_MESSAGE and len(self.content) < 1:
            raise ValueError(
                "message_type 'message' requires at least one content item"
            )
        return self


class RpcRequest(BaseModel):
    """JSON-RPC 2.0 request or notification (notification when id is None)."""

    jsonrpc: str = JSONRPC_VERSION
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class RpcResponse(BaseModel):
    """JSON-RPC 2.0 response."""

    jsonrpc: str = JSONRPC_VERSION
    result: Any = None
    error: dict[str, Any] | None = None
    id: str | int | None = None


class ChannelInfo(BaseModel):
    """Self-description that a channel sends on registration."""

    name: str
    version: str = "0.1.0"
    description: str = ""
