#!/usr/bin/env bash
set -euo pipefail

TARGET="${AI_VERSE_MEMORY_TARGET:-$PWD}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  printf 'AI-Verse Memory install error: Python 3 is required.\n' >&2
  exit 1
fi

if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/install.py" ]]; then
  "$PYTHON" "$SCRIPT_DIR/scripts/install.py" --target "$TARGET" --source-dir "$SCRIPT_DIR"
  exit $?
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
URL="https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/scripts/install.py"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$URL" -o "$TMP/install.py"
elif command -v wget >/dev/null 2>&1; then
  wget -q "$URL" -O "$TMP/install.py"
else
  printf 'AI-Verse Memory install error: curl or wget is required for remote installation.\n' >&2
  exit 1
fi
"$PYTHON" "$TMP/install.py" --target "$TARGET"
