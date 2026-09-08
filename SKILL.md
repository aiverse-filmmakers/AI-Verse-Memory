---
name: ai-verse-memory
description: Operate AI-Verse Memory as a scoped persistent memory engine. In AI-Verse OS v2 it indexes canonical operator/workspace context in place and stores only atomic historical memory in the OS memory layers; in other Agent-OS repositories it falls back to the standalone .ai-verse-memory layout.
version: 0.2.0
author: AI-VERSE
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, context, agent-os, local-first, ai-verse]
    category: productivity
---

# AI-Verse Memory Engine

## Core rule

> The operating system decides where truth lives. AI-Verse Memory provides capture, scoped recall, provenance, supersession, and a rebuildable local index.

Markdown remains canonical. SQLite is derived and disposable.

## Detect the mode first

From the repository root run the installed helper:

```bash
python scripts/ai-verse-memory/memory.py mode
```

for AI-Verse OS v2, or:

```bash
python .ai-verse-memory/memory.py mode
```

for standalone mode.

### AI-Verse OS v2 native mode

If `AI-VERSE.yaml` declares schema v2 and `architecture: unified-workspace`, do not create a second profile, project model, decision store, or context tree.

Use the OS as authority:

- operator identity/preferences -> `operator/profile/`
- operator current state -> `operator/context/`
- operator historical memory -> `operator/memory/`
- operator decisions -> `operator/decisions/`
- workspace current state -> `workspaces/<id>/context/`
- workspace historical memory -> `workspaces/<id>/memory/`
- workspace decisions -> `workspaces/<id>/decisions/`
- reusable knowledge -> root or workspace `knowledge/`
- derived index -> `runtime/indexes/ai-verse-memory/`

Atomic memories are stored under `operator/memory/atomic/` or `workspaces/<id>/memory/atomic/`.

### Standalone mode

If no compatible AI-Verse OS v2 manifest exists, preserve the original portable layout under `.ai-verse-memory/`.

## Before substantial work

1. Identify the active scope before recalling memory.
2. In AI-Verse OS v2, identify the active workspace from `WORKSPACE.yaml` and routing context.
3. Recall only the relevant scope.
4. Use current canonical context over historical memory when they disagree.
5. Read full source files only when the recall result shows they are needed.

Native workspace recall:

```bash
python scripts/ai-verse-memory/memory.py recall "<task or topic>" --workspace <id>
```

This may return operator context plus the selected workspace, but it must not silently search unrelated workspaces.

Operator-only recall:

```bash
python scripts/ai-verse-memory/memory.py recall "<task or topic>" --scope operator
```

Cross-workspace recall is exceptional and must be explicit:

```bash
python scripts/ai-verse-memory/memory.py recall "<task or topic>" --all-workspaces
```

## Decide whether something belongs in memory

In AI-Verse OS v2, do not use atomic memory as a duplicate catch-all.

Route information first:

| Information | Canonical home |
|---|---|
| stable identity or enduring preference | operator profile |
| what matters now | operator/workspace context |
| settled choice and reasoning | operator/workspace decisions |
| durable reusable method or domain knowledge | knowledge |
| historical event, state transition, lesson, experience, or fact worth recalling later | atomic memory |
| proven repeatable execution method | candidate skill |
| transient input | inbox or no persistence |

Atomic memory should mainly preserve history that would otherwise be expensive to reconstruct.

## Write an atomic memory

Operator memory:

```bash
python scripts/ai-verse-memory/memory.py remember \
  --type experience \
  --scope operator \
  --text "The first rollout failed because approval routing was missing." \
  --source "session:current"
```

Workspace memory:

```bash
python scripts/ai-verse-memory/memory.py remember \
  --type state \
  --workspace example \
  --text "The integration passed supervised testing and is ready for the next review gate." \
  --source "session:current"
```

Use concise, independently updateable memories. Preserve provenance when practical.

## Supersession

Never rewrite historical memory to pretend the old state never existed.

```bash
python scripts/ai-verse-memory/memory.py supersede <memory-id> \
  --text "The newer state is now active." \
  --source "session:current"
```

Normal recall excludes superseded atomic memories unless `--include-history` is requested.

Do not use memory supersession to edit current OS context or decisions. Update their canonical OS files instead.

## Index behavior

In native mode the engine indexes, without copying:

- operator profile
- operator current context
- operator decision files
- operator memory summaries and atomic memory
- workspace manifests
- workspace current context
- workspace decisions
- workspace memory summaries and atomic memory

It intentionally does not turn the full knowledge base into a hidden duplicate RAG store. AI-Verse OS routing remains responsible for deeper knowledge retrieval.

## Memory quality rules

- Durable: likely to matter later.
- Atomic: one independently changeable proposition.
- Grounded: preserve source/provenance when possible.
- Scoped: operator or the correct workspace.
- Historical: do not compete with current context.
- Lifecycle-aware: supersede outdated atomic memories.
- Private by default: never store secrets automatically.
- Minimal: search before creating duplicates.

## Legacy v0.1 migration

If native AI-Verse OS v2 contains an old `.ai-verse-memory/` store, leave it untouched until reviewed.

Dry run:

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy
```

Apply only after review:

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy --apply
```

The migration copies only safely mappable atomic memories. It never deletes the old store and does not blindly promote old profile/scenario summaries into current OS truth.

## Health checks

```bash
python scripts/ai-verse-memory/memory.py doctor
python scripts/ai-verse-memory/memory.py status
```

A healthy native install should verify:

- AI-Verse OS v2 detection
- writable canonical memory paths
- derived index path
- SQLite and rebuild
- workspace isolation
- Claude/Codex skill parity
- capability registry entry
- canonical AGENTS integration
- no duplicated standing block in `CLAUDE.md`

## Safety

Do not automatically persist passwords, API keys, tokens, private keys, recovery codes, financial credentials, government identifiers, highly sensitive medical details, or other secrets. Prefer a pointer to a secure system instead of the secret value.
