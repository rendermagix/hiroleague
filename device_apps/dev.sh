#!/usr/bin/env bash
# dev.sh — developer task runner for device_apps.
# Always verifies the pinned Flutter version (via flutter_build.sh) before
# running any Flutter or Dart command.
#
# Usage: ./dev.sh [--outdated] [--codegen] [--web] [--android] [--all]
#
#   --outdated   List packages with newer versions available
#   --codegen    Run build_runner (freezed / riverpod_generator / drift)
#   --web        Build Flutter web  (output: build/web/)
#   --android    Build Flutter APK for arm64-v8a — Samsung Galaxy S22+ and
#                all modern 64-bit Android devices
#                (output: build/app/outputs/flutter-apk/)
#   --all        Shorthand for --codegen --web --android
#
#   Options can be combined, e.g.: ./dev.sh --codegen --android
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUTTER="$SCRIPT_DIR/flutter_build.sh"

# ── helpers ──────────────────────────────────────────────────────────────────

step() { echo ""; echo "━━━ $1 ━━━"; echo ""; }

usage() {
  grep '^#' "$0" | grep -v '#!/' | sed 's/^# \{0,1\}//'
  exit 0
}

# ── argument parsing ──────────────────────────────────────────────────────────

if [[ $# -eq 0 ]]; then
  usage
fi

DO_OUTDATED=false
DO_CODEGEN=false
DO_WEB=false
DO_ANDROID=false

for arg in "$@"; do
  case $arg in
    --outdated) DO_OUTDATED=true ;;
    --codegen)  DO_CODEGEN=true ;;
    --web)      DO_WEB=true ;;
    --android)  DO_ANDROID=true ;;
    --all)      DO_CODEGEN=true; DO_WEB=true; DO_ANDROID=true ;;
    -h|--help)  usage ;;
    *)
      echo "❌ Unknown option: $arg"
      echo "   Run ./dev.sh --help for usage."
      exit 1
      ;;
  esac
done

# ── version check (fast, runs flutter --version via flutter_build.sh) ─────────

step "Verifying Flutter version"
"$FLUTTER" --version

# ── tasks ────────────────────────────────────────────────────────────────────

if [[ "$DO_OUTDATED" == true ]]; then
  step "Checking for outdated packages"
  "$FLUTTER" pub outdated
fi

if [[ "$DO_CODEGEN" == true ]]; then
  step "Running code generation (build_runner)"
  dart run build_runner build --delete-conflicting-outputs
fi

if [[ "$DO_WEB" == true ]]; then
  step "Building Flutter web"
  "$FLUTTER" build web
fi

if [[ "$DO_ANDROID" == true ]]; then
  step "Building Flutter APK (arm64-v8a)"
  "$FLUTTER" build apk --target-platform android-arm64
fi

echo ""
echo "✅  All done."
