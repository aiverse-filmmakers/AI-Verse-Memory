# Claude Code Integration

AI-Verse Memory uses two layers with Claude Code:

1. a project skill at `.claude/skills/ai-verse-memory/SKILL.md`;
2. a small standing instruction in `CLAUDE.md` so memory recall/capture is considered during normal work, not only when the user manually invokes a skill.

The installer handles both when possible.

## Standing instruction

Add this block once to the repository's `CLAUDE.md`:

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

Then ask Claude something that should use existing memory. Claude should call `recall` before relying on old context.

## Existing repositories

If `.ai-verse-memory/state/migration.json` is missing and the repo already contains useful context, Claude should perform `.ai-verse-memory/MIGRATION.md` once.

## Compaction

Before context compaction, preserve only durable session state that would otherwise be expensive to reconstruct. Do not save raw tool output or every turn.
