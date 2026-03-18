"""Entry point for the detached server process spawned by `hirocli start`.

Runs the FastAPI HTTP server and ChannelManager concurrently inside a single
asyncio event loop.  Gateway connectivity is owned by the mandatory
`devices` channel plugin.

Workspace path resolution:
  - Foreground mode: workspace_path is passed directly by tools/server.py.
  - Background mode: workspace_path is read from the HIRO_WORKSPACE_PATH env var
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

from hiro_commons.log import Logger
from hiro_commons.process import write_pid

from hirocli.constants import DEVICE_ID_PREFIX, DEVICE_ID_SUFFIX_LENGTH, ENV_ADMIN_UI, ENV_WORKSPACE_PATH, PID_FILENAME

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
                "HIRO_WORKSPACE_PATH environment variable is not set. "
                "The server process must be started via 'hirocli start'."
            )
        workspace_path = Path(ws_str)

    from hiro_channel_sdk import log_setup
    from hirocli.domain.config import load_config, mark_connected, mark_disconnected, resolve_log_dir
    from hirocli.domain.crypto import load_or_create_master_key
    from hirocli.domain.db import ensure_db
    from hirocli.domain.pairing import (
        ApprovedDevice,
        clear_pairing_session,
        load_pairing_session,
        upsert_approved_device,
    )
    from hirocli.runtime.agent_manager import AgentManager
    from hirocli.runtime.channel_event_handler import ChannelEventHandler
    from hirocli.runtime.channel_manager import ChannelManager
    from hirocli.runtime.communication_manager import CommunicationManager
    from hirocli.runtime.event_handler import EventHandler
    from hirocli.runtime.http_server import (
        run_http_server,
        set_channel_info_provider,
        set_stop_event,
        set_tool_registry,
        set_workspace_path,
    )
    from hirocli.runtime.message_adapter import MessageAdapterPipeline
    from hirocli.runtime.request_handler import RequestHandler
    from hirocli.runtime.adapters.audio_adapter import AudioTranscriptionAdapter
    from hirocli.runtime.adapters.image_adapter import ImageUnderstandingAdapter
    from hirocli.services.stt import GeminiSTTProvider, OpenAISTTProvider, STTService
    from hirocli.services.vision_service import VisionService
    from hirocli.tools import all_tools
    from hirocli.tools.registry import ToolRegistry

    config = load_config(workspace_path)
    log_dir = resolve_log_dir(workspace_path, config)
    log_setup.init(
        "server",
        log_dir,
        foreground=foreground,
        log_levels=config.log_levels or None,
    )
    log.info(
        "Config loaded",
        workspace=str(workspace_path),
        http_port=config.http_port,
        plugin_port=config.plugin_port,
        admin_port=config.admin_port,
        gateway_url=config.gateway_url,
        log_dir=str(log_dir),
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
    log.info("Tool registry ready", tools=len(tool_registry._tools))

    # ------------------------------------------------------------------
    # Shared media services — one instance each, used by both the adapter
    # pipeline and the agent/tool layer via TranscribeTool / DescribeImageTool.
    # ------------------------------------------------------------------
    stt_service = STTService(providers=[
        OpenAISTTProvider(),
        GeminiSTTProvider(),
    ])
    log.info("STT service ready", providers=["openai", "gemini"])
    vision_service = VisionService()
    log.info("Vision service ready")

    # ------------------------------------------------------------------
    # Adapter pipeline
    # ------------------------------------------------------------------
    adapter_pipeline = MessageAdapterPipeline([
        AudioTranscriptionAdapter(service=stt_service),
        ImageUnderstandingAdapter(service=vision_service),
    ])
    log.info("Adapter pipeline ready", adapters=["audio_transcription", "image_understanding"])

    # ------------------------------------------------------------------
    # Message handlers (constructed before CommunicationManager so they
    # can be injected at construction time)
    # ------------------------------------------------------------------
    event_handler = EventHandler()

    # CommunicationManager is created first; RequestHandler receives a ref
    # so it can enqueue responses via comm_manager.enqueue_outbound.
    comm_manager = CommunicationManager(
        adapter_pipeline=adapter_pipeline,
        event_handler=event_handler,
    )

    request_handler = RequestHandler(comm_manager, workspace_path)
    comm_manager._request_handler = request_handler  # inject after both are constructed
    log.info("Communication manager ready")

    # ------------------------------------------------------------------
    # Channel event handler (infrastructure: pairing, connectivity)
    # ------------------------------------------------------------------
    channel_manager_ref: ChannelManager | None = None

    async def _handle_pairing_request(data: dict) -> None:
        if channel_manager_ref is None:
            return
        request_id = data.get("request_id")
        pairing_code = data.get("pairing_code")
        device_public_key = data.get("device_public_key")
        device_name_raw = data.get("device_name")
        device_name = device_name_raw if isinstance(device_name_raw, str) and device_name_raw else None

        if not isinstance(request_id, str) or not request_id:
            return
        if not isinstance(pairing_code, str) or not pairing_code:
            await channel_manager_ref.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_pairing_code"},
            )
            return
        if not isinstance(device_public_key, str) or not device_public_key:
            await channel_manager_ref.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "invalid_device_public_key"},
            )
            return

        session = load_pairing_session(workspace_path)
        if session is None:
            await channel_manager_ref.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "no_active_pairing_session"},
            )
            return

        if (not session.is_valid()) or (session.code != pairing_code):
            await channel_manager_ref.send_event_to_channel(
                "devices", "pairing_response",
                {"request_id": request_id, "status": "rejected", "reason": "pairing_code_invalid_or_expired"},
            )
            return

        from hiro_commons.attestation import create_device_attestation

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
        await channel_manager_ref.send_event_to_channel(
            "devices", "pairing_response",
            {
                "request_id": request_id,
                "status": "approved",
                "device_id": device_id,
                "attestation": attestation,
            },
        )

    async def _handle_gateway_connected(data: dict) -> None:
        gateway_url = str(data.get("gateway_url") or config.gateway_url)
        mark_connected(workspace_path, gateway_url)

    async def _handle_gateway_disconnected(data: dict) -> None:
        mark_disconnected(workspace_path)

    channel_event_handler = ChannelEventHandler()
    channel_event_handler.register("pairing_request", _handle_pairing_request)
    channel_event_handler.register("gateway_connected", _handle_gateway_connected)
    channel_event_handler.register("gateway_disconnected", _handle_gateway_disconnected)
    log.info("Channel event handler ready",
             events=["pairing_request", "gateway_connected", "gateway_disconnected"])

    # ------------------------------------------------------------------
    # Channel and communication managers
    # ------------------------------------------------------------------
    channel_manager = ChannelManager(
        config,
        workspace_path,
        stop_event,
        on_message=comm_manager.receive,
        on_event=channel_event_handler.handle,
    )
    channel_manager_ref = channel_manager
    comm_manager.set_channel_manager(channel_manager)
    set_channel_info_provider(channel_manager.get_channel_info)

    agent_manager = AgentManager(comm_manager, workspace_path)

    # Log agent configuration at startup so the log viewer shows which model is in use.
    try:
        from ..domain.agent_config import load_agent_config as _load_agent_cfg
        _agent_cfg = _load_agent_cfg(workspace_path)
        log.info(
            "Agent config loaded",
            model=_agent_cfg.model,
            provider=_agent_cfg.provider,
            temperature=_agent_cfg.temperature,
            max_tokens=_agent_cfg.max_tokens,
        )
    except Exception:
        log.info("Agent config loaded (using defaults)")

    def _shutdown(*_: object) -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, _shutdown)

    log.info(
        "Server startup complete — launching components",
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
        from hirocli.ui.run import run_admin_ui
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

    from hirocli.runtime.http_server import get_restart_admin, is_restart_requested

    if is_restart_requested():
        log.info("Restart requested — spawning new server process")
        _spawn_server(workspace_path, admin=get_restart_admin())

    mark_disconnected(workspace_path)
    log.info("hirocli server exited")


def _spawn_server(workspace_path: Path, admin: bool = False) -> None:
    """Spawn a new detached server process (used for self-restart).

    Uses spawn_detached from hiro_commons; the new child writes its own PID
    via write_pid() at startup, so we don't write it here.
    """
    from hiro_commons.process import remove_pid, spawn_detached, uv_python_cmd

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
    _admin = os.environ.get(ENV_ADMIN_UI) == "1"
    asyncio.run(_main(admin=_admin))
