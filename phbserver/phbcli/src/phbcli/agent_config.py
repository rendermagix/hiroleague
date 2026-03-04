"""Agent configuration management for phbcli.

All functions are workspace-scoped — they accept workspace_path: Path.
Files live at:
  <workspace>/agent/config.json
  <workspace>/agent/system_prompt.md
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_DEFAULT_SYSTEM_PROMPT = """\
You are a helpful home assistant running on Private Home Box.
Answer questions concisely and helpfully.
"""

_DEFAULT_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4.1-mini",
    "temperature": 0.7,
    "max_tokens": 1024,
}


class AgentConfig(BaseModel):
    """LLM provider and generation settings for the agent."""

    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)

    @property
    def model_string(self) -> str:
        """Return the 'provider:model' identifier used by init_chat_model."""
        return f"{self.provider}:{self.model}"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def workspace_agent_dir(workspace_path: Path) -> Path:
    return workspace_path / "agent"


def _agent_config_file(workspace_path: Path) -> Path:
    return workspace_agent_dir(workspace_path) / "config.json"


def _agent_system_prompt_file(workspace_path: Path) -> Path:
    return workspace_agent_dir(workspace_path) / "system_prompt.md"


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def load_agent_config(workspace_path: Path) -> AgentConfig:
    """Load agent config from workspace, writing defaults if absent."""
    agent_dir = workspace_agent_dir(workspace_path)
    agent_dir.mkdir(parents=True, exist_ok=True)
    config_file = _agent_config_file(workspace_path)
    if config_file.exists():
        try:
            return AgentConfig.model_validate_json(config_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse agent config, using defaults: %s", exc)
    else:
        _write_default_config(workspace_path)
    return AgentConfig()


def save_agent_config(workspace_path: Path, config: AgentConfig) -> None:
    agent_dir = workspace_agent_dir(workspace_path)
    agent_dir.mkdir(parents=True, exist_ok=True)
    _agent_config_file(workspace_path).write_text(
        config.model_dump_json(indent=2), encoding="utf-8"
    )


def load_system_prompt(workspace_path: Path) -> str:
    """Load the system prompt from workspace, writing the default if absent."""
    agent_dir = workspace_agent_dir(workspace_path)
    agent_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = _agent_system_prompt_file(workspace_path)
    if prompt_file.exists():
        return prompt_file.read_text(encoding="utf-8").strip()
    _write_default_system_prompt(workspace_path)
    return _DEFAULT_SYSTEM_PROMPT.strip()


def _write_default_config(workspace_path: Path) -> None:
    config_file = _agent_config_file(workspace_path)
    config_file.write_text(json.dumps(_DEFAULT_CONFIG, indent=2), encoding="utf-8")
    logger.info("Created default agent config at %s", config_file)


def _write_default_system_prompt(workspace_path: Path) -> None:
    prompt_file = _agent_system_prompt_file(workspace_path)
    prompt_file.write_text(_DEFAULT_SYSTEM_PROMPT, encoding="utf-8")
    logger.info("Created default system prompt at %s", prompt_file)
