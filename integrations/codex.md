# Codex Integration

AI-Verse Memory uses two layers with Codex:

1. a project skill at `.agents/skills/ai-verse-memory/SKILL.md`;
2. a small standing instruction in `AGENTS.md` so recall/capture is part of normal work.

The installer handles both when possible.

## Standing instruction

Add this block once to the repository's `AGENTS.md`:

```markdown
<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, project state, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->
```

## Verify

From the repository root:

```bash
python .ai-verse-memory/memory.py doctor
python .ai-verse-memory/memory.py status
```

## Existing repositories

If `.ai-verse-memory/state/migration.json` is missing and the repo already contains useful context, Codex should perform `.ai-verse-memory/MIGRATION.md` once.

## Session continuity

Capture durable decisions/state before compaction or session end when losing them would force costly reconstruction. Avoid transcript dumping.
