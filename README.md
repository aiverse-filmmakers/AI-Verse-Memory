# AI-Verse Memory

**A lightweight, local-first persistent memory layer for AI agents. No external database, vector store, memory API, server, Docker stack, or separate embedding model required.**

AI-Verse Memory is designed to drop into an existing Agent-OS style repository and give Claude Code, Codex, Hermes, and other file-aware agents one shared memory structure.

The design deliberately keeps the system small:

- **Markdown is canonical.** Memory remains human-readable, portable, editable, and Git-friendly.
- **SQLite FTS5 is only an index.** It can be deleted and rebuilt from Markdown at any time.
- **No second AI provider.** The agent you already use does the reasoning needed to decide what is worth remembering.
- **Recall is scoped.** The agent retrieves a small set of relevant memories instead of loading the whole brain.
- **History is preserved.** Changed facts are superseded rather than silently overwritten.
- **Old knowledge can be migrated.** Existing Agent-OS context, notes, decisions, and transcripts can be distilled into the same structure.

## Memory model

AI-Verse Memory combines a few proven ideas without importing their infrastructure:

| Layer | Purpose |
|---|---|
| **Evidence** | Optional source reference or excerpt showing where a memory came from. |
| **Atomic memory** | One durable fact, preference, constraint, decision, entity detail, event, or lesson. |
| **Scenario** | A compact working view of a project, client, topic, or recurring situation. |
| **Profile** | Stable high-level context that should be available quickly across sessions. |

Every atomic memory also has metadata for type, scope, importance, confidence, timestamps, provenance, and lifecycle state.

## What gets remembered

Good candidates:

- stable facts
- preferences
- constraints
- meaningful decisions and their reasoning
- project state that matters later
- people/entities and relationships
- important events
- lessons learned from completed work
- proven repeatable workflows that may later become skills

Bad candidates:

- transient chatter
- one-off tool output
- guesses
- secrets unless the user explicitly wants them stored
- duplicate information already represented canonically
- obsolete facts that should instead supersede an earlier memory

## Repository contents

```text
AI-Verse-Memory/
├── README.md
├── SKILL.md
├── LICENSE
├── install.sh
├── install.ps1
├── protocol/
│   └── MEMORY-PROTOCOL.md
├── scripts/
│   └── memory.py
├── templates/
│   ├── profile.md
│   └── scenario.md
├── integrations/
│   ├── claude-code.md
│   ├── codex.md
│   └── hermes.md
└── migration/
    └── MIGRATION.md
```

## What installation creates in a user's Agent-OS

```text
.ai-verse-memory/
├── profile.md
├── memories/
│   └── YYYY/
│       └── MM/
│           └── <memory-id>.md
├── scenarios/
├── evidence/
└── state/
    └── memory.db
```

The `state/memory.db` file is derived data. The Markdown files are the real memory.

## Quick install

### macOS / Linux

From inside the Agent-OS repository:

```bash
curl -fsSL https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.ps1 | iex
```

The installer is intentionally conservative. It creates the memory folder, copies the memory skill and protocol, installs the dependency-free Python helper, and prints the small integration block that should be added to the agent's standing instructions.

## Core commands

```bash
python .ai-verse-memory/memory.py doctor
python .ai-verse-memory/memory.py remember --type preference --text "Prefer concise project updates"
python .ai-verse-memory/memory.py recall "how should project updates be written"
python .ai-verse-memory/memory.py supersede <old-id> --text "Updated preference"
python .ai-verse-memory/memory.py rebuild
python .ai-verse-memory/memory.py discover .
```

Agents normally call these commands for the user. The user should not need to manage the index manually.

## First-run migration

After installation, the agent should run the migration workflow in `migration/MIGRATION.md` once if the repository already contains useful context.

The migration does **not** blindly copy every old file into memory. It:

1. discovers likely historical context sources;
2. identifies durable facts, preferences, decisions, project state, entities, experiences, and workflows;
3. preserves provenance;
4. deduplicates against memories already created;
5. marks conflicts and superseded facts correctly;
6. creates scenario summaries for mature projects;
7. rebuilds the local index;
8. produces a migration report for review.

The existing connected agent performs the extraction. AI-Verse Memory does not require another model or API.

## Design boundary

AI-Verse Memory is intentionally **not** a vector database, RAG platform, team memory server, transcript warehouse, or knowledge graph product. Those can be optional future adapters. The core stays useful on a normal laptop with Python and SQLite.

## License

MIT.