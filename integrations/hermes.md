# Hermes Integration

Hermes supports `SKILL.md` skills and keeps user-installed skills under `~/.hermes/skills/`.

AI-Verse Memory does **not** replace Hermes itself or require Hermes to run a second memory provider. The skill simply teaches Hermes to use the same `.ai-verse-memory/` store as Claude Code and Codex when working inside the Agent-OS repository.

## Install the skill

Copy `SKILL.md` to:

```text
~/.hermes/skills/ai-verse/ai-verse-memory/SKILL.md
```

The shell installer does this automatically when it detects a Hermes installation.

Alternatively, Hermes can install a `SKILL.md` from a URL using its normal skills installer.

## Project standing guidance

Keep the AI-Verse Memory standing block in the project's `AGENTS.md`:

```markdown
<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, project state, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->
```

## Verify

From the Agent-OS repository root, ask Hermes to use the `ai-verse-memory` skill, or run:

```bash
python .ai-verse-memory/memory.py doctor
```

Hermes should read and write the exact same local memory files as the other agents.

## Existing data

If the repository already contains useful context, Hermes can perform `.ai-verse-memory/MIGRATION.md` using its currently connected model. No separate embedding model or memory API is required.
