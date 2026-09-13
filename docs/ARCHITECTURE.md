# AI-Verse Memory Architecture

## Public-beta architecture

AI-Verse Memory keeps the established local-first model:

```text
canonical Markdown
      |
      v
rebuildable SQLite index
      |
      v
scoped recall
```

The public-beta hardening does not introduce a new Memory architecture. It strengthens ownership, migration, lifecycle, and mutation boundaries around the same model.

## Native AI-Verse OS mode

The host remains canonical for current truth.

Memory owns historical atomics only:

```text
operator/memory/atomic/
workspaces/<id>/memory/atomic/
```

Memory derives recall views from selected current host sources without copying ownership.

The SQLite index is disposable:

```text
runtime/indexes/ai-verse-memory/memory.db
```

### Authority order

Current context, workspace manifests, decisions, and profile outrank historical Memory in recall.

A Brain direction-ownership change is treated as a semantic source-version change so frozen OS strategy cannot become current again through stale indexing.

## Physical isolation

Native source reads and canonical writes enforce both lexical and resolved physical ownership.

A symlink may not redirect:

- an operator Memory owner;
- a workspace owner;
- a Memory parent;
- an atomic destination;
- a migration destination.

Read rejection is not used as a substitute for write containment.

## Mutation protocol

Canonical mutation is serialized by a Memory-owned cross-process lock.

Single-file canonical writes use atomic replacement.

Retryable remember effects may use durable idempotency receipts.

Supersession uses a prepared transaction journal. If interrupted, the next mutation recovers the intended file effects before continuing.

SQLite rebuilds are coordinated with canonical mutation but remain derived state.

## Migration authority handoff

Legacy adoption is snapshot-bound:

```text
dry run
  -> source fingerprint
  -> target workspace fingerprint
  -> review
  -> apply only if unchanged
  -> destination verification
  -> handoff receipt
  -> source retirement marker
```

Old historical Markdown remains evidence. The supported old writable route is retired only after verified handoff.

If blockers remain, handoff remains pending.

## Lifecycle

The public lifecycle is separate from the Memory engine:

```text
scripts/component.py
```

It implements:

- install
- setup
- status
- doctor
- enable
- disable
- update
- uninstall

Expert lifecycle operations are reconcile, detach, and migrate.

Install does not imply setup. Setup does not transfer canonical authority. Uninstall preserves canonical user state. Reconcile can rediscover the preserved setup receipt.

## Self-learning boundary

Memory stores historical evidence, corrections, experiences, lessons, and provenance references.

Memory does not store executable Skill packages and does not own strategic promotion. Skills owns Skill lifecycle. Brain owns strategic/evaluation policy.

## Standalone mode

Without a compatible AI-Verse OS, `.ai-verse-memory/` remains the canonical portable Memory home.

After a verified native handoff, `AUTHORITY.json` marks that standalone store retired. Historical evidence remains readable, while supported new canonical writes are refused.

## Intentionally absent from public beta

The core does not require vector infrastructure, a background daemon, a separate model, or a cloud Memory service. Larger-scale retrieval tiers remain optional future derived adapters only.
