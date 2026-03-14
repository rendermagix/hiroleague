"""Gateway lifecycle tools: setup, start, stop, status, teardown.

These tools delegate all logic to hirogateway.service, which owns the
gateway lifecycle.  CLI commands and the admin UI are thin callers that
invoke execute() and render the result.
"""

from __future__ import annotations

from hirogateway.service import (
    GatewaySetupResult,
    GatewayStartResult,
    GatewayStatusResult,
    GatewayStopResult,
    GatewayTeardownResult,
    get_status,
    setup_instance,
    start_instance,
    stop_instance,
    teardown_instance,
)

from .base import Tool, ToolParam


class GatewayStatusTool(Tool):
    name = "gateway_status"
    description = "Show running status for one or all local gateway instances"
    params = {
        "instance": ToolParam(
            str,
            "Gateway instance name (omit to show all instances)",
            required=False,
        ),
    }

    def execute(self, instance: str | None = None) -> GatewayStatusResult:
        return get_status(instance)


class GatewayStartTool(Tool):
    name = "gateway_start"
    description = "Start a local gateway instance in the background"
    params = {
        "instance": ToolParam(
            str,
            "Gateway instance name (default: registry default)",
            required=False,
        ),
        "verbose": ToolParam(bool, "Enable verbose gateway logging", required=False),
    }

    def execute(
        self,
        instance: str | None = None,
        verbose: bool = False,
    ) -> GatewayStartResult:
        return start_instance(instance, verbose=verbose)


class GatewayStopTool(Tool):
    name = "gateway_stop"
    description = "Stop a running local gateway instance"
    params = {
        "instance": ToolParam(
            str,
            "Gateway instance name (default: registry default)",
            required=False,
        ),
    }

    def execute(self, instance: str | None = None) -> GatewayStopResult:
        return stop_instance(instance)


class GatewaySetupTool(Tool):
    name = "gateway_setup"
    description = (
        "Create a new local gateway instance: register it, save config, "
        "and optionally register auto-start"
    )
    params = {
        "name": ToolParam(str, "Gateway instance name"),
        "desktop_public_key": ToolParam(
            str, "Desktop Ed25519 public key (base64) used as the trust root"
        ),
        "port": ToolParam(int, "Port the gateway WebSocket server will bind to"),
        "host": ToolParam(
            str,
            "Host the gateway will bind to (default: 0.0.0.0)",
            required=False,
        ),
        "log_dir": ToolParam(str, "Custom log directory (default: instance folder)", required=False),
        "make_default": ToolParam(bool, "Set this instance as the default", required=False),
        "skip_autostart": ToolParam(bool, "Do not register auto-start", required=False),
        "elevated_task": ToolParam(
            bool,
            "(Windows) Request UAC elevation for Task Scheduler auto-start entry",
            required=False,
        ),
    }

    def execute(
        self,
        name: str,
        desktop_public_key: str,
        port: int,
        host: str = "0.0.0.0",
        log_dir: str = "",
        make_default: bool = False,
        skip_autostart: bool = False,
        elevated_task: bool = False,
    ) -> GatewaySetupResult:
        return setup_instance(
            name,
            host=host,
            port=port,
            desktop_public_key=desktop_public_key,
            log_dir=log_dir,
            make_default=make_default,
            skip_autostart=skip_autostart,
            elevated_task=elevated_task,
        )


class GatewayTeardownTool(Tool):
    name = "gateway_teardown"
    description = "Stop a local gateway instance and remove its auto-start registration"
    params = {
        "instance": ToolParam(
            str,
            "Gateway instance name (default: registry default)",
            required=False,
        ),
        "purge": ToolParam(
            bool,
            "Also remove the instance from the registry and delete its files",
            required=False,
        ),
        "elevated_task": ToolParam(
            bool,
            "(Windows) Request UAC elevation to remove high-privilege Task Scheduler entry",
            required=False,
        ),
    }

    def execute(
        self,
        instance: str | None = None,
        purge: bool = False,
        elevated_task: bool = False,
    ) -> GatewayTeardownResult:
        return teardown_instance(instance, purge=purge, elevated_task=elevated_task)
