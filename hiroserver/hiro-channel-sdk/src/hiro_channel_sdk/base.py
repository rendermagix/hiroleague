"""Abstract base class every channel plugin must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any

from .models import ChannelInfo, UnifiedMessage


class ChannelPlugin(ABC):
    """Contract between hirocli and a channel plugin.

    Subclass this, implement the abstract methods, then hand an instance to
    ``PluginTransport`` to connect it to hirocli.

    Lifecycle (called by PluginTransport):
      1. ``on_configure(config)`` — push credentials / settings from hirocli
      2. ``on_start()``           — begin listening for inbound messages
      3. ``on_stop()``            — graceful shutdown

    Sending / receiving:
      - Implement ``send(message)`` to translate an outbound UnifiedMessage
        into a third-party API call.
      - Call ``await self.emit(message)`` from within your implementation
        whenever an inbound message arrives; the transport forwards it to hirocli.
    """

    # Injected by PluginTransport — do not set manually.
    _emit_callback: Callable[[UnifiedMessage], Awaitable[None]] | None = None
    _event_callback: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None

    @property
    @abstractmethod
    def info(self) -> ChannelInfo:
        """Return channel name, version, and description."""

    @abstractmethod
    async def on_configure(self, config: dict[str, Any]) -> None:
        """Receive credentials and settings pushed by hirocli."""

    @abstractmethod
    async def on_start(self) -> None:
        """Begin polling / webhooks — start producing inbound messages."""

    @abstractmethod
    async def on_stop(self) -> None:
        """Gracefully tear down connections to the third party."""

    @abstractmethod
    async def send(self, message: UnifiedMessage) -> None:
        """Translate *message* into a third-party API call and dispatch it."""

    async def emit(self, message: UnifiedMessage) -> None:
        """Forward an inbound message from the third party to hirocli.

        Call this from your polling loop or webhook handler whenever a new
        message arrives from the external service.
        """
        if self._emit_callback is not None:
            await self._emit_callback(message)

    async def emit_event(self, event: str, data: dict[str, Any] | None = None) -> None:
        """Send a structured event back to hirocli (status, diagnostics, etc.)."""
        if self._event_callback is not None:
            await self._event_callback(event, data or {})

    async def on_event(self, event: str, data: dict[str, Any]) -> None:
        """Optional inbound event from hirocli to the plugin."""
        _ = (event, data)
