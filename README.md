# AI-Verse Memory

AI-Verse Memory is a local-first historical memory component for AI agents and AI operating systems. Canonical historical memory stays human-readable Markdown. SQLite is derived, disposable recall state.

Current public-beta version: **0.3.0-beta.1**.

In AI-Verse OS v2, current profile, context, decisions, workspace topology, and knowledge keep their existing owners. Memory owns historical atomic memory, provenance, corrections, experiences, and lessons. Memory does not own Skills or Brain strategy.

## Requirements

- Python 3.9+
- Linux, macOS, or Windows
- AI-Verse OS v2, or a standalone file-aware Agent-OS repository

## Install

Use the public component lifecycle:

```bash
python scripts/component.py --target /path/to/target install
```

Install makes the Memory package/runtime available. It does not attach Memory, initialize canonical state, transfer authority, approve scopes, or migrate old state.

Verify the expected post-install state:

```bash
python scripts/component.py --target /path/to/target --json status
```

Expected state: `setup-required`.

The older `install.sh`, `install.ps1`, and `scripts/install.py` path remains for backward compatibility with the frozen beta and retains the historical combined install/setup behavior.

## Setup

```bash
python scripts/component.py --target /path/to/target setup
```

Native setup:

1. installs Memory runtime adapters;
2. attaches through `.aiverse/extensions/registry.json`;
3. initializes/rebuilds derived recall state;
4. records Memory setup state;
5. detects legacy Memory that still requires adoption.

Setup never silently migrates old state or transfers canonical authority. If an active legacy store is detected, status becomes `migration-required`.

Standalone setup initializes the portable `.ai-verse-memory/` layout and bounded agent integration.

## Verify

Fast, non-destructive status:

```bash
python scripts/component.py --target /path/to/target status
python scripts/component.py --target /path/to/target --json status
```

Primary states:

- `absent`
- `setup-required`
- `disabled`
- `unhealthy`
- `migration-required`
- `ready`

Deeper read-only doctor:

```bash
python scripts/component.py --target /path/to/target doctor
python scripts/component.py --target /path/to/target --json doctor
```

Memory doctor reports structural, attachment, runtime, dependency, and operational depth separately. It does not claim whole-system readiness.

## Use

Native example:

```bash
python scripts/ai-verse-memory/memory.py --root /path/to/AI-Verse-OS remember \
  --type experience \
  --workspace example \
  --text "The supervised test exposed a retry edge case."

python scripts/ai-verse-memory/memory.py --root /path/to/AI-Verse-OS recall \
  "retry edge case" \
  --workspace example
```

Retry-safe historical evidence capture:

```bash
python scripts/ai-verse-memory/memory.py --root /path/to/AI-Verse-OS remember \
  --type lesson \
  --workspace example \
  --text "Bounded retry recovered this provider failure." \
  --source "run:render-42" \
  --evidence-ref "receipt:42" \
  --evidence-ref "artifact:render-42" \
  --effect-id "learning-effect-42"
```

The same `--effect-id` with the same input returns the original effect. Reusing that ID for different input is rejected.

Standalone uses the same engine commands through `.ai-verse-memory/memory.py`.

## Automatic safe historical capture

Owner-routed runtimes may call the Memory module's `capture_candidate` admission gate for high-confidence durable historical facts, preferences, entities, events, experiences, workflows, lessons, or corrections.

The gate fails closed unless the caller explicitly proves the candidate is durable historical evidence and explicitly denies current-truth, secret, strategic, privacy-ambiguity, permission-expansion, and external-authority boundaries. Provenance source, evidence references, and a retry-safe `effect_id` are mandatory.

This path reuses the existing canonical Memory writer. It does not persist every turn, duplicate current profile/context truth, or create another Memory store.

### Selective promotion from session digests

Session digests can be used as bounded evidence for durable atomic Memory through the module API `promote_session_digest`. The caller supplies explicit candidates and safety assertions; Memory does not infer a durable fact merely because it appeared in a conversation.

Promotion is capped per digest, locked to the digest's scope, and accepts only evidence references covered by that digest. Safe candidates still route through `capture_candidate`. Explicit corrections must identify the older Memory record they supersede; Memory then performs a retry-safe transactional supersession so normal recall sees the correction while historical recall preserves the stale record.

### Tiny orientation map

The module API `get_orientation_map` builds a small per-scope catalog before deeper recall. It aggregates counts, Memory types, current-source routes, explicit tags/topics, and recent session-digest pointers without copying canonical text or digest summaries.

The map is stored only in the disposable SQLite index and rebuilt from authoritative Memory/source/digest evidence on read. It carries a deterministic `source_fingerprint` over only the currently authorized atomic Memory, current-source versions, and session-digest versions. A source change therefore changes the fingerprint and the next read replaces any stale stored projection. Deleting the projection or shared derived database does not lose truth.

`get_orientation_map(..., max_bytes=N)` enforces a hard serialized UTF-8 byte budget. The default is 8192 bytes and may be configured with `AI_VERSE_ORIENTATION_MAP_MAX_BYTES`; accepted values are 1024-65536. If pressure requires truncation, sample route paths, older recent-session pointers, lower-ranked topics, and finally route entries are removed deterministically while scope, source fingerprint, counts, Memory-type counts, and source-kind counts are preserved.

`get_orientation_map_diagnostics` reports projection bytes, a transparent byte-based token estimate, configured budget, truncation state, source counts, visible-scope count, and freshness. It never exposes hidden reasoning or canonical Memory/source content. Workspace orientation follows normal Memory visibility: the bound workspace plus operator context, never an unrelated workspace.

### Progressive recall v1

The module API `progressive_recall` adds one versioned retrieval surface without changing legacy `recall()`.

- `depth="catalog"` reuses the B2 orientation map and does not require a query.
- `depth="summary"` uses existing session-digest recall plus compact query-bound excerpts from existing indexed Memory/current-source recall.
- `depth="detail"` returns bounded targeted digest/index detail with provenance and evidence pointers.
- `depth="source"` is intentionally reserved for the C2 exact-source extension. C1 detail may report `next_depth="source"` and `deeper_evidence_available=true`, but `source_depth_available` remains false until exact-source validation exists.

The API version is `memory.progressive-recall.v1`. Summary/detail require a non-empty query, use existing Memory scope rules, and never enable all-workspace retrieval. Responses are hard-bounded by `max_bytes` or `AI_VERSE_PROGRESSIVE_RECALL_MAX_BYTES` (default 16384; supported 4096-65536) and by at most 20 returned items.

Summary/detail output is navigation or bounded indexed detail, not exact-source evidence. Evidence pointers carry canonical/derived path and version metadata so callers can decide whether a C2 source descent is required.

## Update, disable, enable, uninstall

Update without changing enablement or authority:

```bash
python scripts/component.py --target /path/to/target update
```

Native enablement:

```bash
python scripts/component.py --target /path/to/AI-Verse-OS disable
python scripts/component.py --target /path/to/AI-Verse-OS enable
```

Uninstall integration/runtime while preserving canonical user state:

```bash
python scripts/component.py --target /path/to/target uninstall
```

Reinstall does not silently restore attachment:

```bash
python scripts/component.py --target /path/to/target install
python scripts/component.py --target /path/to/target reconcile
```

`reconcile` rediscovers the preserved Memory setup receipt. It does not migrate legacy authority automatically.

Expert registry-only detach:

```bash
python scripts/component.py --target /path/to/AI-Verse-OS detach
```

## What setup does not grant

Setup does not grant new workspace permissions, external account access, Brain strategy ownership, Skill lifecycle ownership, automatic self-modification, or silent legacy authority transfer.

Memory is an evidence/history owner, not a permission engine or strategy engine.

## Native ownership

When `AI-VERSE.yaml` declares schema v2 and `architecture: unified-workspace`, Memory owns historical atomic state under:

```text
operator/memory/atomic/
workspaces/<id>/memory/atomic/
```

Its derived index is:

```text
runtime/indexes/ai-verse-memory/memory.db
```

Current native sources are indexed in place rather than copied into a second Memory truth store.

Workspace recall is isolated by default:

```bash
python scripts/ai-verse-memory/memory.py recall "<query>" --workspace <id>
```

Cross-workspace recall requires `--all-workspaces`.

Native reads and writes validate physical path containment. Symlinked owner boundaries that escape or cross scope are rejected.

## Historical learning evidence

Historical types include `fact`, `preference`, `constraint`, `state`, `entity`, `event`, `experience`, `workflow`, `lesson`, and `correction`. Legacy `decision` and `project_state` remain accepted for compatibility.

For self-learning, Memory owns only historical evidence:

- what happened;
- whether it succeeded or failed;
- corrections;
- lessons;
- provenance and evidence references.

Memory does not store executable Skill packages and does not decide strategic promotion. Skills owns Skill lifecycle. Brain owns strategic evaluation.

## Memory-first, OS-later adoption

Plan and fingerprint the source:

```bash
python scripts/component.py --target /path/to/AI-Verse-OS migrate \
  --source-root /path/to/old-project
```

Apply only after review:

```bash
python scripts/component.py --target /path/to/AI-Verse-OS migrate \
  --source-root /path/to/old-project \
  --apply
```

Apply refuses if the reviewed source or target workspace topology drifted.

When every blocking record is resolved and destination verification succeeds, Memory records a canonical authority handoff, marks the old standalone store retired, retires the supported old writer when present, and preserves the old historical Markdown as evidence.

If unresolved or invalid records remain, authority handoff does not occur. Two writable canonical Memory routes are never declared valid.

See [migration/MIGRATION.md](migration/MIGRATION.md).

## Concurrency and durability

Canonical Memory mutation is serialized across processes. File effects use atomic replacement, stale mutation locks can recover, supersession uses a recovery journal, and retryable remember effects can use durable idempotency receipts.

The SQLite index remains derived and rebuildable.

## Release and acceptance

CI covers Python 3.9 and 3.12 on Linux, macOS, and Windows. A separate public-beta acceptance gate exercises lifecycle, migration, containment, and idempotency on all three operating systems.

The exact immutable public-beta artifact is recorded under `releases/` after the candidate commit passes acceptance. Bootstrap references are then pinned to that exact commit instead of mutable `main`.

## License

MIT.
