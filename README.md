# AI-Verse Memory

**A lightweight, local-first persistent memory layer for AI agents. No external database, vector store, memory API, server, Docker stack, or separate embedding model required.**

AI-Verse Memory is designed to drop into an existing Agent-OS style repository and give Claude Code, Codex, Hermes, and other file-aware agents one shared memory structure.

The design deliberately keeps the system small:

- **Markdown is canonical.** Memory remains human-readable, portable, editable, and easy to inspect.
- **SQLite FTS5 is only an index.** It can be deleted and rebuilt from Markdown at any time.
- **No second AI provider.** The agent you already use does the reasoning needed to decide what is worth remembering.
- **Recall is scoped.** The agent retrieves a small set of relevant memories instead of loading the whole brain.
- **History is preserved.** Changed facts are superseded rather than silently overwritten.
- **Old knowledge can be migrated.** Existing Agent-OS context, notes, decisions, and transcripts can be distilled into the same structure.
- **Personal memory is local by default.** The installer Git-ignores `.ai-verse-memory/` to reduce accidental exposure in public repositories.

## Requirements

- Python 3.9+
- macOS, Linux, or Windows
- an existing Agent-OS/workspace using Claude Code, Codex, Hermes, or another file-aware agent

Normal memory use is offline. Network access is only needed to download/install the package initially.

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
- guesses presented as facts
- secrets unless the user explicitly wants them stored
- duplicate information already represented canonically
- obsolete facts that should instead supersede an earlier memory

## Repository contents

```text
AI-Verse-Memory/
├── README.md
├── SKILL.md
├── manifest.json
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
├── migration/
│   └── MIGRATION.md
└── tests/
    └── test_memory.py
```

## What installation creates in a user's Agent-OS

```text
.ai-verse-memory/
├── memory.py
├── MEMORY-PROTOCOL.md
├── MIGRATION.md
├── SCENARIO-TEMPLATE.md
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

The installer also installs the reusable skill into:

```text
.claude/skills/ai-verse-memory/SKILL.md
.agents/skills/ai-verse-memory/SKILL.md
```

If Hermes is detected, it also installs the skill into the user's Hermes skills directory.

## Quick install

Run the installer **from inside the Agent-OS repository you want to give memory to**.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.ps1 | iex
```

Installation:

1. creates the local memory runtime;
2. installs the skill for Claude and Codex;
3. installs the Hermes skill when Hermes is detected;
4. adds one idempotent standing-memory block to `CLAUDE.md` and `AGENTS.md`;
5. initializes the Markdown store and SQLite index;
6. runs a health check;
7. Git-ignores the personal runtime memory by default.

After that, agents know to recall relevant memory before substantial work and capture only durable information afterward.

## Core commands

```bash
python .ai-verse-memory/memory.py doctor
python .ai-verse-memory/memory.py status
python .ai-verse-memory/memory.py remember --type preference --text "Prefer concise project updates"
python .ai-verse-memory/memory.py recall "how should project updates be written"
python .ai-verse-memory/memory.py supersede <old-id> --text "Updated preference"
python .ai-verse-memory/memory.py rebuild
python .ai-verse-memory/memory.py discover .
```

Agents normally call these commands for the user. The user should not need to manage the index manually.

## First-run migration for existing Agent-OS data

If the repository already contains useful historical context, ask the connected agent:

> Run the AI-Verse Memory initial migration for this repository.

The agent follows `.ai-verse-memory/MIGRATION.md`.

The migration does **not** blindly copy every old file into memory. It:

1. discovers likely historical context sources;
2. identifies durable facts, preferences, decisions, project state, entities, experiences, and workflows;
3. preserves provenance;
4. deduplicates against memories already created;
5. marks conflicts and superseded facts correctly;
6. creates scenario summaries for mature projects;
7. flags strong workflow memories that may deserve promotion into real skills;
8. rebuilds the local index;
9. produces a migration report for review.

The existing connected agent performs the extraction. AI-Verse Memory does not require another model or API.

## Privacy and Git

The installer adds:

```gitignore
.ai-verse-memory/
```

by default. This is deliberate because persistent memory can contain personal or business context.

The reusable skill files and the standing instructions remain outside that directory and can still be committed into an Agent-OS template.

If a user deliberately wants to sync memory across devices, they can change that Git policy themselves, ideally only in a private repository.

## Design boundary

AI-Verse Memory is intentionally **not** a vector database, RAG platform, team memory server, transcript warehouse, or knowledge graph product. Those can become optional future adapters. The core stays useful on a normal laptop with Python and SQLite.

## Design influences

The architecture borrows ideas, not code, from several memory/context systems:

- Context Mode: lightweight session continuity and local lexical indexing
- OpenViking: progressive context disclosure and scoped retrieval
- TencentDB Agent Memory: atomic memories, scenario context, profile layers, and workflow promotion
- MemPalace: provenance, historical validity, and preserving changes over time
- Obsidian's plugin ecosystem: small installable/versioned package philosophy

AI-Verse Memory keeps those useful principles while intentionally leaving out their heavier infrastructure.

## License

MIT.
