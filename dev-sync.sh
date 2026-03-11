#!/usr/bin/env bash
# Run from the repo root after every git pull or when switching environments: ./dev-sync.sh
# Keeps workspace dependencies and all installed tool binaries in sync.

set -e

# Stop the server if running so Windows releases the file lock on phbcli.exe
echo "==> Stopping phbcli server (if running)..."
phbcli stop 2>/dev/null || true

echo "==> Syncing phbserver workspace dependencies..."
cd phbserver
uv sync

echo "==> Updating phbcli tool binary..."
# --upgrade refreshes packages in-place without deleting the venv (avoids Windows file-lock errors on Scripts/).
# --force overwrites the entry-point script in ~/.local/bin (needed when the script was left behind by a prior failed install).
# phb-channel-devices is bundled as a script in phbcli's pyproject.toml, so this single install covers both binaries.
uv tool install --editable phbcli --upgrade --force

echo ""
echo "Done. All tool binaries are up to date."
echo "  phbcli              -> run: phbcli --help"
echo "  phb-channel-devices -> run: phb-channel-devices --help  (bundled with phbcli)"
echo "  gateway             -> run: uv run phbgateway --help  (workspace, no binary needed)"
