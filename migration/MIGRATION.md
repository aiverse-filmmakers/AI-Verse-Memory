# Historical Memory Migration

AI-Verse Memory v0.2 supports two migration paths.

## A. Existing Agent-OS context into memory

Use `discover` to find likely historical sources, then let the connected agent distill only durable history.

```bash
python <memory-engine> discover . --output <migration-report-path>
```

Do not import every file. Preserve provenance, avoid transient chatter, and do not duplicate information already represented canonically.

In AI-Verse OS v2, current profile/context/decision/knowledge files remain authoritative where they already live. Historical migration should not copy those files wholesale into atomic memory.

Useful atomic migration candidates include:

- important past events
- state transitions
- lessons from failures or successful work
- entity history that matters later
- old constraints that explain later decisions
- historical facts no longer represented in current context
- workflow experiences that may later become skills

## B. AI-Verse Memory v0.1 into AI-Verse OS v2

If `.ai-verse-memory/` already exists inside an AI-Verse OS v2 repository, use the dedicated migration command.

### 1. Dry run

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy
```

The engine maps:

- `global` -> `operator`
- `project:<id>` -> `workspace:<id>` only when that workspace exists
- `client:<id>` -> `workspace:<id>` only when that workspace exists
- `workspace:<id>` -> the matching workspace

Unknown scopes are reported as unresolved instead of being silently placed in the wrong workspace.

### 2. Review the report

Review `operator/memory/migrations/legacy-ai-verse-memory-migration.md`.

The dry run does not copy atomic memories.

### 3. Apply

```bash
python scripts/ai-verse-memory/memory.py migrate-legacy --apply
```

The migration:

- preserves memory IDs and chronology;
- preserves provenance;
- rewrites only the scope needed for the v2 architecture;
- skips existing IDs;
- leaves the old `.ai-verse-memory/` directory untouched;
- rebuilds the derived index after copying.

### 4. Review old profile/scenario material separately

The migration deliberately does not auto-promote `.ai-verse-memory/profile.md` or scenario summaries into AI-Verse OS profile/context. Those are summaries from the old architecture and may be stale or overlap newer canonical sources.

If still useful, distill them manually into the correct operator/workspace source with provenance.

## Validation

After migration run:

```bash
python <memory-engine> rebuild
python <memory-engine> doctor
python <memory-engine> status
```

Test representative recalls for operator context, a workspace, a superseded memory, and an old lesson.

Only then mark the migration complete:

```bash
python <memory-engine> migration-complete --summary "Reviewed and migrated durable historical memory."
```
