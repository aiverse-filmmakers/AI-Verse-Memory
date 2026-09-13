# AI-Verse Memory Protocol

AI-Verse Memory is the canonical owner of historical memory, not a competing owner of current truth, Skills, or Brain strategy.

## Operating law

1. Detect repository mode and active scope.
2. Recall the minimum relevant context.
3. Treat current canonical owner state as newer authority than historical Memory.
4. Persist only durable history with future value.
5. Preserve provenance and chronology.
6. Keep SQLite derived and rebuildable from canonical sources.
7. Never create two writable canonical Memory routes during adoption.

## Native AI-Verse OS mode

When the host declares AI-Verse OS v2 unified-workspace architecture:

- operator atomic history lives under `operator/memory/atomic/`;
- workspace atomic history lives under `workspaces/<id>/memory/atomic/`;
- derived recall state lives under `runtime/indexes/ai-verse-memory/`;
- profile, current context, decisions, workspace topology, and knowledge keep their existing owners;
- workspace recall never crosses into another workspace unless explicitly requested.

Selected current canonical sources are indexed in place. They are not copied into a second Memory truth store.

Native source and destination boundaries are checked both lexically and physically. Symlinked paths that escape the repository or cross ownership/scope are rejected.

## Standalone mode

When no compatible AI-Verse OS exists, `.ai-verse-memory/` is the portable canonical Memory home.

A standalone store marked `AUTHORITY.json: status=retired` is historical evidence only. Supported canonical writes must refuse there after native authority handoff.

## Recall

Operator:

```bash
python <memory-engine> recall "<query>" --scope operator
```

Workspace:

```bash
python <memory-engine> recall "<query>" --workspace <id>
```

Cross-workspace recall requires explicit `--all-workspaces`.

## Capture

Before saving historical Memory ask:

- Will this matter later?
- Is it history rather than current state?
- Does another canonical owner already own this current truth?
- Is the scope correct?
- Is this a correction/supersession?
- What provenance or evidence should remain attached?

Public-beta historical types include:

- `fact`
- `preference`
- `constraint`
- `state`
- `entity`
- `event`
- `experience`
- `workflow`
- `lesson`
- `correction`

Legacy `decision` and `project_state` remain accepted for compatibility.

Use `source` and repeatable `--evidence-ref` to retain historical provenance. Use `--effect-id` for retry-safe owner-routed capture when an effect may be replayed.

## Supersession

Changed historical Memory preserves chronology. The replacement points to the old memory, the old memory becomes superseded, and a recovery journal protects the multi-file effect from interruption.

Normal recall excludes superseded history unless explicitly requested.

## Canonical mutation

Memory canonical mutation is component-owned and serialized.

- canonical file writes use atomic replacement;
- concurrent mutations wait on the Memory mutation lock;
- stale abandoned locks can recover;
- retryable remember effects may have durable idempotency receipts;
- rebuild is coordinated with canonical mutation;
- migration has its own reviewed snapshot and handoff receipt.

This mechanism is not a generic OS filesystem mutation service.

## Self-learning evidence boundary

Memory owns historical evidence for the canonical self-learning loop:

- experiences;
- corrections;
- lessons;
- success/failure history;
- provenance/evidence references;
- recall of prior outcomes.

Memory does **not** own:

- executable Skill proposal packages;
- candidate Skill source bytes;
- Skill activation/version lifecycle;
- strategic evaluation or promotion decisions.

Skills owns Skill lifecycle. Brain owns strategic/evaluation policy. Memory only supplies historical evidence those owners may inspect.

A repeated successful workflow may be evidence for Skill improvement, but Memory does not convert it into a Skill by itself.

## Migration and authority

Migration follows:

```text
discover -> dry-run snapshot -> review -> apply -> destination verify -> authority handoff -> retire old writer
```

If source bytes or target workspace topology drift after review, apply fails closed.

If unresolved/invalid records remain, authority handoff does not occur.

## Privacy and scope

Persist only information appropriate for durable local history. Workspace boundaries apply to Memory recall and write placement exactly as they apply to the host routing model.
