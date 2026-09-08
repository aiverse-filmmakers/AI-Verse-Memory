---
name: ai-verse-memory
description: Install and operate a lightweight local-first persistent memory layer for an Agent-OS repository. Use it to remember durable facts, preferences, constraints, decisions, project state, entities, experiences, and proven workflows; recall relevant context before work; supersede outdated memories; rebuild the local index; and migrate useful historical context into the memory structure.
version: 0.1.0
author: AI-VERSE
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, context, agent-os, local-first, ai-verse]
    category: productivity
---

# AI-Verse Memory

## Purpose

Give an existing Agent-OS repository one shared, local, human-readable memory that can be used by Claude Code, Codex, Hermes, and other file-aware agents.

The core rule is simple:

> Markdown is the memory. SQLite is only a rebuildable search index.

Do not introduce a vector database, embedding service, cloud memory API, Docker stack, or separate LLM just to operate this skill.

## When to use

Use this skill when:

- a new durable fact, preference, constraint, decision, project state, entity detail, event, or lesson appears;
- the user asks you to remember something;
- old information is corrected or becomes obsolete;
- a task would benefit from prior project/user context;
- the current session is about to be compacted or ended and meaningful state should survive;
- the repository already contains old notes, context files, decisions, or transcripts that should be migrated;
- a repeated successful procedure is mature enough to be proposed as a reusable skill.

Do not store every conversation turn. Memory must earn its place.

## Memory layers

### Evidence

Optional provenance showing where a memory came from. Prefer a path, session identifier, URL, commit, or short excerpt. Do not duplicate huge source files into the memory store.

### Atomic memory

One durable proposition. Keep it specific enough to retrieve and update independently.

Types:

- `fact`
- `preference`
- `constraint`
- `decision`
- `project_state`
- `entity`
- `event`
- `experience`
- `workflow`

### Scenario

A compact working view of a project, client, topic, or recurring situation. Scenario files summarize multiple atomic memories and point to important source memories. They are not substitutes for atomic memories.

### Profile

Stable high-level context useful across many sessions. Only promote information here after it has proven durable.

## Capture rules

Before writing memory, ask internally:

1. Will this plausibly matter in a future session?
2. Is it a fact, preference, constraint, decision, state change, entity detail, event, lesson, or proven workflow?
3. Is it already represented canonically?
4. Is this new information, or does it update an older memory?
5. Is the source trustworthy enough to store as fact, or should confidence be lower?
6. Is this sensitive information that should not be persisted without clear user intent?

If it is not durable, do not save it.

## Write procedure

The helper is normally installed at `.ai-verse-memory/memory.py`.

Create an atomic memory:

```bash
python .ai-verse-memory/memory.py remember \
  --type decision \
  --scope project:example \
  --importance 4 \
  --source "session:current" \
  --text "Use the new render pipeline for Example Project." \
  --why "The previous pipeline caused repeated continuity failures."
```

Prefer concise atomic memories. If a statement contains several independently changeable claims, split it.

## Recall procedure

Before substantial work where prior context may matter, search memory first:

```bash
python .ai-verse-memory/memory.py recall "Example Project render pipeline" --scope project:example
```

Use the returned memory IDs and paths as evidence. Read the full Markdown file only when more detail is required.

Retrieval should prefer:

1. active over superseded memory;
2. exact scope over global scope;
3. stronger lexical relevance;
4. higher importance;
5. more recent updates when relevance is otherwise similar.

Do not load the entire memory directory into context.

## Updating old information

Do not silently edit history to make an old memory look as if it was always true.

Use supersession:

```bash
python .ai-verse-memory/memory.py supersede <old-memory-id> \
  --type preference \
  --text "The user now prefers the revised workflow." \
  --source "session:current"
```

The old memory remains inspectable but becomes inactive for normal recall.

## Scenario maintenance

Create or refresh a scenario when a project/topic has enough atomic memories that repeatedly reconstructing the working context becomes wasteful.

Use `templates/scenario.md` as the format. A scenario should contain:

- one-sentence abstract;
- compact current overview;
- active constraints;
- important decisions;
- current state;
- key entities;
- unresolved items;
- relevant memory IDs.

This provides progressive disclosure: abstract first, overview second, atomic details only if needed.

## Profile maintenance

`profile.md` is not a dumping ground. Promote only stable, broadly useful information. Preferences or project facts that change often should stay atomic or scenario-scoped.

## Session continuity

Before compaction or at the end of a substantial session, capture only state that would be costly to reconstruct, such as:

- what was decided;
- what remains unfinished;
- a newly discovered constraint;
- a successful or failed approach worth remembering;
- a project state transition.

Do not preserve raw tool noise merely because the session is ending.

## Workflow promotion

When an `experience` or `workflow` memory represents a procedure that has succeeded repeatedly and has clear trigger conditions, inputs, execution steps, guardrails, and verification, propose promoting it into a real Agent-OS skill.

Memory records that a procedure exists. A skill should define how to execute it reliably.

## Migration of existing repositories

If `.ai-verse-memory/state/migration.json` does not exist and the repository already contains substantial context, read `migration/MIGRATION.md` and perform the migration workflow.

Start with:

```bash
python .ai-verse-memory/memory.py discover . --output .ai-verse-memory/state/discovery.md
```

Use the current connected agent to inspect likely sources and distill durable memories. Do not require another model/API.

Migration must:

- preserve provenance;
- deduplicate;
- identify conflicts;
- supersede obsolete information;
- avoid importing transient chatter;
- create scenario summaries where useful;
- finish with `rebuild` and `doctor`;
- write `.ai-verse-memory/state/migration.json` only after a successful pass.

## Safety and privacy

Do not automatically persist passwords, API keys, authentication tokens, private keys, financial credentials, government identifiers, medical information, or other highly sensitive data unless the user explicitly requests that exact information be stored locally and understands the consequence.

Prefer references to secure locations instead of secret values.

## Health checks

Run:

```bash
python .ai-verse-memory/memory.py doctor
```

A healthy installation has:

- writable canonical Markdown store;
- usable SQLite;
- FTS5 when available, with automatic lexical fallback otherwise;
- an index that can be rebuilt from Markdown;
- no requirement for network access during normal recall/write operations.
