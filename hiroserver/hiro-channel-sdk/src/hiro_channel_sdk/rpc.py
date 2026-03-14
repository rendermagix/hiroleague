"""JSON-RPC 2.0 helpers — build and parse wire frames."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from .models import RpcRequest, RpcResponse

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_request(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
) -> str:
    """Serialise a JSON-RPC request (expects a response)."""
    return RpcRequest(
        method=method,
        params=params or {},
        id=request_id or uuid4().hex,
    ).model_dump_json()


def build_notification(
    method: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Serialise a JSON-RPC notification (fire-and-forget, no id)."""
    return RpcRequest(method=method, params=params or {}, id=None).model_dump_json()


def build_success(result: Any, request_id: str | int | None = None) -> str:
    """Serialise a successful JSON-RPC response."""
    return RpcResponse(result=result, id=request_id).model_dump_json()


def build_error(
    code: int,
    message: str,
    request_id: str | int | None = None,
    data: Any = None,
) -> str:
    """Serialise a JSON-RPC error response."""
    return RpcResponse(
        error={"code": code, "message": message, "data": data},
        id=request_id,
    ).model_dump_json()


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_message(raw: str) -> RpcRequest | RpcResponse:
    """Deserialise a raw JSON string into the appropriate RPC model."""
    data = json.loads(raw)
    if "method" in data:
        return RpcRequest.model_validate(data)
    return RpcResponse.model_validate(data)
