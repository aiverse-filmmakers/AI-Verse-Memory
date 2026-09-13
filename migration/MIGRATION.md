# Historical Memory Migration

AI-Verse Memory public beta uses explicit, snapshot-bound adoption. Migration is separate from setup because copying history and transferring canonical authority are different effects.

## Existing Agent-OS history

Use `discover` to identify likely historical sources, then distill only durable history:

```bash
python <memory-engine> discover . --output <migration-report-path>
```

Do not bulk-import current profile/context/decision/knowledge files. Those remain authoritative where their current owner keeps them.

Good historical candidates include events, state transitions, corrections, lessons, durable past constraints, entity history, and workflow experiences.

## Legacy AI-Verse Memory into native AI-Verse OS

### 1. Dry run

Local legacy store:

```bash
python scripts/ai-verse-memory/memory.py --root <new-os> migrate-legacy
```

External Memory-first source:

```bash
python scripts/ai-verse-memory/memory.py --root <new-os> migrate-legacy \
  --source-root <old-project>
```

The dry run creates:

```text
operator/memory/migrations/legacy-ai-verse-memory-plan.json
operator/memory/migrations/legacy-ai-verse-memory-migration.md
```

The plan records:

- the validated source root;
- a fingerprint of source memory paths and bytes;
- target workspace-topology fingerprint;
- record-by-record scope mapping;
- blocking unresolved/invalid records.

Scope mapping is conservative:

- `global` and `operator` -> `operator`;
- `project:<id>`, `client:<id>`, and `workspace:<id>` -> matching workspace only;
- unknown scopes remain unresolved.

### 2. Review

Review the plan and report. The source may continue to operate during review, but any later source drift invalidates apply and requires a new dry run.

### 3. Apply

```bash
python scripts/ai-verse-memory/memory.py --root <new-os> migrate-legacy \
  --source-root <old-project> \
  --apply
```

Apply requires the reviewed dry-run plan.

It refuses when:

- source memory bytes changed after review;
- target workspace topology changed after review;
- a destination ID conflicts with different canonical content.

Migrated records preserve IDs, chronology, original provenance when present, and add migration provenance including source path, source digest, source snapshot fingerprint, and migration timestamp.

If a valid old record has no `source`, fallback provenance is based on the validated old source path. External sources do not need to be relative to the new OS root.

### 4. Authority handoff

A successful copy is not automatically a successful authority handoff.

Handoff occurs only when blocking unresolved/invalid records are zero and destination verification succeeds.

The new native store records:

```text
operator/memory/.ai-verse-memory-state/authority-handoff.json
```

The old standalone store records:

```text
.ai-verse-memory/AUTHORITY.json
```

with status `retired`.

If the old store contains the supported `.ai-verse-memory/memory.py` writer, it is backed up and replaced by a retirement stub. Historical memory Markdown under `memories/` is not rewritten by the handoff.

This preserves evidence without preserving competing writable authority.

### 5. Completion

After representative recall verification:

```bash
python <memory-engine> migration-complete \
  --summary "Reviewed historical migration and verified canonical handoff."
```

When a migration plan exists, `migration-complete` refuses unless the handoff receipt matches the reviewed source fingerprint.

If unresolved/invalid records remain, the old route stays active and the new component remains `migration-required`. Resolve the blockers, generate a new dry-run plan, then apply again.

## Public lifecycle shortcut

The standard component CLI exposes the same explicit adoption:

```bash
python scripts/component.py --target <new-os> migrate --source-root <old-project>
python scripts/component.py --target <new-os> migrate --source-root <old-project> --apply
```

`setup` only detects migration need. It never calls apply automatically.

## Safety invariants

- No migration leaves two declared writable canonical Memory stores.
- Source drift after review fails closed.
- Destination scope is verified.
- Source history remains evidence after retirement.
- Symlinked or escaping source/destination paths are rejected.
- Migration can be retried safely because existing matching IDs are recognized rather than duplicated.
