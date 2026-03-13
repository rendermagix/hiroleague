#!/usr/bin/env bash
# Version-gated Flutter wrapper.
# Reads the required Flutter version from .fvmrc and aborts if the globally
# installed version does not match, preventing silent SDK mismatches.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FVMRC="$SCRIPT_DIR/.fvmrc"

# Parse required version from .fvmrc  e.g. {"flutter":"3.41.4"}
REQUIRED=$(grep -oE '"flutter"[[:space:]]*:[[:space:]]*"[^"]+"' "$FVMRC" \
           | grep -oE '[0-9]+\.[0-9]+\.[0-9]+')

if [[ -z "$REQUIRED" ]]; then
  echo "❌ Could not read required Flutter version from $FVMRC"
  exit 1
fi

ACTUAL=$(flutter --version 2>/dev/null \
         | grep -E '^Flutter ' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)

if [[ -z "$ACTUAL" ]]; then
  echo "❌ Flutter is not installed or not on PATH."
  echo "   Install Flutter $REQUIRED from: https://docs.flutter.dev/release/archive"
  exit 1
fi

if [[ "$ACTUAL" != "$REQUIRED" ]]; then
  echo "❌ Flutter version mismatch."
  echo "   Required : $REQUIRED  (pinned in .fvmrc)"
  echo "   Installed: $ACTUAL"
  echo ""
  echo "   Upgrade  : flutter upgrade"
  echo "   Downgrade: https://docs.flutter.dev/release/archive"
  exit 1
fi

exec flutter "$@"
