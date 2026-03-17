"""hiro-channel-sdk — shared contract for Hiro channel plugins.

Exports the key building blocks every plugin author needs:
  - UnifiedMessage   — canonical cross-channel message model (v0.1)
  - MessageRouting   — routing/identification envelope within UnifiedMessage
  - ContentItem      — single content piece within UnifiedMessage
  - ChannelPlugin    — abstract base class to implement
  - PluginTransport  — handles WS connection to hirocli, JSON-RPC dispatch
  - rpc              — JSON-RPC 2.0 helpers (build / parse)
  - constants        — protocol constants (RPC methods, WS close codes, etc.)
"""

from . import constants, log_setup
from .base import ChannelPlugin
from .models import ChannelInfo, ContentItem, MessageRouting, RpcRequest, RpcResponse, UnifiedMessage
from .transport import PluginTransport

__version__ = "0.1.0"
__all__ = [
    "log_setup",
    "constants",
    "ChannelPlugin",
    "ChannelInfo",
    "ContentItem",
    "MessageRouting",
    "RpcRequest",
    "RpcResponse",
    "UnifiedMessage",
    "PluginTransport",
]
