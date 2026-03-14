"""Agents page — view agent configuration, registered tools, and coming-soon sections.

Implemented sections:
  - Configuration: provider, model, temperature, max_tokens, system prompt (read-only).
    Source: load_agent_config() and load_system_prompt() from the workspace DB.
  - Registered tools: expandable list of all tools the agent can invoke, with their
    description and parameter schemas. Source: all_tools().

Coming-soon placeholder sections (not yet built):
  - Tool call history / audit log
  - Active conversations
  - Conversation memory
  - Model configuration (edit model / parameters)
  - Token usage statistics
"""

from __future__ import annotations

from pathlib import Path

from nicegui import app as nicegui_app, ui

_PLACEHOLDERS = [
    ("history", "Tool call history"),
    ("forum", "Active conversations"),
    ("psychology", "Conversation memory"),
    ("tune", "Model configuration"),
    ("analytics", "Token usage"),
]


@ui.page("/agents")
async def agents_page() -> None:
    from hirocli.domain.agent_config import load_agent_config, load_system_prompt
    from hirocli.domain.workspace import resolve_workspace
    from hirocli.tools import all_tools
    from hirocli.ui.app import create_page_layout

    create_page_layout(active_path="/agents")

    # ------------------------------------------------------------------ refreshable config
    @ui.refreshable
    def config_section() -> None:
        ws_name: str | None = nicegui_app.storage.user.get("selected_workspace")
        if ws_name is None:
            ui.label("No workspaces available.").classes("opacity-60 text-sm")
            return

        error: str | None = None
        agent_cfg = None
        system_prompt = ""
        try:
            entry, _ = resolve_workspace(ws_name)
            ws_path = Path(entry.path)
            agent_cfg = load_agent_config(ws_path)
            system_prompt = load_system_prompt(ws_path)
        except Exception as exc:
            error = str(exc)

        if error:
            ui.label(f"Error loading agent config: {error}").classes("text-negative")
            return

        with ui.card().classes("w-full"):
            ui.label("Configuration").classes("text-base font-semibold mb-3")
            with ui.grid(columns=2).classes("gap-x-6 gap-y-1 w-full max-w-lg"):
                _config_row("Provider", agent_cfg.provider)
                _config_row("Model", agent_cfg.model)
                _config_row("Temperature", str(agent_cfg.temperature))
                _config_row("Max tokens", str(agent_cfg.max_tokens))

            ui.separator().classes("my-3")
            ui.label("System prompt").classes("text-sm font-medium opacity-70 mb-1")
            ui.label(system_prompt).classes(
                "text-sm font-mono opacity-80 whitespace-pre-wrap bg-black/5 rounded p-3 w-full"
            )

    # ------------------------------------------------------------------ page layout
    with ui.column().classes("w-full gap-6 p-6"):
        ui.label("Agents").classes("text-2xl font-semibold")

        # ---- Agent configuration (workspace-scoped)
        config_section()

        # ---- Registered tools (same for all workspaces — built from all_tools())
        with ui.card().classes("w-full"):
            ui.label("Registered tools").classes("text-base font-semibold mb-1")
            ui.label(
                "All tools the agent can invoke. Parameters marked optional are not required."
            ).classes("text-sm opacity-60 mb-3")

            tools = all_tools()
            for tool in tools:
                with ui.expansion(tool.name, icon="build").classes("w-full border-b last:border-0"):
                    ui.label(tool.description).classes("text-sm opacity-70 mb-2")
                    if tool.params:
                        with ui.column().classes("gap-1"):
                            for param_name, param in tool.params.items():
                                with ui.row().classes("items-baseline gap-2 flex-wrap"):
                                    ui.label(param_name).classes(
                                        "text-sm font-mono font-medium min-w-36"
                                    )
                                    ui.label(param.type_.__name__).classes(
                                        "text-xs font-mono opacity-50"
                                    )
                                    ui.label(param.description).classes("text-sm opacity-60")
                                    if not param.required:
                                        ui.badge("optional").props("outline dense")
                    else:
                        ui.label("No parameters.").classes("text-sm opacity-40")

        # ---- Coming-soon placeholder sections
        for icon, title in _PLACEHOLDERS:
            with ui.card().classes("w-full"):
                with ui.row().classes("items-center justify-between"):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon(icon).classes("opacity-40")
                        ui.label(title).classes("text-base font-semibold")
                    ui.badge("Coming soon").props("outline")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config_row(label: str, value: str) -> None:
    ui.label(label).classes("text-sm font-medium opacity-60")
    ui.label(value).classes("text-sm font-mono")
