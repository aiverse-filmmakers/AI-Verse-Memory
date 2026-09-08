# Historical Memory Migration

Run this once after installing AI-Verse Memory into an Agent-OS repository that already contains useful context.

The goal is **not** to move every old file. The goal is to distill durable memory while leaving original sources untouched.

## Principles

- Existing files remain where they are.
- Migration is additive and reversible.
- The current connected agent performs the reasoning. No second model/API is required.
- Preserve source paths or session identifiers as provenance.
- Prefer atomic memories over giant summaries.
- Do not duplicate information already represented canonically.
- If old and new sources disagree, keep the timeline and mark older information superseded when the newer source is clearly authoritative.
- Do not ingest secrets automatically.

## Phase 1: Discover

From the Agent-OS repository root:

```bash
python .ai-verse-memory/memory.py discover . --output .ai-verse-memory/state/discovery.md
```

Inspect the highest-priority candidates first. Common useful sources include:

- `CLAUDE.md`
- `AGENTS.md`
- context/profile folders
- decision logs
- project notes
- client notes
- reference documents
- brainstorms
- archived state
- prior memory files
- exported or local agent transcripts
- README files that encode project assumptions

Do not assume every discovered file belongs in memory.

## Phase 2: Build a source inventory

Create `.ai-verse-memory/state/migration-report.md` and record:

```markdown
# Migration Report

## Sources reviewed
- path/to/source.md — reviewed

## Memories created
- mem-... — preference — source

## Conflicts/supersessions
- old -> new

## Scenario files created
- project-x.md

## Sources intentionally not migrated
- logs/raw-output.txt — transient tool output
```

This report makes migration auditable without copying all old material.

## Phase 3: Extract durable atomic memories

For each useful source, identify independent durable propositions.

Classify each as one of:

- `fact`
- `preference`
- `constraint`
- `decision`
- `project_state`
- `entity`
- `event`
- `experience`
- `workflow`

Use the narrowest meaningful scope:

- `global`
- `project:<slug>`
- `entity:<slug>`
- `client:<slug>`
- another stable domain prefix when useful

Before adding a candidate, recall similar memory:

```bash
python .ai-verse-memory/memory.py recall "<candidate fact>" --scope <scope>
```

If the same memory already exists, do not duplicate it.

Create new memories with provenance:

```bash
python .ai-verse-memory/memory.py remember \
  --type decision \
  --scope project:example \
  --source "path:decisions/log.md" \
  --importance 4 \
  --text "The project uses approach X." \
  --why "Chosen after approach Y failed quality control."
```

## Phase 4: Resolve chronology

When several historical sources describe the same thing at different times:

1. identify the earlier memory;
2. identify the later authoritative change;
3. store both when the change itself is useful history;
4. supersede the earlier memory so normal recall returns the current truth.

```bash
python .ai-verse-memory/memory.py supersede <old-id> \
  --text "The current state is now X." \
  --source "path:newer-source.md"
```

Do not flatten a changing fact into a timeless statement.

## Phase 5: Promote stable global context

After atomic memories exist, update `.ai-verse-memory/profile.md` with only stable information useful across many sessions.

Good profile material:

- role / enduring responsibilities
- stable working preferences
- durable constraints
- long-term priorities

Do not put volatile project status in the profile.

## Phase 6: Build scenarios

For projects, clients, or recurring domains with several relevant memories, create a scenario using the scenario template.

A scenario is a derived working view. It should contain:

- L0 abstract: one sentence;
- L1 overview: compact current context;
- current constraints;
- important active decisions;
- current state;
- key entities;
- unresolved items;
- memory IDs supporting the summary.

Do not delete the atomic memories after creating a scenario.

## Phase 7: Identify skill candidates

Review migrated `workflow` and `experience` memories.

If a workflow is repeatable and has clear triggers, required inputs, execution steps, decision rules, guardrails, outputs, and validation, flag it in the migration report as a candidate Agent-OS skill.

Do not automatically convert every remembered workflow into a skill.

## Phase 8: Validate

Run:

```bash
python .ai-verse-memory/memory.py rebuild
python .ai-verse-memory/memory.py doctor
python .ai-verse-memory/memory.py status
```

Test several representative recalls, especially:

- a global preference;
- a project decision;
- a changed/superseded fact;
- an entity detail;
- a lesson from older work.

## Phase 9: Mark complete

Only after review:

```bash
python .ai-verse-memory/memory.py migration-complete \
  --summary "Reviewed existing Agent-OS context and migrated durable memory."
```

This creates `.ai-verse-memory/state/migration.json`.

Migration can be run again later for newly discovered historical sources. The marker only means the initial bootstrap pass is complete.
