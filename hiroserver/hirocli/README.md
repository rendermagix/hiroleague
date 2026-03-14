# hirocli

**Hiro CLI** — desktop server with WebSocket gateway client.

## Installation from PyPI

```bash
pip install hirocli
```

## Installation from source

```bash
cd hiroserver
uv sync
uv tool install --editable hirocli
```

This installs both `hirocli` and `hiro-channel-devices` binaries — the mandatory channel is bundled as a script entry in `hirocli`'s `pyproject.toml`.

### After pulling updated code

Run from the repo root every time you pull changes or switch environments:

```bash
./dev-sync.sh
```

> **Why not just `uv sync`?** `hirocli` is a `uv tool` — its entry-point scripts are baked at install time. If `pyproject.toml` or the package structure changes, the old script will fail with `ModuleNotFoundError`. `dev-sync.sh` stops the server (to release Windows file locks), syncs deps, and re-installs the tool.

## Quick Start

```bash
# One-time setup: configure gateway, generate device ID, register auto-start
hirocli setup

# If needed on Windows, request UAC to create elevated scheduled task
hirocli setup --elevated-task

# Manual start / stop
hirocli start
hirocli stop

# Start in foreground with live log output (server + all plugin logs)
hirocli start --foreground
hirocli start -f

# Check status
hirocli status

# Device pairing helpers
hirocli device add
hirocli device list
hirocli device revoke <device_id>

# Cleanup auto-start and running process
hirocli teardown

# Full uninstall flow (teardown + prints final package uninstall command)
hirocli uninstall
```

## Commands

| Command | Description |
|---------|-------------|
| `setup` | Interactive first-time configuration. Creates `~/.hirocli/`, generates device ID, registers Windows auto-start, then starts the server. On Windows it tries Task Scheduler first, then falls back to HKCU Run key if needed. |
| `start` | Start the background server (FastAPI HTTP + plugin manager). |
| `start -f` / `start --foreground` | Run the server in the foreground with live log output. Server logs and all plugin logs stream to the terminal. Ctrl+C to stop. |
| `stop`  | Stop the running server. |
| `status`| Show whether the server is running, WebSocket connection state, last connection time, and gateway URL. |
| `device add` | Generate a short-lived numeric pairing code for onboarding a mobile device. |
| `device list` | List approved paired devices. |
| `device revoke <id>` | Revoke an approved device by device_id. |
| `teardown`| Stop the server and remove auto-start entries (Task Scheduler + Registry). Optional: `--purge` to remove `~/.hirocli/`; `--elevated-task` for elevated task removal. |
| `uninstall`| Runs teardown, then prints package uninstall command (`uv tool uninstall hirocli` or `pip uninstall hirocli`). |

## Windows Auto-Start Behavior

- Default `setup` flow:
  1. Attempt Task Scheduler (`schtasks`, run-level `LIMITED`)
  2. If unavailable/denied, fall back to `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- Use `--elevated-task` to request UAC and create/delete a `run-level: HIGHEST` scheduled task.

## App Directory

All runtime data is stored in `~/.hirocli/`:

- `config.json` — device ID, gateway URL, and logging settings (`log_dir`, `log_levels`)
- `state.json` — live WebSocket connection state (updated by the running server)
- `hirocli.pid` — PID of the running server process
- `master_key.pem` — desktop Ed25519 master key used for gateway authentication
- `pairing_session.json` — current active pairing code and expiry
- `devices.json` — approved paired devices
- `logs/server.log` — hirocli server log (rotating, 5 MB × 5 backups)
- `logs/plugin-<name>.log` — one log file per channel plugin subprocess

## HTTP API

When running, the server exposes a local HTTP API at `http://127.0.0.1:18080`:

- `GET /status` — returns server/connection status as JSON
- `GET /channels` — returns list of currently connected channel plugins (name, version, description)
