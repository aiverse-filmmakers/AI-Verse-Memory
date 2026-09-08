# AI-Verse Memory Protocol

This file is the standing operating protocol that Agent-OS repositories can reference from `CLAUDE.md`, `AGENTS.md`, or equivalent agent instructions.

## Core behavior

Use `.ai-verse-memory/` as the repository's persistent memory layer.

Before substantial work, recall relevant memory when prior context could materially change the answer or execution. Do not read the entire memory store. Use the local helper:

```bash
python .ai-verse-memory/memory.py recall "<task or topic>"
```

Add `--scope project:<slug>` when the active project is known.

After a conversation or task produces information that is likely to matter later, capture only the durable part. Good memory categories are:

- `fact`
- `preference`
- `constraint`
- `decision`
- `project_state`
- `entity`
- `event`
- `experience`
- `workflow`

Use:

```bash
python .ai-verse-memory/memory.py remember --type <type> --text "<atomic durable memory>"
```

Use `--scope`, `--source`, `--importance`, `--confidence`, `--why`, and `--tags` when they improve future recall.

## Memory quality rules

1. **Atomic:** one independently updateable proposition per memory.
2. **Durable:** save what will matter later, not normal conversation filler.
3. **Grounded:** preserve provenance. A stored memory should say where it came from when practical.
4. **Scoped:** use `global` only for broadly relevant information. Prefer `project:<slug>`, `entity:<slug>`, or another useful narrow scope.
5. **Lifecycle-aware:** if new information replaces old information, supersede the old memory instead of silently rewriting history.
6. **Confidence-aware:** distinguish confirmed information from uncertain inference.
7. **Private by default:** do not persist highly sensitive secrets automatically.
8. **Search before duplicate:** recall related memory before adding another record that may say the same thing.

## Supersession

When a durable fact changes, run:

```bash
python .ai-verse-memory/memory.py supersede <old-id> --type <type> --text "<new current memory>"
```

Normal recall excludes superseded memories unless explicitly requested.

## Progressive disclosure

Memory should load in layers:

1. **Profile / scenario abstract:** quick relevance check.
2. **Scenario overview:** enough context to plan.
3. **Atomic memories:** exact facts, decisions, preferences, and evidence only when needed.

Do not flood the model with full historical transcripts or every related file.

## Scenario summaries

When many atomic memories accumulate around one project, client, or recurring context, maintain a scenario file in `.ai-verse-memory/scenarios/`.

Scenario summaries are derived views, not replacements for atomic memories. They should link or list the memory IDs they summarize.

## Profile

`.ai-verse-memory/profile.md` contains only stable, broadly useful context. Do not constantly rewrite it from one-off events.

## Session continuity

Before compaction or at the end of substantial work, preserve state that would be expensive to reconstruct:

- meaningful decisions;
- unfinished project state;
- important constraints;
- newly learned preferences;
- useful failures or successful approaches;
- workflows that proved repeatable.

Do not save raw logs merely because context is about to be compacted.

## Migration trigger

If this repository already contains useful historical context and `.ai-verse-memory/state/migration.json` is missing, perform the one-time workflow in `.ai-verse-memory/MIGRATION.md` before treating the memory system as fully initialized.

## Skill promotion

When a workflow memory has become reliable and repeatable, convert it into a dedicated Agent-OS skill rather than allowing procedural knowledge to remain buried in memory.

## Canonical-storage rule

Markdown files under `.ai-verse-memory/` are canonical. `.ai-verse-memory/state/memory.db` is a disposable local index and may always be rebuilt with:

```bash
python .ai-verse-memory/memory.py rebuild
```
