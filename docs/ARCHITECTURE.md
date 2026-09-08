# Architecture

AI-Verse Memory is deliberately a **small memory layer**, not a memory platform.

## Goals

1. Work inside an existing Agent-OS repository.
2. Share one memory across Claude Code, Codex, Hermes, and other file-aware agents.
3. Require no memory-specific API key, server, vector database, embedding model, Docker stack, or cloud account.
4. Keep memory inspectable and portable.
5. Preserve chronology instead of silently rewriting old truth.
6. Load only the context needed for the current task.
7. Let existing historical Agent-OS data be migrated by the already connected agent.

## Components

```text
Agent
  │
  ├── standing protocol
  │      decides when to recall/capture
  │
  ├── SKILL.md
  │      detailed memory procedures
  │
  └── memory.py
         │
         ├── canonical Markdown
         │    ├── profile
         │    ├── atomic memories
         │    └── scenarios
         │
         └── SQLite index
              └── FTS5 when available
```

## Canonical memory

Markdown is authoritative. The SQLite file can always be removed and rebuilt.

This avoids locking a user's memory inside a database format and gives both humans and agents a readable audit trail.

## Atomic memory schema

Each memory represents one independently updateable proposition and carries:

- unique ID
- type
- scope
- lifecycle status
- importance
- confidence
- creation/update timestamps
- optional validity range
- supersession links
- provenance/source
- tags
- memory text
- optional reason/importance explanation

## Progressive disclosure

The system uses three practical read depths:

### L0: relevance

A scenario's one-sentence abstract or compact profile context is enough to decide whether deeper memory is relevant.

### L1: working context

Scenario overview restores the current project/client/topic state without loading all history.

### L2: evidence and exact memory

Atomic memories provide specific facts, decisions, preferences, chronology, and provenance.

The agent should stop as soon as it has enough context.

## Lifecycle

```text
new durable information
        │
        ▼
search for existing memory
        │
   ┌────┴────┐
   │         │
 new       update
   │         │
write     supersede old
   │         │
   └────┬────┘
        ▼
rebuild/update local index
        │
        ▼
future scoped recall
```

Superseded memories remain available for historical recall but are excluded from normal current-context retrieval.

## Retrieval

Version 0.1 uses local lexical retrieval and ranking rather than embeddings.

Candidate ranking considers:

- lexical overlap
- exact phrase match
- scope match
- active lifecycle status
- importance
- confidence
- recency
- scenario/profile role

SQLite FTS5 accelerates candidate retrieval when available. A non-FTS lexical fallback keeps the system usable on SQLite builds without FTS5.

## Migration

Historical migration is agent-assisted rather than a blind parser.

The helper discovers likely sources. The already connected Claude/Codex/Hermes model then determines which information is actually durable, classifies it, preserves provenance, resolves chronology, and writes atomic memories.

This avoids requiring a second LLM while producing better structure than indiscriminate ingestion.

## Privacy model

Runtime memory is local plaintext and is Git-ignored by default.

AI-Verse Memory does not claim to provide encryption, secret storage, access control, or multi-user isolation. Users should keep credentials and highly sensitive secrets in appropriate secure systems and store references rather than secret values in memory.

## What is intentionally absent

The v0.1 core does not contain:

- vector search
- embeddings
- a knowledge graph
- a web dashboard
- a daemon/background server
- automatic cloud sync
- multi-user ACLs
- transcript warehousing
- a separate summarization model

Those may be implemented later as optional adapters only if they do not compromise the small local core.
