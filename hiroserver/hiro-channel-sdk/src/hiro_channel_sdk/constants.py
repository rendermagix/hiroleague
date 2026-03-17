"""Channel SDK protocol constants.

Authoritative source for the JSON-RPC wire protocol, WebSocket close codes,
auth roles, message content types, and reconnect policy used by all Hiro
channel packages and the hirocli/hirogateway servers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

JSONRPC_VERSION: str = "2.0"
JSONRPC_ERROR_METHOD_NOT_FOUND: int = -32601
JSONRPC_ERROR_INTERNAL: int = -32603

# ---------------------------------------------------------------------------
# Channel RPC methods
# ---------------------------------------------------------------------------

METHOD_REGISTER: str = "channel.register"
METHOD_RECEIVE: str = "channel.receive"
METHOD_EVENT: str = "channel.event"
METHOD_SEND: str = "channel.send"
METHOD_CONFIGURE: str = "channel.configure"
METHOD_STOP: str = "channel.stop"
METHOD_STATUS: str = "channel.status"

# ---------------------------------------------------------------------------
# WebSocket close codes (Hiro application range 4000–4999)
# ---------------------------------------------------------------------------

WS_CLOSE_NORMAL: int = 1000
WS_CLOSE_AUTH_FAILED: int = 4003
WS_CLOSE_PAIRING_FIELD_MISSING: int = 4004
WS_CLOSE_DESKTOP_NOT_CONNECTED: int = 4006
WS_CLOSE_PAIRING_TIMEOUT: int = 4008
WS_CLOSE_DUPLICATE_DEVICE: int = 4009
WS_CLOSE_CHANNEL_REPLACED: int = 4010

# ---------------------------------------------------------------------------
# Auth roles
# ---------------------------------------------------------------------------

AUTH_ROLE_DESKTOP: str = "desktop"
AUTH_ROLE_DEVICE: str = "device"

# ---------------------------------------------------------------------------
# Message types — communication intent discriminator on UnifiedMessage
# ---------------------------------------------------------------------------

MESSAGE_TYPE_MESSAGE: str = "message"    # content exchange (text, images, files…)
MESSAGE_TYPE_REQUEST: str = "request"    # reserved — expects a response
MESSAGE_TYPE_RESPONSE: str = "response"  # reserved — answer to a request
MESSAGE_TYPE_STREAM: str = "stream"      # reserved — streaming chunks

# ---------------------------------------------------------------------------
# Message content types — content_type values used in ContentItem
# ---------------------------------------------------------------------------

CONTENT_TYPE_TEXT: str = "text"
CONTENT_TYPE_JSON: str = "json"
CONTENT_TYPE_IMAGE: str = "image"
CONTENT_TYPE_AUDIO: str = "audio"
CONTENT_TYPE_VIDEO: str = "video"
CONTENT_TYPE_FILE: str = "file"
CONTENT_TYPE_LOCATION: str = "location"

# ---------------------------------------------------------------------------
# Reconnect / backoff policy
# ---------------------------------------------------------------------------

RECONNECT_DELAY_SECONDS: float = 5.0
RECONNECT_BACKOFF_BASE: float = 1.0
RECONNECT_BACKOFF_MAX: float = 60.0
