"""ToolRegistry — central dispatch for all phbcli tools.

The registry holds one instance of every registered Tool.  Any caller —
HTTP /invoke, future web UI, tests — goes through registry.invoke() instead
of instantiating tools directly.  This is the single place to add cross-cutting
concerns like policy checks, audit logging, or rate limiting later.

CLI commands and the AI agent continue to call tool.execute() directly (they
already hold a reference to the tool instance), so nothing changes for them.
The registry is an *additional* entry point, not a replacement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import Tool


class ToolNotFoundError(Exception):
    """Raised when invoke() is called with an unknown tool name."""


class ToolExecutionError(Exception):
    """Wraps an unexpected exception raised inside tool.execute()."""

    def __init__(self, tool_name: str, cause: Exception) -> None:
        super().__init__(f"Tool '{tool_name}' raised: {cause}")
        self.tool_name = tool_name
        self.cause = cause


@dataclass
class InvokeResult:
    """Structured return value from registry.invoke()."""

    tool_name: str
    result: Any


class ToolRegistry:
    """Holds tool instances and dispatches invoke() calls.

    Usage::

        registry = ToolRegistry()
        registry.register(DeviceAddTool())
        registry.register(DeviceListTool())

        result = registry.invoke("device_add", {"ttl_seconds": 120})
        # result.result is a DeviceAddResult dataclass

    Policy hook::

        def my_policy(tool_name: str, params: dict) -> None:
            if tool_name == "device_revoke":
                raise PermissionError("not allowed")

        registry = ToolRegistry(policy=my_policy)
    """

    def __init__(
        self,
        policy: "PolicyFn | None" = None,
    ) -> None:
        self._tools: dict[str, Tool] = {}
        self._policy = policy

    def register(self, tool: Tool) -> None:
        """Add a tool instance to the registry."""
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        """Return all registered tool names."""
        return list(self._tools.keys())

    def schema(self) -> list[dict[str, Any]]:
        """Return a JSON-serialisable schema for all registered tools.

        Useful for exposing GET /tools so a web UI can discover what's available.
        """
        result = []
        for tool in self._tools.values():
            result.append({
                "name": tool.name,
                "description": tool.description,
                "params": {
                    name: {
                        "type": param.type_.__name__,
                        "description": param.description,
                        "required": param.required,
                    }
                    for name, param in tool.params.items()
                },
            })
        return result

    def invoke(self, tool_name: str, params: dict[str, Any] | None = None) -> InvokeResult:
        """Dispatch a call to the named tool.

        Args:
            tool_name: The snake_case name declared on the Tool subclass.
            params:    Flat dict of keyword arguments forwarded to execute().
                       Unknown keys are silently ignored so callers don't need
                       to be perfectly in sync with the tool signature.

        Raises:
            ToolNotFoundError:  tool_name is not registered.
            ToolExecutionError: tool.execute() raised an unexpected exception.
        """
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Unknown tool: '{tool_name}'. Available: {self.names()}")

        if self._policy is not None:
            self._policy(tool_name, params or {})

        tool = self._tools[tool_name]

        # Only pass params the tool actually declares — avoids unexpected-keyword errors.
        safe_params = {k: v for k, v in (params or {}).items() if k in tool.params}

        try:
            result = tool.execute(**safe_params)
        except Exception as exc:
            raise ToolExecutionError(tool_name, exc) from exc

        return InvokeResult(tool_name=tool_name, result=result)


# Type alias for the optional policy callable.
# policy(tool_name, params) should raise an exception to block the call.
PolicyFn = "Callable[[str, dict[str, Any]], None]"
