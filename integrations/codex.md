# Codex Integration

AI-Verse Memory installs the same execution contract into `.agents/skills/ai-verse-memory/SKILL.md`.

## AI-Verse OS v2 native mode

The neutral engine lives at:

```text
scripts/ai-verse-memory/memory.py
```

Codex should read the AI-Verse OS runtime contract, identify the active workspace, and use workspace-scoped recall:

```bash
python scripts/ai-verse-memory/memory.py recall "<topic>" --workspace <id>
```

The installer keeps the Claude and Codex `SKILL.md` files identical so AI-Verse OS architecture checks do not report adapter drift.

`AGENTS.md` remains the canonical standing contract. Memory does not add a second standing block to the Claude adapter.

## Standalone mode

Codex uses `.agents/skills/ai-verse-memory/SKILL.md` and the `.ai-verse-memory/` engine/store.
