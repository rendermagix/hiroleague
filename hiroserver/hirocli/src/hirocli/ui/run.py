"""Admin UI coroutine — started alongside the HTTP server when --admin is set.

Uses `ui.run_with()` to mount NiceGUI onto a dedicated FastAPI app, then
serves that app with Uvicorn in the same event loop — identical to how
`run_http_server` works.  No extra thread or event loop required.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from hiro_commons.log import Logger

from hirocli.domain.config import Config

log = Logger.get("ADMIN")


async def run_admin_ui(
    config: Config,
    stop_event: asyncio.Event,
    log_dir: Path | None = None,
    workspace_path: Path | None = None,
) -> None:
    """Start the NiceGUI admin UI and shut it down when stop_event fires."""
    from nicegui import ui

    from hirocli.ui import state
    from hirocli.ui.app import register_pages

    state.log_dir = log_dir
    state.workspace_path = workspace_path

    # Resolve gateway log dir from the default gateway instance so the logs page
    # can display gateway.log alongside server and plugin logs.
    try:
        from hirogateway.instance import load_registry as _load_gw_registry
        from hirogateway.config import load_config as _load_gw_config, resolve_log_dir as _gw_resolve_log_dir
        _gw_registry = _load_gw_registry()
        if _gw_registry.instances:
            _gw_name = _gw_registry.default_instance or next(iter(_gw_registry.instances))
            _gw_entry = _gw_registry.instances.get(_gw_name)
            if _gw_entry is not None:
                _gw_instance_path = Path(_gw_entry.path)
                _gw_config = _load_gw_config(_gw_instance_path)
                state.gateway_log_dir = _gw_resolve_log_dir(_gw_instance_path, _gw_config)
    except Exception:
        pass

    # Resolve the workspace id and name so pages can identify the current workspace.
    if workspace_path is not None:
        try:
            from hirocli.domain.workspace import load_registry
            registry = load_registry()
            for ws_id, entry in registry.workspaces.items():
                if Path(entry.path).resolve() == workspace_path.resolve():
                    state.workspace_id = ws_id
                    state.workspace_name = entry.name
                    break
        except Exception:
            pass

    register_pages()

    # Dedicated FastAPI app so NiceGUI gets its own port, separate from the
    # HTTP API.  ui.run_with() sets has_run_config and mounts NiceGUI's
    # routes/static assets onto this app.
    # Note: run_with() hardcodes reload=False internally — do not pass it.
    admin_app = FastAPI(title="Hiro Admin")
    # storage_secret enables app.storage.user (per-browser persistent storage)
    # used for the dark mode preference. Derived from the device ID so it is
    # stable across server restarts without needing an extra config field.
    ui.run_with(
        admin_app,
        title="Hiro Admin",
        show_welcome_message=False,
        storage_secret=f"hiro-admin-{config.device_id}",
    )

    log.info("Admin UI starting", url=f"http://127.0.0.1:{config.admin_port}")

    uv_config = uvicorn.Config(
        app=admin_app,
        host="127.0.0.1",
        port=config.admin_port,
        log_level="warning",
        loop="none",
    )
    server = uvicorn.Server(uv_config)

    serve_task = asyncio.create_task(server.serve())
    stop_task = asyncio.create_task(stop_event.wait())

    done, pending = await asyncio.wait(
        [serve_task, stop_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if stop_task in done:
        server.should_exit = True
        await serve_task

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    log.info("Admin UI stopped")
