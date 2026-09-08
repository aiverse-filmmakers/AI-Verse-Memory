#!/usr/bin/env bash
set -euo pipefail

BASE_URL="https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main"
TARGET="${AI_VERSE_MEMORY_TARGET:-$PWD}"
RUNTIME="$TARGET/.ai-verse-memory"
MARKER="AI-VERSE-MEMORY:START"

say() { printf '%s\n' "$*"; }
fail() { printf 'AI-Verse Memory install error: %s\n' "$*" >&2; exit 1; }

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsSL "$1" -o "$2"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q "$1" -O "$2"; }
else
  fail "curl or wget is required for installation"
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
else
  fail "Python 3 is required. Install Python, then rerun this installer."
fi

mkdir -p "$RUNTIME" "$RUNTIME/scenarios" "$RUNTIME/evidence" "$RUNTIME/state"
mkdir -p "$TARGET/.claude/skills/ai-verse-memory" "$TARGET/.agents/skills/ai-verse-memory"

fetch "$BASE_URL/scripts/memory.py" "$RUNTIME/memory.py"
fetch "$BASE_URL/protocol/MEMORY-PROTOCOL.md" "$RUNTIME/MEMORY-PROTOCOL.md"
fetch "$BASE_URL/migration/MIGRATION.md" "$RUNTIME/MIGRATION.md"
fetch "$BASE_URL/templates/scenario.md" "$RUNTIME/SCENARIO-TEMPLATE.md"
fetch "$BASE_URL/SKILL.md" "$TARGET/.claude/skills/ai-verse-memory/SKILL.md"
fetch "$BASE_URL/SKILL.md" "$TARGET/.agents/skills/ai-verse-memory/SKILL.md"
chmod +x "$RUNTIME/memory.py" 2>/dev/null || true

if [ ! -f "$RUNTIME/profile.md" ]; then
  fetch "$BASE_URL/templates/profile.md" "$RUNTIME/profile.md"
fi

append_protocol() {
  local file="$1"
  touch "$file"
  if grep -q "$MARKER" "$file" 2>/dev/null; then
    return
  fi
  cat >> "$file" <<'EOF'

<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, project state, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->
EOF
}

append_protocol "$TARGET/CLAUDE.md"
append_protocol "$TARGET/AGENTS.md"

# Personal runtime memory is private/local by default. The reusable skill and
# standing instructions remain outside this ignored directory and may be committed.
touch "$TARGET/.gitignore"
if ! grep -Fxq ".ai-verse-memory/" "$TARGET/.gitignore" 2>/dev/null; then
  printf '\n# AI-Verse Memory local runtime and personal memory\n.ai-verse-memory/\n' >> "$TARGET/.gitignore"
fi

# Hermes skills are user-local. Install the skill automatically only when a
# Hermes installation/profile is detectable.
if command -v hermes >/dev/null 2>&1 || [ -d "${HOME:-}/.hermes" ]; then
  HERMES_SKILL="${HOME}/.hermes/skills/ai-verse/ai-verse-memory"
  mkdir -p "$HERMES_SKILL"
  fetch "$BASE_URL/SKILL.md" "$HERMES_SKILL/SKILL.md"
  say "Installed Hermes skill: $HERMES_SKILL/SKILL.md"
fi

(
  cd "$TARGET"
  "$PYTHON" .ai-verse-memory/memory.py init >/dev/null
  "$PYTHON" .ai-verse-memory/memory.py doctor
)

say ""
say "AI-Verse Memory installed in: $TARGET"
say "Claude skill: .claude/skills/ai-verse-memory/SKILL.md"
say "Codex skill:  .agents/skills/ai-verse-memory/SKILL.md"
say "Memory store: .ai-verse-memory/ (Git-ignored by default)"
say ""
say "If this Agent-OS already contains useful historical context, ask your agent:"
say '  "Run the AI-Verse Memory initial migration for this repository."'
say ""
say "Otherwise memory is ready for new work immediately."
