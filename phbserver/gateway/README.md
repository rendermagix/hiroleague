# phbgateway

**Private Home Box Gateway** — WebSocket relay server.

Accepts connections from `phbcli` desktop clients and online apps, performs
challenge/response authentication, and relays messages between authenticated
devices identified by `device_id`.

## Dev setup

`phbgateway` is part of the `phbserver` uv workspace. No separate tool install is needed — it runs directly from the workspace venv via `uv run`.

After cloning or pulling updated code, run from the repo root:

```bash
./dev-sync.sh
```

Or manually:

```bash
cd phbserver
uv sync
```

## Quick Start

```bash
# Create a named gateway instance (mandatory values at creation)
uv run phbgateway instance create home --port 8765 --desktop-pubkey "<base64-public-key>" --set-default

# Start the instance later using only its name/default
uv run phbgateway start --instance home
# or simply:
uv run phbgateway
```

## Instance model

Each gateway runs as a named instance with persistent config:

- `name` (instance identity)
- `host` and `port` (bind address)
- `desktop_public_key` trust root
- `log_dir` (optional override)

Instance commands:

```bash
phbgateway instance list
phbgateway instance show home
phbgateway instance set-default home
phbgateway instance remove home --purge
```

## How it works

1. Every new socket receives an auth challenge nonce.
2. A desktop client authenticates using its master key (`auth_mode=desktop`) against
   the desktop trust root configured at startup (`--desktop-pubkey`).
3. A device client authenticates with desktop attestation + nonce signature
   (`auth_mode=device`).
4. Once authenticated, messages are relayed by `device_id`.

## Message Format

```json
{
  "target_device_id": "uuid-of-the-target-device",
  "payload": { ... }
}
```

If `target_device_id` is omitted, the message is broadcast to all connected devices.
