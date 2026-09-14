---
name: ai-verse-memory
description: Operate AI-Verse Memory as scoped historical memory. In AI-Verse OS v2 it stores historical atomics in host-owned Memory layers and indexes selected current canonical sources in place; elsewhere it uses the standalone .ai-verse-memory layout.
version: 0.3.0-beta.1
author: AI-VERSE
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, context, agent-os, local-first, ai-verse]
    category: productivity
---

# AI-Verse Memory

## Core rule

> Current truth keeps its canonical owner. Memory owns durable history, provenance, corrections, experiences, and lessons.

Markdown is canonical. SQLite is derived.

## Public lifecycle

Use the component lifecycle for installation state:

```bash
python scripts/component.py --target <root> install
python scripts/component.py --target <root> setup
python scripts/component.py --target <root> --json status
python scripts/component.py --target <root> --json doctor
```

Install does not imply setup. Setup does not imply migration or authority transfer.

## Recall

Native operator:

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

Do not use `--all-workspaces` unless the task genuinely spans multiple workspaces.

## Historical capture

Save only durable history that can matter later. Do not duplicate current host truth.

Examples:

```bash
python <memory-engine> remember --type experience --scope operator --text "<historical outcome>"
python <memory-engine> remember --type correction --workspace <id> --text "<what was corrected>"
python <memory-engine> remember --type lesson --workspace <id> --text "<lesson>" \
  --source "<provenance>" --evidence-ref "<evidence>" --effect-id "<retry-key>"
```

Use `--effect-id` when a durable write may be retried.

## Self-learning evidence

Memory may record:

- success/failure experiences;
- corrections;
- lessons;
- provenance and evidence references.

Memory must not create executable Skill packages or decide strategic promotion. Skills owns Skill lifecycle. Brain owns strategy/evaluation.

## Automatic safe historical capture

For owner-routed runtime capture, call the Memory module's `capture_candidate` admission gate rather than writing Markdown directly.

The caller must explicitly prove durability/history and explicitly deny current-truth, secret, strategic, privacy-ambiguity, permission-expansion and external-authority boundaries. Memory then reuses canonical `write_atomic` with source, evidence refs and `effect_id`.

Do not use automatic capture for current state, constraints, decisions, credentials, strategic direction or uncertain/private material.

For a completed session digest, use `promote_session_digest` only with a bounded set of explicit durable candidates. Promotion must stay in the digest's scope and use evidence already covered by the digest. The promotion layer still routes each candidate through `capture_candidate`.

Corrections must name the historical Memory ID they supersede. Do not create an unbound correction or overwrite the old Markdown record.

## Orientation before deep recall

Use `get_orientation_map` when a caller needs a tiny scoped catalog before targeted recall. The map is derived SQLite state only. It may expose counts, types, source routes, explicit tags/topics, recent digest pointers, and a deterministic source fingerprint, but never full atomic text, current-source bodies, digest summaries, or raw transcripts.

Honor the configured byte budget. `max_bytes` or `AI_VERSE_ORIENTATION_MAP_MAX_BYTES` bounds serialized output, and deterministic truncation must preserve scope, fingerprint, counts, Memory-type counts, and source-kind counts. Use `get_orientation_map_diagnostics` for byte/token estimates, source counts, freshness, and truncation state; diagnostics must stay content-free and must not expose hidden reasoning.

Treat the map as navigation, not evidence. Deeper Memory/digest/source reads remain authoritative.

## Progressive recall

Use `progressive_recall` when the caller wants a bounded retrieval layer instead of legacy flat recall.

- Start at `catalog` when orientation is enough.
- Use `summary` for relevant session-level navigation and compact indexed-record excerpts.
- Use `detail` only when the caller needs the bounded indexed content and evidence pointers.
- Follow `next_depth="source"` only when exact evidence is needed. Pass the complete prior detail item as `evidence_ref`; do not manufacture or widen its path/scope/version metadata.
- Accept exact text only when source depth returns `status="ok"` and `exact_evidence=true`. `stale` or `unavailable` means do not guess from detail text.
- A session digest may return `external_source_required`; route those validated Gateway refs through the later owner bridge rather than treating the digest summary as transcript evidence.

Do not treat summary excerpts or digest summaries as exact evidence. Preserve the returned scope and evidence metadata when requesting deeper retrieval.

## Supersession

When historical meaning changes, supersede the old atomic record instead of rewriting chronology.

## Migration

Memory-first to OS-later adoption is explicit:

```bash
python scripts/component.py --target <new-os> migrate --source-root <old-project>
python scripts/component.py --target <new-os> migrate --source-root <old-project> --apply
```

Apply requires an unchanged reviewed source fingerprint and target workspace topology. Verified handoff retires the supported old writer while preserving historical source Markdown.

## Safety

Honor workspace scope, physical path containment, and the host ownership model. Never use Memory as a second current-context, Skill, or Brain-strategy store.
