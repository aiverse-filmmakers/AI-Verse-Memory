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

## Automatic safe capture

Runtime/Brain classification may suggest a historical memory, but Memory owns final admission through `capture_candidate`.

Automatic capture is eligible only when the caller supplies bounded evidence proving all of the following:

- the candidate is durable and historical;
- it is not current canonical truth;
- it is not strategic authority;
- it does not contain secrets;
- privacy/scope is not ambiguous;
- it does not expand permission or external authority;
- confidence is at least the automatic threshold;
- provenance source, evidence refs, and retry-safe `effect_id` are present.

Automatic capture is limited to historical `fact`, `preference`, `entity`, `event`, `experience`, `workflow`, `lesson`, and `correction` records. Current `state`, `constraint`, `decision`, and legacy `project_state` remain outside this automatic path.

The admission gate is a thin wrapper over the existing canonical `write_atomic` mutation. It creates no second Memory store or writer.

## Selective session-digest promotion

A completed session digest may provide evidence for a small number of durable atomic Memory records through `promote_session_digest`.

Promotion is deliberately not a classifier or another Memory authority:

- the caller still supplies explicit admission assertions;
- at most 8 candidates may be evaluated from one digest call;
- every candidate is forced to the digest's exact scope;
- caller-supplied evidence references must already exist in the digest's `source_refs` or `source_coverage`;
- the canonical digest reference is added as promotion evidence;
- retry-safe effect identity is derived deterministically when the caller does not supply one;
- each candidate still passes through `capture_candidate`, so transient, weak-confidence, secret, strategic, current-truth, permission-expanding, privacy-ambiguous, or external-authority material remains blocked/ignored.

A correction must name the exact historical Memory record it supersedes. Memory performs the replacement as one serialized two-file transaction, preserves the old record as superseded history, retains evidence refs, and records the retry-safe effect receipt. Cross-scope supersession is rejected.

Session digests remain evidence/navigation. Promotion never turns the whole digest or transcript into atomic Memory automatically.

## Tiny orientation map

`get_orientation_map` exposes a disposable per-scope routing projection before deeper recall.

The map contains only compact metadata:

- visible scope bindings;
- counts of active atomic Memory, indexed owner sources, and session digests;
- active Memory type counts;
- indexed source kind counts and a tiny set of source routes;
- explicit Memory tags and session-digest topics;
- recent digest identifiers/topics for escalation to session-level history.

It does not copy atomic Memory text, current-source bodies, digest summaries, or raw transcripts. Workspace maps follow existing Memory visibility rules: the bound workspace plus operator context, never another workspace.

The projection lives only in the derived SQLite database. Every public map read rebuilds from canonical atomic metadata, refreshed current-source index state, and the canonical session-digest projection so deletion/rebuild and source removal remain lossless.

Schema v2 adds a deterministic `source_fingerprint` over the authorized source identities/versions used for that scope. Atomic-file changes, current-source version changes, or session-digest canonical-version changes alter the fingerprint; unrelated workspace evidence does not. Stored projection rows are never trusted as authority and are replaced from current owner evidence on read.

Orientation output is hard-bounded by serialized UTF-8 bytes. Callers may supply `max_bytes`, or use `AI_VERSE_ORIENTATION_MAP_MAX_BYTES`; the default is 8192 bytes and the supported range is 1024-65536. Budget pressure removes only optional navigation detail in deterministic order while retaining scope, fingerprint, source counts, Memory-type counts, and source-kind counts. If even the core metadata cannot fit the configured budget, the call fails explicitly rather than silently violating the cap.

`get_orientation_map_diagnostics` returns content-free operational facts only: projection bytes, a declared byte-based token estimate, budget, truncation flag, source counts, returned-entry counts, visible-scope count, fingerprint, and freshness. It does not expose chain-of-thought or canonical source text.

## Progressive recall v1

Memory exposes one additive versioned progressive retrieval contract: `memory.progressive-recall.v1`.

The depth ladder is owner-preserving:

1. `catalog` reuses the rebuildable B2 orientation projection.
2. `summary` combines existing targeted session-digest recall with compact excerpts from existing query-bound indexed recall.
3. `detail` returns bounded targeted digest/index detail and evidence pointers.
4. `source` accepts a prior detail item as `evidence_ref` and revalidates exact source scope, containment, identity, and version before returning canonical text.

Legacy `recall()` is unchanged. Progressive recall calls existing `recall()`, `recall_session_digests()`, and `get_orientation_map()` rather than introducing a second ranking/index authority.

Summary/detail require a non-empty query and stay within normal operator/workspace visibility. The v1 surface does not expose all-workspace retrieval. Item count is capped and serialized UTF-8 response bytes are hard-bounded by caller configuration. Budget pressure may omit bounded content while retaining record identity/evidence pointers; it never widens scope.

Every summary/detail item states whether deeper evidence exists and carries the evidence metadata available at that layer. These layers are not exact-source truth.

At source depth, indexed atomic/current-owner records are read only from the currently validated canonical path. The expected version from the detail pointer must match the source version computed at read time. Version drift returns `stale` without content; deletion or containment failure returns `unavailable` without content; scope/path/identity tampering is rejected. Large sources are returned as deterministic query-centered exact windows under the same byte budget, with line/character coverage and explicit truncation metadata.

Session digests are deliberately different: the canonical digest file is itself a compact summary. After validating its canonical version and scope, source depth returns `external_source_required` plus bounded Gateway `source_refs` / coverage. It never upgrades the digest summary into original transcript evidence.

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
