# Claude Code Integration

AI-Verse Memory supports two Claude integration modes.

## AI-Verse OS v2 native mode

AI-Verse OS v2 treats `AGENTS.md` as the canonical runtime contract and `CLAUDE.md` as a Claude adapter. The installer therefore:

1. installs `.claude/skills/ai-verse-memory/SKILL.md`;
2. installs the neutral engine at `scripts/ai-verse-memory/memory.py`;
3. adds one bounded Memory integration block to `AGENTS.md`;
4. does not duplicate standing Memory guidance in `CLAUDE.md`;
5. registers the capability in `skills/registry.yaml` when the expected registry is present.

Claude should follow normal AI-Verse routing, identify the workspace, then use scoped recall only when prior history can materially change the work.

```bash
python scripts/ai-verse-memory/memory.py recall "<topic>" --workspace <id>
```

Current OS context remains more authoritative than historical memory.

## Standalone mode

For a generic Agent-OS repository, the installer keeps the original model:

- `.claude/skills/ai-verse-memory/SKILL.md`
- `.ai-verse-memory/`
- one standing Memory block in `CLAUDE.md` and `AGENTS.md`

## Verify

Native:

```bash
python scripts/ai-verse-memory/memory.py doctor
```

Standalone:

```bash
python .ai-verse-memory/memory.py doctor
```
