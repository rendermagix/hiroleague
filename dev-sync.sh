#!/usr/bin/env bash
# Run from the repo root after every git pull or when switching environments: ./dev-sync.sh
# Keeps workspace dependencies and all installed tool binaries in sync.

set -e

# Stop the server if running so Windows releases the file lock on hirocli.exe
echo "==> Stopping hirocli server (if running)..."
hirocli stop 2>/dev/null || true

echo "==> Stopping hiro-channel-devices (if running)..."
# Git Bash/MSYS can rewrite /F-style args unless conversion is disabled.
MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hiro-channel-devices.exe 2>/dev/null || true

echo "==> Stopping hirogateway (if running)..."
# Stop gateway process so Windows releases the file lock on hirogateway.exe before reinstalling.
MSYS2_ARG_CONV_EXCL='*' taskkill.exe /F /T /IM hirogateway.exe 2>/dev/null || true

echo "==> Syncing hiroserver workspace dependencies..."
cd hiroserver
uv sync

echo "==> Updating hirocli tool binary..."
# --upgrade refreshes packages in-place without deleting the venv (avoids Windows file-lock errors on Scripts/).
# --force overwrites the entry-point script in ~/.local/bin (needed when the script was left behind by a prior failed install).
# hiro-channel-devices is bundled as a script in hirocli's pyproject.toml, so this single install covers both binaries.
uv tool install --editable hirocli --upgrade --force

echo "==> Updating hirogateway tool binary..."
uv tool install --editable gateway --upgrade --force

echo ""
echo "Done. All tool binaries are up to date."
echo "  hirocli              -> run: hirocli --help"
echo "  hiro-channel-devices -> run: hiro-channel-devices --help  (bundled with hirocli)"
echo "  hirogateway          -> run: hirogateway --help"
