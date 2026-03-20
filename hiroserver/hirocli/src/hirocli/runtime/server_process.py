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
import os
import signal
import sys
from pathlib import Path

from hiro_commons.log import Logger
from hiro_commons.process import remove_pid, spawn_detached, uv_python_cmd, write_pid

from hirocli.constants import ENV_ADMIN_UI, ENV_WORKSPACE, ENV_WORKSPACE_PATH, PID_FILENAME
from hirocli.domain.config import load_config, mark_disconnected, resolve_log_dir
from hirocli.domain.crypto import load_or_create_master_key
from hirocli.domain.db import ensure_db
from hirocli.runtime.agent_manager import AgentManager
from hirocli.runtime.channel_event_handler import ChannelEventHandler
from hirocli.runtime.channel_manager import ChannelManager
from hirocli.runtime.communication_manager import CommunicationManager
from hirocli.runtime.event_handler import EventHandler
from hirocli.runtime.http_server import (
    get_restart_admin,
    is_restart_requested,
    run_http_server,
    set_channel_info_provider,
    set_stop_event,
    set_tool_registry,
    set_workspace_path,
)
from hirocli.runtime.infra_event_handlers import InfraEventHandlers
from hirocli.runtime.message_adapter import MessageAdapterPipeline
from hirocli.runtime.request_handler import RequestHandler
from hirocli.runtime.adapters.audio_adapter import AudioTranscriptionAdapter
from hirocli.runtime.adapters.image_adapter import ImageUnderstandingAdapter
from hirocli.services.stt import GeminiSTTProvider, OpenAISTTProvider, STTService
from hirocli.services.vision_service import VisionService
from hirocli.tools import all_tools
from hirocli.tools.registry import ToolRegistry

log = Logger.get("SERVER")


async def _main(
    foreground: bool = False,
    workspace_path: Path | None = None,
    workspace_name: str | None = None,
    admin: bool = False,
) -> None:

    # Get workspace path or get out

    if workspace_path is None:
        ws_str = os.environ.get(ENV_WORKSPACE_PATH)
        if not ws_str:
            raise RuntimeError(
                "HIRO_WORKSPACE_PATH environment variable is not set. "
                "The server process must be started via 'hirocli start'."
            )
        workspace_path = Path(ws_str)
    if workspace_name is None:
        workspace_name = os.environ.get(ENV_WORKSPACE) or workspace_path.name

    # Load Config and Setup Logging

    config = load_config(workspace_path)
    log_dir = resolve_log_dir(workspace_path, config)

    # Should we take these 2 lines out to module level?

    # Centralised routed sinks: server.log (exclude CLI.*) + cli.log (include CLI.*)
    Logger.configure(level="INFO", console=foreground)
    Logger.open_log_dir(log_dir, level="INFO")

    
    # Suppress websockets info noise ("server listening", "connection open", etc.)
    # and bridge warnings/errors into the structured logger.
    Logger.silence_stdlib("websockets", module="WEBSOCKET", level="WARNING")
    if config.log_levels:
        Logger.apply_level_overrides(config.log_levels)
    log.info("Hiro Server starting...", workspace=workspace_name, foreground=foreground, admin=admin)
    log.info(
        f"Loaded workspace '{workspace_name}' config",
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
    log.info(f"Loaded Tool Definitions: ({len(tool_registry._tools)})")

    # ------------------------------------------------------------------
    # Shared media services — one instance each, used by both the adapter
    # pipeline and the agent/tool layer via TranscribeTool / DescribeImageTool.
    # ------------------------------------------------------------------
    log.info("Loading Media Services")
    log.info("== Loading Speech to Text Services")
    stt_service = STTService(providers=[
        OpenAISTTProvider(),
        GeminiSTTProvider(),
    ])
    log.info("== Loading Vision Services")
    vision_service = VisionService()

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
    infra_handlers = InfraEventHandlers(workspace_path, config, desktop_private_key)
    channel_event_handler = ChannelEventHandler()
    infra_handlers.register_all(channel_event_handler)

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
    infra_handlers.set_channel_manager(channel_manager)
    comm_manager.set_channel_manager(channel_manager)
    set_channel_info_provider(channel_manager.get_channel_info)

    agent_manager = AgentManager(comm_manager, workspace_path)

    # Log agent configuration at startup so the log viewer shows which model is in use.
    try:
        from hirocli.domain.agent_config import load_agent_config as _load_agent_cfg
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
    _ws_name = os.environ.get(ENV_WORKSPACE) or None
    asyncio.run(_main(workspace_name=_ws_name, admin=_admin))
