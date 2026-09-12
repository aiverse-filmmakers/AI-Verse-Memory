# AI-Verse Memory

**A local-first persistent memory engine for AI agents and AI operating systems. Markdown stays canonical. SQLite is only a rebuildable index.**

AI-Verse Memory v0.2 adds native support for the AI-Verse OS v2 Unified Workspace Architecture while preserving standalone compatibility for other Agent-OS repositories.

## What changed in v0.2

The memory layer no longer assumes it should own the whole profile/project/context structure.

When installed into AI-Verse OS v2, the operating system remains the source of truth and Memory acts as an engine:

- AI-Verse OS defines where operator and workspace truth lives.
- AI-Verse Memory stores only atomic historical memory in those canonical memory layers.
- Current profile, context, decisions, and workspace manifests are indexed in place rather than copied.
- Workspace recall is isolated by default.
- SQLite lives under `runtime/` as derived state.
- The installer attaches Memory through the local `.aiverse/extensions/registry.json` contract without modifying tracked OS runtime files.

If no compatible AI-Verse OS v2 is detected, the original `.ai-verse-memory/` standalone model remains available.

## Design principles

- **One source of truth.** Memory never creates a second canonical profile/context system inside AI-Verse OS v2.
- **Markdown is canonical.** Human-readable files remain the durable truth.
- **SQLite is disposable.** Delete the index and rebuild it at any time.
- **Scoped recall.** Operator and workspace memory stay isolated unless cross-workspace retrieval is explicitly requested.
- **Current context beats history.** Historical memory cannot silently override current `CURRENT.md`, profile, or decisions.
- **History stays history.** Changed atomic memories are superseded instead of rewritten.
- **No extra AI infrastructure.** No vector database, embedding service, cloud memory API, Docker stack, or second LLM is required.
- **Domain neutral.** Memory understands operator/workspace boundaries, not professions such as filmmaking, medicine, coding, or marketing.
- **Private by default.** AI-Verse OS v2 already keeps user-owned state and runtime output local by default; standalone mode Git-ignores `.ai-verse-memory/`.

## Requirements

- Python 3.9+
- macOS, Linux, or Windows
- AI-Verse OS v2 or another file-aware Agent-OS repository

Normal memory use is offline after installation.

# Native AI-Verse OS v2 mode

The installer detects this contract:

```yaml
schema_version: "2.0"
architecture: unified-workspace
```

plus the `operator/` and `workspaces/` layers.

It then uses:

```text
AI-Verse-OS/
├── operator/
│   ├── profile/                 # canonical profile, indexed in place
│   ├── context/                 # canonical current context, indexed in place
│   ├── decisions/               # canonical decisions, indexed in place
│   └── memory/
│       └── atomic/              # atomic operator memories
│
├── workspaces/
│   └── <id>/
│       ├── WORKSPACE.yaml       # indexed in place
│       ├── context/             # indexed in place
│       ├── decisions/           # indexed in place
│       └── memory/
│           └── atomic/          # atomic workspace memories
│
├── runtime/
│   └── indexes/
│       └── ai-verse-memory/
│           └── memory.db        # derived, rebuildable
│
├── scripts/
│   └── ai-verse-memory/
│       ├── memory.py
│       ├── MEMORY-PROTOCOL.md
│       └── MIGRATION.md
│
├── .claude/skills/ai-verse-memory/SKILL.md
└── .agents/skills/ai-verse-memory/SKILL.md
```

It does **not** create `.ai-verse-memory/profile.md` or a second scenario/project hierarchy.

## Native writeback model

| Information | Canonical home |
|---|---|
| stable operator identity/preferences | `operator/profile/` |
| current operator state | `operator/context/` |
| historical operator memory | `operator/memory/` |
| operator decisions | `operator/decisions/` |
| current workspace state | `workspaces/<id>/context/` |
| historical workspace memory | `workspaces/<id>/memory/` |
| workspace decisions | `workspaces/<id>/decisions/` |
| reusable knowledge | root/workspace `knowledge/` |
| disposable search index | `runtime/indexes/ai-verse-memory/` |

Memory should store what happened and may matter later. It should not duplicate what is already current canonical truth.

# Standalone compatibility mode

If AI-Verse OS v2 is not detected, installation preserves the original portable structure:

```text
.ai-verse-memory/
├── memory.py
├── MEMORY-PROTOCOL.md
├── MIGRATION.md
├── SCENARIO-TEMPLATE.md
├── profile.md
├── memories/
├── scenarios/
├── evidence/
└── state/
    └── memory.db
```

This means existing Agent-OS, Claude Code, Codex, and Hermes workflows remain supported.

# Install

Run from the repository you want to give memory to.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.sh | bash
```

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main/install.ps1 | iex
```

The installer is idempotent and automatically selects native AI-Verse OS v2 or standalone mode.

## What native installation does

1. installs the neutral Memory engine under `scripts/ai-verse-memory/`;
2. installs matching Claude and Codex skill adapters;
3. attaches `ai-verse-memory` in `.aiverse/extensions/registry.json` using the shared lock/atomic-replace contract;
4. migrates only exact legacy Memory-owned blocks/stanzas out of tracked `AGENTS.md`, `CLAUDE.md`, or `skills/registry.yaml`; ambiguous user-modified legacy content is left untouched;
5. initializes the derived SQLite index;
6. runs `doctor`;
7. leaves canonical operator/workspace Memory and any old standalone `.ai-verse-memory/` store untouched unless the user deliberately migrates it.

Normal native install/update does **not** add a Memory block to `AGENTS.md`, `CLAUDE.md`, `AI-VERSE.yaml`, or `skills/registry.yaml`.

# Attachment lifecycle

Native attachment can be changed without deleting canonical Memory:

```bash
python scripts/install.py --target /path/to/AI-Verse-OS --action disable
python scripts/install.py --target /path/to/AI-Verse-OS --action enable
python scripts/install.py --target /path/to/AI-Verse-OS --action detach
```

`disable` keeps the registration but marks it unavailable. `detach` removes only Memory's local registry entry. Both preserve operator/workspace atomic Memory and the installed engine/adapters; re-running the normal installer can attach/repair it again.

Standalone state is never automatically detached, deleted, or converted into native state. Migration remains explicit.

# Core commands

Native examples:

```bash
python scripts/ai-verse-memory/memory.py mode
python scripts/ai-verse-memory/memory.py doctor
python scripts/ai-verse-memory/memory.py status
python scripts/ai-verse-memory/memory.py remember --type experience --scope operator --text "A useful historical lesson"
python scripts/ai-verse-memory/memory.py remember --type state --workspace example --text "The workspace moved to supervised testing"
python scripts/ai-verse-memory/memory.py recall "supervised testing" --workspace example
python scripts/ai-verse-memory/memory.py supersede <memory-id> --text "Updated historical state"
python scripts/ai-verse-memory/memory.py rebuild
```

Standalone uses the same commands through `.ai-verse-memory/memory.py`.

## Workspace isolation

Native recall with:

```bash
--workspace example
```

searches the selected workspace plus operator-level context. It does not search unrelated workspaces.

Cross-workspace search requires the explicit flag:

```bash
--all-workspaces
```

This is deliberate. Memory follows the same privacy and context-isolation boundary as AI-Verse OS.

# What is indexed in native mode

Without copying or replacing the original files, the engine indexes:

- `operator/profile/*.md`
- `operator/context/*.md`
- `operator/decisions/**/*.md`
- operator memory summaries and atomic memories
- each `WORKSPACE.yaml`
- workspace context
- workspace decisions
- workspace memory summaries and atomic memories

The full `knowledge/` tree is intentionally not swallowed into the memory index. Deeper knowledge retrieval remains an AI-Verse OS routing responsibility.

# Atomic memory model

Atomic memory keeps metadata for:

- `id`
- `type`
- `scope`
- `status`
- `importance`
- `confidence`
- `created_at`
- `updated_at`
- `valid_from`
- `valid_to`
- `supersedes`
- `superseded_by`
- `source`
- `tags`

Normal recall prefers active entries, exact workspace scope, lexical relevance, importance, confidence, canonical-source authority, and recency.

# Legacy v0.1 migration

If v0.1 was already installed inside AI-Verse OS v2, the v0.2 installer does not delete or silently move it.

Dry run:

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy
```

Apply after reviewing the report:

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy --apply
```

`global` becomes operator memory. `project:<id>`, `client:<id>`, and `workspace:<id>` move only when a matching v2 workspace exists. Unknown scopes remain unresolved rather than leaking into the wrong workspace.

# Health and QC

```bash
python scripts/ai-verse-memory/memory.py doctor
```

Native `doctor` checks storage, SQLite, FTS fallback, rebuildability, workspace isolation, Claude/Codex skill parity, the local extension attachment, absence of obsolete tracked Memory registrations, and a clean Claude adapter.

The repository CI tests Python 3.9 and 3.12 on Linux, macOS, and Windows, plus standalone and AI-Verse OS v2 installer smoke tests.

# Optional future retrieval tiers

The core remains lexical and local. Future semantic or larger-scale backends should be optional derived adapters only:

```text
Tier 0: SQLite FTS / lexical fallback, always available
Tier 1: optional local semantic index
Tier 2: optional larger external index for very large installations
```

None of those tiers may become the canonical memory store. Markdown remains truth.

# Security

AI-Verse Memory is not a secret manager. Do not automatically persist credentials, tokens, private keys, recovery codes, financial credentials, government identifiers, or other highly sensitive information. See `SECURITY.md`.

## License

MIT.
