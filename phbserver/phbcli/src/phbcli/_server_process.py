"""Entry point for the detached server process spawned by `phbcli start`.

Runs the FastAPI HTTP server and PluginManager concurrently inside a single
asyncio event loop.  Gateway connectivity is owned by the mandatory
`devices` channel plugin.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from phb_logger import Logger

log = Logger.get("SERVER")


async def _tail_plugin_logs(log_dir: Path, stop_event: asyncio.Event) -> None:
    """Forward new lines from plugin-*.log files to stdout in foreground mode."""
    positions: dict[str, int] = {}
    while not stop_event.is_set():
        await asyncio.sleep(0.5)
        for log_file in sorted(log_dir.glob("plugin-*.log")):
            key = str(log_file)
            if key not in positions:
                # Seek to end on first discovery — skip pre-existing history
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


async def _main(foreground: bool = False) -> None:
    from phb_channel_sdk import log_setup
    from phbcli.config import APP_DIR, load_config, mark_connected, mark_disconnected, resolve_log_dir
    from phbcli.crypto import create_device_attestation, load_or_create_master_key
    from phbcli.pairing import (
        ApprovedDevice,
        clear_pairing_session,
        load_pairing_session,
        upsert_approved_device,
    )
    from phbcli.agent_manager import AgentManager
    from phbcli.communication_manager import CommunicationManager
    from phbcli.plugin_manager import PluginManager
    from phbcli.process import write_pid
    from phbcli.server import run_http_server, set_channel_info_provider

    config = load_config()
    log_dir = resolve_log_dir(config)
    log_setup.init(
        "server",
        log_dir,
        foreground=foreground,
        log_levels=config.log_levels or None,
    )
    desktop_private_key = load_or_create_master_key(APP_DIR, filename=config.master_key_file)
    stop_event = asyncio.Event()
    write_pid()
    plugin_manager: PluginManager | None = None

    def _shutdown(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _shutdown)

    async def _on_channel_event(event: str, data: dict[str, object]) -> None:
        nonlocal plugin_manager
        if event == "gateway_connected":
            gateway_url = str(data.get("gateway_url") or config.gateway_url)
            mark_connected(gateway_url)
        elif event == "gateway_disconnected":
            mark_disconnected()
        elif event == "pairing_request":
            if plugin_manager is None:
                return
            request_id = data.get("request_id")
            pairing_code = data.get("pairing_code")
            device_public_key = data.get("device_public_key")
            if not isinstance(request_id, str) or not request_id:
                return
            if not isinstance(pairing_code, str) or not pairing_code:
                await plugin_manager.send_event_to_channel(
                    "devices",
                    "pairing_response",
                    {
                        "request_id": request_id,
                        "status": "rejected",
                        "reason": "invalid_pairing_code",
                    },
                )
                return
            if not isinstance(device_public_key, str) or not device_public_key:
                await plugin_manager.send_event_to_channel(
                    "devices",
                    "pairing_response",
                    {
                        "request_id": request_id,
                        "status": "rejected",
                        "reason": "invalid_device_public_key",
                    },
                )
                return

            session = load_pairing_session()
            if session is None:
                await plugin_manager.send_event_to_channel(
                    "devices",
                    "pairing_response",
                    {
                        "request_id": request_id,
                        "status": "rejected",
                        "reason": "no_active_pairing_session",
                    },
                )
                return

            if (not session.is_valid()) or (session.code != pairing_code):
                await plugin_manager.send_event_to_channel(
                    "devices",
                    "pairing_response",
                    {
                        "request_id": request_id,
                        "status": "rejected",
                        "reason": "pairing_code_invalid_or_expired",
                    },
                )
                return

            device_id = f"mobile-{uuid.uuid4().hex[:12]}"
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
                ApprovedDevice(
                    device_id=device_id,
                    device_public_key=device_public_key,
                    paired_at=datetime.now(UTC),
                    expires_at=expires_at,
                    metadata={"source": "gateway_pairing"},
                )
            )
            clear_pairing_session()
            await plugin_manager.send_event_to_channel(
                "devices",
                "pairing_response",
                {
                    "request_id": request_id,
                    "status": "approved",
                    "device_id": device_id,
                    "attestation": attestation,
                },
            )

    comm_manager = CommunicationManager()
    plugin_manager = PluginManager(
        config,
        stop_event,
        on_message=comm_manager.receive,
        on_event=_on_channel_event,
    )
    comm_manager.set_plugin_manager(plugin_manager)
    set_channel_info_provider(plugin_manager.get_channel_info)
    agent_manager = AgentManager(comm_manager)

    log.info(
        "Starting phbcli server",
        http=f"http://{config.http_host}:{config.http_port}/status",
        plugin_ws=f"ws://127.0.0.1:{config.plugin_port}",
        device_id=config.device_id,
    )

    coros = [
        run_http_server(config, stop_event),
        plugin_manager.run(),
        comm_manager.run(),
        agent_manager.run(),
    ]
    if foreground:
        coros.append(_tail_plugin_logs(log_dir, stop_event))

    server_task = asyncio.ensure_future(
        asyncio.gather(*coros, return_exceptions=True)
    )

    # Block until a shutdown signal fires, then give plugin_manager its
    # graceful-shutdown window before cancelling any remaining tasks.
    await stop_event.wait()
    await asyncio.sleep(1.5)
    server_task.cancel()
    try:
        await server_task
    except (asyncio.CancelledError, Exception):
        pass

    mark_disconnected()
    log.info("phbcli server exited")


if __name__ == "__main__":
    asyncio.run(_main())
