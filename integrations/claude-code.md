# Claude Code Integration

## Native AI-Verse OS mode

Public setup installs:

```text
.claude/skills/ai-verse-memory/SKILL.md
scripts/ai-verse-memory/
```

and attaches Memory through:

```text
.aiverse/extensions/registry.json
```

Memory does not add a standing native block to tracked `AGENTS.md` or `CLAUDE.md`, and it does not register itself in tracked `skills/registry.yaml`.

Claude follows normal host routing, identifies the active workspace, then uses scoped Memory recall only when history can materially change the work.

```bash
python scripts/ai-verse-memory/memory.py recall "<topic>" --workspace <id>
```

Current canonical host context remains more authoritative than historical Memory.

## Standalone mode

Standalone setup keeps the portable integration:

- `.claude/skills/ai-verse-memory/SKILL.md`
- `.ai-verse-memory/`
- one bounded Memory block in `AGENTS.md` and `CLAUDE.md`

## Lifecycle verification

```bash
python scripts/component.py --target <root> --json status
python scripts/component.py --target <root> --json doctor
```
