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

TMP="$(mktemp -d "${TMPDIR:-/tmp}/ai-verse-memory.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
REPO_RAW="https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory"
die() {
  printf 'AI-Verse Memory install error: %s\n' "$1" >&2
  exit 2
}
fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -q "$1" -O "$2"
  else
    die "curl or wget is required for remote installation."
  fi
}
# Members get the accepted release: the commit recorded in release/component-release.json.
# AI_VERSE_MEMORY_RELEASE_REF overrides it (developers only). Never falls back to main.
REF="${AI_VERSE_MEMORY_RELEASE_REF:-}"
if [[ -z "$REF" ]]; then
  fetch "$REPO_RAW/main/release/component-release.json" "$TMP/component-release.json" \
    || die "Could not download the release file. Check your internet connection and try again."
  set +e
  REF="$("$PYTHON" -c '
import json, re, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    if not isinstance(d, dict):
        raise ValueError
except Exception:
    sys.exit(3)
if d.get("release_status") != "accepted":
    sys.exit(4)
r = str(d.get("revision", ""))
if not re.fullmatch(r"[0-9a-f]{40}", r):
    sys.exit(5)
print(r)
' "$TMP/component-release.json" 2>/dev/null)"
  CODE=$?
  set -e
  case "$CODE" in
    0) ;;
    3) die "The release file is not valid. Please try again later or report this." ;;
    4) die "No accepted release is available yet. Please try again later." ;;
    5) die "The release file does not name a valid release. Please report this." ;;
    *) die "Could not read the release file." ;;
  esac
fi
export AI_VERSE_MEMORY_RELEASE_REF="$REF"
BASE="$REPO_RAW/$REF/scripts"
for FILE in install.py install_engine.py os_compat.py; do
  fetch "$BASE/$FILE" "$TMP/$FILE" \
    || die "Could not download the installer ($FILE). Check your internet connection and try again."
done
"$PYTHON" "$TMP/install.py" --target "$TARGET"
