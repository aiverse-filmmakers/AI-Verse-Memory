#!/usr/bin/env bash
set -euo pipefail

TARGET="${AI_VERSE_MEMORY_TARGET:-$PWD}"
SOURCE_REF="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
RELEASE_REF="031e1e77c97ed3c9012235c7ffe0a4ece05e3695"
RELEASE_BASE="https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/$RELEASE_REF"

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

# A real repository checkout installs its local sources. Remote bootstrap is
# pinned to the immutable public-beta payload commit above.
if [[ -n "$SCRIPT_DIR" && -f "$SCRIPT_DIR/scripts/install.py" && -f "$SCRIPT_DIR/manifest.json" ]] \
  && grep -q '"name"[[:space:]]*:[[:space:]]*"ai-verse-memory"' "$SCRIPT_DIR/manifest.json" 2>/dev/null; then
  "$PYTHON" "$SCRIPT_DIR/scripts/install.py" --target "$TARGET" --source-dir "$SCRIPT_DIR"
  exit $?
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export AI_VERSE_MEMORY_RELEASE_REF="$RELEASE_REF"
export AI_VERSE_MEMORY_BASE_URL="$RELEASE_BASE"
BASE="$RELEASE_BASE/scripts"
for FILE in install.py install_engine.py os_compat.py; do
  URL="$BASE/$FILE"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$URL" -o "$TMP/$FILE"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$URL" -O "$TMP/$FILE"
  else
    printf 'AI-Verse Memory install error: curl or wget is required for remote installation.\n' >&2
    exit 1
  fi
done
"$PYTHON" "$TMP/install.py" --target "$TARGET"
