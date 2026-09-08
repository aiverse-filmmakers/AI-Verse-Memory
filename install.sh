#!/usr/bin/env bash
set -euo pipefail

TARGET="${AI_VERSE_MEMORY_TARGET:-$PWD}"
SOURCE_REF="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""

if [[ -n "$SOURCE_REF" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SOURCE_REF")" 2>/dev/null && pwd || true)"
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  printf 'AI-Verse Memory install error: Python 3 is required.\n' >&2
  exit 1
fi

# Use repository-local sources only when this script is actually being run from
# an AI-Verse Memory checkout. A piped `curl | bash` has no trustworthy script path.
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/install.py" && -f "$SCRIPT_DIR/manifest.json" ]] \
  && grep -q '"name"[[:space:]]*:[[:space:]]*"ai-verse-memory"' "$SCRIPT_DIR/manifest.json" 2>/dev/null; then
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
