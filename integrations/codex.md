# Codex Integration

## Native AI-Verse OS mode

Public setup installs the Memory adapter at:

```text
.agents/skills/ai-verse-memory/SKILL.md
```

The neutral engine and lifecycle live under:

```text
scripts/ai-verse-memory/
```

Attachment is local through `.aiverse/extensions/registry.json`. Memory does not modify tracked `AGENTS.md`, `CLAUDE.md`, or `skills/registry.yaml` in native mode.

Codex identifies the active workspace and uses scoped recall:

```bash
python scripts/ai-verse-memory/memory.py recall "<topic>" --workspace <id>
```

The Claude and Codex Memory Skill adapters remain identical.

## Standalone mode

Codex uses `.agents/skills/ai-verse-memory/SKILL.md` together with the `.ai-verse-memory/` portable store.

## Lifecycle verification

```bash
python scripts/component.py --target <root> --json status
python scripts/component.py --target <root> --json doctor
```
