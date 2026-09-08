# AI-Verse Memory Protocol

AI-Verse Memory is a memory engine, not a competing source of truth.

## Operating principle

1. Identify the repository mode.
2. Identify the active scope.
3. Recall only the minimum relevant context.
4. Treat current canonical OS context as newer authority than historical memory.
5. Persist only durable history that has a clear future value.
6. Keep the SQLite index disposable and rebuildable from Markdown.

## AI-Verse OS v2 native mode

When `AI-VERSE.yaml` declares schema v2 and `architecture: unified-workspace`:

- use `operator/` and `workspaces/` as the canonical storage architecture;
- store atomic operator memories in `operator/memory/atomic/`;
- store atomic workspace memories in `workspaces/<id>/memory/atomic/`;
- keep the search database under `runtime/indexes/ai-verse-memory/`;
- never create a second `.ai-verse-memory/profile.md` or scenario layer;
- never treat memory as more authoritative than `CURRENT.md`, profile, decisions, or curated knowledge;
- never silently search one workspace while working in another.

The engine indexes selected canonical profile/context/decision files in place to improve recall without copying them into memory.

## Standalone mode

When no compatible AI-Verse OS v2 manifest exists, use `.ai-verse-memory/` as the portable canonical memory home and retain the profile/scenario model for backwards compatibility.

## Recall

Native operator-only:

```bash
python scripts/ai-verse-memory/memory.py recall "<query>" --scope operator
```

Native workspace:

```bash
python scripts/ai-verse-memory/memory.py recall "<query>" --workspace <id>
```

Standalone:

```bash
python .ai-verse-memory/memory.py recall "<query>" --scope <scope>
```

Cross-workspace recall requires `--all-workspaces` and should only be used when the task genuinely spans multiple workspaces.

## Capture

Before saving atomic memory ask:

- Will this matter later?
- Is it history rather than current context?
- Does a canonical profile/context/decision/knowledge file already own this truth?
- Is the scope correct?
- Is it an update to an older atomic memory?
- Is it safe to persist?

Good atomic types are `fact`, `preference`, `constraint`, `state`, `entity`, `event`, `experience`, and `workflow`. `decision` and the legacy `project_state` type remain supported for compatibility, but native AI-Verse OS should prefer its canonical decisions and use `state` for workspace history.

## Supersession

Changed atomic memory should preserve chronology. Create the new memory and mark the prior one superseded. Normal recall excludes superseded entries unless history is explicitly requested.

Do not use atomic supersession to rewrite current OS context.

## Progressive disclosure

Native mode uses the OS itself as the disclosure hierarchy:

1. workspace manifest / operator profile for scope and identity;
2. current context;
3. relevant decisions and memory summaries;
4. exact atomic memories only when needed.

Standalone mode retains profile -> scenario -> atomic memory.

## Skill promotion

A repeatedly successful workflow memory with a clear trigger, inputs, steps, guardrails, outputs, and verification should be promoted into a real skill. Memory records history; skills define execution.

## Privacy

Do not automatically persist secrets or highly sensitive data. Workspace privacy boundaries apply to memory recall as strictly as they apply to normal OS routing.
