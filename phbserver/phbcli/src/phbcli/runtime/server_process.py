"""Entry point for the detached server process spawned by `phbcli start`.

Runs the FastAPI HTTP server and ChannelManager concurrently inside a single
asyncio event loop.  Gateway connectivity is owned by the mandatory
`devices` channel plugin.

Workspace path resolution:
  - Foreground mode: workspace_path is passed directly by tools/server.py.
  - Background mode: workspace_path is read from the PHB_WORKSPACE_PATH env var
    set by tools/server.py before Popen.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from phb_commons.log import Logger
from phb_commons.process import write_pid

from phbcli.constants import DEVICE_ID_PREFIX, DEVICE_ID_SUFFIX_LENGTH, ENV_ADMIN_UI, ENV_WORKSPACE_PATH, PID_FILENAME

log = Logger.get("SERVER")


async def _tail_plugin_logs(log_dir: Path, stop_event: asyncio.Event) -> None:
    """Forward new lines from plugin-*.log files to stdout in foreground mode."""
    positions: dict[str, int] = {}
    while not stop_event.is_set():
        await asyncio.sleep(0.5)
        for log_file in sorted(log_dir.glob("plugin-*.log")):
            key = str(log_file)
            if key not in positions:
                try:
                    positions[key] = log_file.stat().st_size
                except OSError:
                    positions[key] = 0
                continue
            try:
                with log_file.open(encoding="utf-8", errors="replace") as fh:
                    fh.seek(positions[key])
                    chunk = fh.read()
                    positions[key] = fh.tell()
                if chunk:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()
            except OSError:
                pass


async def _main(foreground: bool = False, workspace_path: Path | None = None, admin: bool = False) -> None:
    if workspace_path is None:
        ws_str = os.environ.get(ENV_WORKSPACE_PATH)
        if not ws_str:
            raise RuntimeError(
                "PHB_WORKSPACE_PATH environment variable is not set. "
                "The server process must be started via 'phbcli start'."
            )
        workspace_path = Path(ws_str)

    from phb_channel_sdk import log_setup
    from phbcli.domain.config import load_config, mark_connected, mark_disconnected, resolve_log_dir
    from phbcli.domain.crypto import load_or_create_master_key
    from phbcli.domain.db import ensure_db
    from phbcli.domain.pairing import (
        ApprovedDevice,
        clear_pairing_session,
        load_pairing_session,
        upsert_approved_device,
    )
    from phbcli.runtime.agent_manager import AgentManager
    from phbcli.runtime.communication_manager import CommunicationManager
    from phbcli.runtime.channel_manager import ChannelManager
    from phbcli.runtime.http_server import run_http_server, set_channel_info_provider, set_stop_event, set_tool_registry, set_workspace_path
    from phbcli.tools import all_tools
    from phbcli.tools.registry import ToolRegistry

    config = load_config(workspace_path)
    log_dir = resolve_log_dir(workspace_path, config)
    log_setup.init(
        "server",
        log_dir,
        foreground=foreground,
        log_levels=config.log_levels or None,
    )
    desktop_private_key = load_or_create_master_key(workspace_path, filename=config.master_key_file)
    stop_event = asyncio.Event()
    set_stop_event(stop_event)
    write_pid(workspace_path, PID_FILENAME)
    ensure_db(workspace_path)  # create/upgrade workspace.db tables and conversations/ dir
    set_workspace_path(workspace_path)

    tool_registry = ToolRegistry()
    tool_registry.register_all(all_tools())
    set_tool_registry(tool_registry)

    channel_manager: ChannelManager | None = None

    def _shutdown(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _shutdown)

    async def _on_channel_event(event: str, data: dict[str, object]) -> None:
        nonlocal channel_manager
        if event == "gateway_connected":
            gateway_url = str(data.get("gateway_url") or config.gateway_url)
            mark_connected(workspace_path, gateway_url)
        elif event == "gateway_disconnected":
            mark_disconnected(workspace_path)
        elif event == "pairing_request":
            if channel_manager is None:
                return
            request_id = data.get("request_id")
            pairing_code = data.get("pairing_code")
            device_public_key = data.get("device_public_key")
            device_name_raw = data.get("device_name")
            # device_name is optional; coerce to str or None.
            device_name = device_name_raw if isinstance(device_name_raw, str) and device_name_raw else None
            if not isinstance(request_id, str) or not request_id:
                return
            if not isinstance(pairing_code, str) or not pairing_code:
                await channel_manager.send_event_to_channel(
                    "devices", "pairing_response",
                    {"request_id": request_id, "status": "rejected", "reason": "invalid_pairing_code"},
                )
                return
            if not isinstance(device_public_key, str) or not device_public_key:
                await channel_manager.send_event_to_channel(
                    "devices", "pairing_response",
                    {"request_id": request_id, "status": "rejected", "reason": "invalid_device_public_key"},
                )
                return

            session = load_pairing_session(workspace_path)
            if session is None:
                await channel_manager.send_event_to_channel(
                    "devices", "pairing_response",
                    {"request_id": request_id, "status": "rejected", "reason": "no_active_pairing_session"},
                )
                return

            if (not session.is_valid()) or (session.code != pairing_code):
                await channel_manager.send_event_to_channel(
                    "devices", "pairing_response",
                    {"request_id": request_id, "status": "rejected", "reason": "pairing_code_invalid_or_expired"},
                )
                return

            from phb_commons.attestation import create_device_attestation

            device_id = f"{DEVICE_ID_PREFIX}{uuid.uuid4().hex[:DEVICE_ID_SUFFIX_LENGTH]}"
            attestation = create_device_attestation(
                desktop_private_key,
                device_id=device_id,
                device_public_key_b64=device_public_key,
                expires_days=config.attestation_expires_days,
            )
            blob = json.loads(attestation["blob"])
            expires_at_raw = blob.get("expires_at")
            expires_at = None
            if isinstance(expires_at_raw, str):
                try:
                    expires_at = datetime.fromisoformat(
                        expires_at_raw.replace("Z", "+00:00")
                    ).astimezone(UTC)
                except Exception:
                    expires_at = None

            upsert_approved_device(
                workspace_path,
                ApprovedDevice(
                    device_id=device_id,
                    device_public_key=device_public_key,
                    paired_at=datetime.now(UTC),
                    expires_at=expires_at,
                    metadata={"source": "gateway_pairing"},
                    device_name=device_name,
                ),
            )
            clear_pairing_session(workspace_path)
            await channel_manager.send_event_to_channel(
                "devices", "pairing_response",
                {
                    "request_id": request_id,
                    "status": "approved",
                    "device_id": device_id,
                    "attestation": attestation,
                },
            )

    comm_manager = CommunicationManager()
    channel_manager = ChannelManager(
        config,
        workspace_path,
        stop_event,
        on_message=comm_manager.receive,
        on_event=_on_channel_event,
    )
    comm_manager.set_channel_manager(channel_manager)
    set_channel_info_provider(channel_manager.get_channel_info)
    agent_manager = AgentManager(comm_manager, workspace_path)

    log.info(
        "Starting phbcli server",
        workspace=str(workspace_path),
        http=f"http://{config.http_host}:{config.http_port}/status",
        plugin_ws=f"ws://127.0.0.1:{config.plugin_port}",
        device_id=config.device_id,
    )

    coros = [
        run_http_server(config, stop_event),
        channel_manager.run(),
        comm_manager.run(),
        agent_manager.run(),
    ]
    if foreground:
        coros.append(_tail_plugin_logs(log_dir, stop_event))
    if admin:
        from phbcli.ui.run import run_admin_ui
        # Pass log_dir and workspace_path so the admin UI can tail logs and
        # identify which workspace it is hosting (to protect self-destructive actions).
        coros.append(run_admin_ui(config, stop_event, log_dir=log_dir, workspace_path=workspace_path))

    server_task = asyncio.ensure_future(
        asyncio.gather(*coros, return_exceptions=True)
    )

    await stop_event.wait()
    await asyncio.sleep(1.5)
    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass

    from phbcli.runtime.http_server import get_restart_admin, is_restart_requested

    if is_restart_requested():
        log.info("Restart requested — spawning new server process")
        _spawn_server(workspace_path, admin=get_restart_admin())

    mark_disconnected(workspace_path)
    log.info("phbcli server exited")


def _spawn_server(workspace_path: Path, admin: bool = False) -> None:
    """Spawn a new detached server process (used for self-restart).

    Uses spawn_detached from phb_commons; the new child writes its own PID
    via write_pid() at startup, so we don't write it here.
    """
    from phb_commons.process import remove_pid, spawn_detached, uv_python_cmd

    script = str(Path(__file__))
    env = {**os.environ, ENV_WORKSPACE_PATH: str(workspace_path)}
    if admin:
        env[ENV_ADMIN_UI] = "1"
    elif ENV_ADMIN_UI in env:
        del env[ENV_ADMIN_UI]

    # Clear stale PID so the new child starts clean.
    remove_pid(workspace_path, PID_FILENAME)

    stderr_log = workspace_path / "stderr.log"
    spawn_detached([*uv_python_cmd(), script], env=env, stderr_log=stderr_log)
    log.info("New server process spawning (child will write its own PID)")


if __name__ == "__main__":
    # Read admin flag from env var set by tools/server.py for background spawns.
    _admin = os.environ.get(ENV_ADMIN_UI) == "1"
    asyncio.run(_main(admin=_admin))
