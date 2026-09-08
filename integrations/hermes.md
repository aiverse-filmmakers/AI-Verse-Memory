# Hermes Integration

AI-Verse Memory can install its skill into the user-local Hermes skill directory when Hermes is detected.

Hermes should still operate the memory engine from the repository it is working in.

## AI-Verse OS v2 native mode

Use:

```bash
python scripts/ai-verse-memory/memory.py mode
python scripts/ai-verse-memory/memory.py recall "<topic>" --workspace <id>
```

Hermes must respect the same workspace isolation and canonical-source rules as Claude and Codex. A Hermes skill does not create a separate memory store.

## Standalone mode

Use:

```bash
python .ai-verse-memory/memory.py recall "<topic>" --scope <scope>
```

## Important

The Hermes user-local skill is only an adapter. Repository Markdown remains canonical and SQLite remains a derived index.
