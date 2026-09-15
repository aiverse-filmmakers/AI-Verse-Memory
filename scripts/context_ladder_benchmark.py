#!/usr/bin/env python3
"""J1 deterministic Context Ladder benchmark for the AI-Verse Memory owner.

The benchmark exercises the real Memory engine. It does not replace recall with
fixture-side search logic. Timing is observational; correctness, scope, source
validation and rebuild fields are deterministic acceptance evidence.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

SCHEMA_VERSION = 1
BENCHMARK_VERSION = "memory.context-ladder-j1.v1"
DEFAULT_SAMPLES = 3
HERE = Path(__file__).resolve().parent


def load_memory(name: str = "_aiverse_memory_j1_benchmark"):
    spec = importlib.util.spec_from_file_location(name, HERE / "memory.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load AI-Verse Memory")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def nbytes(value: object) -> int:
    return len(stable(value).encode("utf-8"))


def median_ms(values_ns: Sequence[int]) -> float:
    if not values_ns:
        return 0.0
    return round(statistics.median(values_ns) / 1_000_000.0, 3)


def measured(fn: Callable[[], Any], samples: int) -> Tuple[Any, List[int]]:
    result = None
    timings: List[int] = []
    for _ in range(max(1, samples)):
        start = time.perf_counter_ns()
        result = fn()
        timings.append(time.perf_counter_ns() - start)
    return result, timings


def native_root(base: Path) -> Path:
    root = base / "os"
    root.mkdir()
    (root / "AI-VERSE.yaml").write_text(
        'schema_version: "2.0"\narchitecture: unified-workspace\n',
        encoding="utf-8",
    )
    (root / "operator").mkdir()
    (root / "operator" / "context").mkdir()
    (root / "operator" / "context" / "CURRENT.md").write_text(
        "# Current Context\n\n## Current state\n\nOperator J1 benchmark context.\n",
        encoding="utf-8",
    )
    for wid in ("alpha", "beta"):
        owner = root / "workspaces" / wid
        owner.mkdir(parents=True)
        (owner / "WORKSPACE.yaml").write_text(
            'schema_version: "2.0"\n'
            f'id: "{wid}"\n'
            f'name: "{wid.title()}"\n'
            'type: "benchmark"\n'
            'status: "active"\n'
            'purpose: "Context Ladder J1 benchmark"\n',
            encoding="utf-8",
        )
        (owner / "context").mkdir()
    (root / "workspaces" / "alpha" / "context" / "CURRENT.md").write_text(
        "# Current Context\n\n## Current state\n\n"
        "J1-CANONICAL-SOURCE-MARKER Alpha render profile is ACEScg.\n",
        encoding="utf-8",
    )
    (root / "workspaces" / "beta" / "context" / "CURRENT.md").write_text(
        "# Current Context\n\n## Current state\n\n"
        "BETA-PRIVATE-J1 Client Atlas profile must remain isolated.\n",
        encoding="utf-8",
    )
    return root


def write_digest(
    mem,
    root: Path,
    *,
    workspace: str,
    session_id: str,
    run_id: str,
    topic: str,
    summary: str,
    completed_at: str,
):
    digest_char = "a" if workspace == "alpha" else "b"
    return mem.write_session_digest(
        session_id,
        summary,
        run_id=run_id,
        scope=f"workspace:{workspace}",
        topic=topic,
        significant_outcomes=[f"{topic} completed"],
        unresolved_items=[],
        source_refs=[
            f"gateway:session:{session_id}",
            f"gateway:run:{run_id}",
        ],
        source_coverage=[f"gateway:run:{run_id}:messages:0-8"],
        source_fingerprint="sha256:" + digest_char * 64,
        source_version="gateway-run-v1",
        provenance={
            "owner": "ai-verse-gateway",
            "kind": "completed_session",
            "session_id": session_id,
            "run_id": run_id,
        },
        completed_at=completed_at,
        effect_id=f"j1:{workspace}:{run_id}",
        root=root,
        mode=mem.MODE_NATIVE,
    )


def fixture(mem, root: Path) -> Dict[str, Any]:
    ancient_digest, _, _ = write_digest(
        mem,
        root,
        workspace="alpha",
        session_id="sess-j1-ancient-atlas",
        run_id="run-j1-ancient-atlas",
        topic="J1 ancient Atlas kickoff",
        summary=(
            "J1 ancient Atlas kickoff selected the gold launch treatment and "
            "documented the first client approval."
        ),
        completed_at="2024-01-10T12:00:00+00:00",
    )

    repeated_ids: List[str] = []
    for index in range(4):
        mid, _, _ = mem.write_atomic(
            (
                f"J1 Client Atlas campaign context {index}: gold launch treatment "
                f"requires review lane {index}."
            ),
            "experience",
            "workspace:alpha",
            tags="j1,client-atlas,campaign,gold",
            source="j1-benchmark",
            effect_id=f"j1-atlas-context-{index}",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        repeated_ids.append(mid)

    exact_id, exact_path, _ = mem.write_atomic(
        (
            "J1 Atlas launch date is 18 September 2026. "
            "Config path is /srv/atlas/config.json. Target port is 7200."
        ),
        "fact",
        "workspace:alpha",
        tags="j1,atlas,launch,config,port",
        source="j1-benchmark",
        effect_id="j1-exact-fact",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    old_id, _, _ = mem.write_atomic(
        "J1-NYX target port is 7100.",
        "fact",
        "workspace:alpha",
        tags="j1,nyx,target,port",
        source="j1-benchmark",
        effect_id="j1-old-port",
        root=root,
        mode=mem.MODE_NATIVE,
    )
    correction_id, _, _ = mem.supersede_atomic(
        old_id,
        "J1-NYX target port is 7200.",
        mem_type="correction",
        scope="workspace:alpha",
        evidence_refs=["gateway:run:run-j1-port-correction"],
        tags="j1,nyx,target,port,correction",
        effect_id="j1-new-port",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    beta_id, _, _ = mem.write_atomic(
        (
            "BETA-PRIVATE-J1 Client Atlas campaign context: gold launch treatment "
            "uses private beta-only instructions."
        ),
        "experience",
        "workspace:beta",
        tags="j1,client-atlas,campaign,gold",
        source="j1-benchmark",
        effect_id="j1-beta-private",
        root=root,
        mode=mem.MODE_NATIVE,
    )
    beta_digest, _, _ = write_digest(
        mem,
        root,
        workspace="beta",
        session_id="sess-j1-beta-private",
        run_id="run-j1-beta-private",
        topic="J1 Client Atlas campaign",
        summary="BETA-PRIVATE-J1 private Atlas campaign session.",
        completed_at="2026-09-14T12:00:00+00:00",
    )

    mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)
    mem.rebuild_relationship_projection(root=root, mode=mem.MODE_NATIVE)

    return {
        "ancient_digest": ancient_digest,
        "repeated_ids": repeated_ids,
        "exact_id": exact_id,
        "exact_path": exact_path,
        "old_id": old_id,
        "correction_id": correction_id,
        "beta_ids": {beta_id, beta_digest},
        "canonical_source_path": root / "workspaces" / "alpha" / "context" / "CURRENT.md",
    }


def response_ids(response: Mapping[str, Any]) -> List[str]:
    result: List[str] = []
    for item in response.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        value = str(item.get("id") or "")
        if value and value not in result:
            result.append(value)
    return result


def row_ids(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    result: List[str] = []
    for row in rows:
        value = str(row.get("id") or "")
        if value and value not in result:
            result.append(value)
    return result


def contains_marker(value: object, marker: str) -> bool:
    return marker in stable(value)


def canonical_fingerprint(root: Path) -> str:
    rows: List[Tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if ".ai-verse-memory-state" in rel or rel.startswith(".ai-verse-memory/"):
            continue
        if path.suffix.lower() in {".md", ".json", ".yaml", ".yml"}:
            rows.append((rel, hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256(stable(rows).encode("utf-8")).hexdigest()


def scenario_prior_session(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    query = "J1 ancient Atlas kickoff gold launch treatment"
    baseline, bt = measured(
        lambda: mem.recall_session_digests(
            query,
            workspace="alpha",
            limit=8,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    candidate, ct = measured(
        lambda: mem.progressive_recall(
            query,
            depth="summary",
            workspace="alpha",
            limit=6,
            max_bytes=8192,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    expected = str(fx["ancient_digest"])
    return {
        "scenario_id": "very_old_prior_session",
        "baseline_correct": expected in row_ids(baseline),
        "candidate_correct": expected in response_ids(candidate),
        "baseline_bytes": nbytes(baseline),
        "candidate_bytes": nbytes(candidate),
        "baseline_latency_ms": median_ms(bt),
        "candidate_latency_ms": median_ms(ct),
        "long_history_recovered": expected in response_ids(candidate),
        "source_reads": 0,
    }


def scenario_correction(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    current_query = "current J1-NYX target port"
    historical_query = "J1-NYX target port before correction"

    baseline, bt = measured(
        lambda: mem.recall(
            current_query,
            workspace="alpha",
            limit=6,
            include_history=False,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    current, ct1 = measured(
        lambda: mem.progressive_recall(
            current_query,
            depth="detail",
            workspace="alpha",
            limit=6,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    historical, ct2 = measured(
        lambda: mem.progressive_recall(
            historical_query,
            depth="detail",
            workspace="alpha",
            limit=6,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    current_ids = response_ids(current)
    history_ids = response_ids(historical)
    old_id = str(fx["old_id"])
    correction_id = str(fx["correction_id"])
    source_ref = next(
        item
        for item in historical["items"]
        if isinstance(item, Mapping) and item.get("id") == old_id
    )
    exact_old = mem.progressive_recall(
        historical_query,
        depth="source",
        workspace="alpha",
        evidence_ref=source_ref,
        max_bytes=6000,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    return {
        "scenario_id": "corrected_fact",
        "baseline_correct": correction_id in row_ids(baseline) and old_id not in row_ids(baseline),
        "candidate_correct": (
            correction_id in current_ids
            and old_id not in current_ids
            and old_id in history_ids
            and exact_old.get("status") == "ok"
            and "7100" in stable(exact_old)
        ),
        "baseline_bytes": nbytes(baseline),
        "candidate_bytes": nbytes(current) + nbytes(historical) + nbytes(exact_old),
        "baseline_latency_ms": median_ms(bt),
        "candidate_latency_ms": median_ms(ct1 + ct2),
        "source_reads": 1,
        "superseded_current_excluded": old_id not in current_ids,
        "historical_source_recovered": "7100" in stable(exact_old),
    }


def scenario_exact(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    query = "exact J1 Atlas launch date config path port"
    baseline, bt = measured(
        lambda: mem.recall(
            query,
            workspace="alpha",
            limit=6,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    detail, ct = measured(
        lambda: mem.progressive_recall(
            query,
            depth="detail",
            workspace="alpha",
            limit=6,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    evidence_ref = next(
        item
        for item in detail["items"]
        if isinstance(item, Mapping) and item.get("id") == fx["exact_id"]
    )
    source = mem.progressive_recall(
        query,
        depth="source",
        workspace="alpha",
        evidence_ref=evidence_ref,
        max_bytes=8192,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    rendered = stable(source)
    exact_ok = all(
        marker in rendered
        for marker in ("18 September 2026", "/srv/atlas/config.json", "7200")
    )
    return {
        "scenario_id": "exact_number_date_path_config",
        "baseline_correct": str(fx["exact_id"]) in row_ids(baseline),
        "candidate_correct": source.get("status") == "ok" and bool(source.get("exact_evidence")) and exact_ok,
        "baseline_bytes": nbytes(baseline),
        "candidate_bytes": nbytes(detail) + nbytes(source),
        "baseline_latency_ms": median_ms(bt),
        "candidate_latency_ms": median_ms(ct),
        "source_reads": 1,
        "exact_fact_recovered": exact_ok,
    }


def scenario_repeated_context(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    query = "J1 Client Atlas campaign gold launch treatment review lane"
    baseline, bt = measured(
        lambda: mem.recall(
            query,
            workspace="alpha",
            limit=8,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    candidate, ct = measured(
        lambda: mem.progressive_recall(
            query,
            depth="summary",
            workspace="alpha",
            limit=8,
            max_bytes=10000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    expected = set(str(item) for item in fx["repeated_ids"])
    candidate_ids = set(response_ids(candidate))
    relevant = len(expected.intersection(candidate_ids))
    returned = max(1, int(candidate.get("returned_items") or 0))
    irrelevant = max(0, returned - relevant)
    return {
        "scenario_id": "repeated_project_client_context",
        "baseline_correct": bool(expected.intersection(row_ids(baseline))),
        "candidate_correct": relevant >= 1,
        "baseline_bytes": nbytes(baseline),
        "candidate_bytes": nbytes(candidate),
        "baseline_latency_ms": median_ms(bt),
        "candidate_latency_ms": median_ms(ct),
        "relevant_items": relevant,
        "irrelevant_items": irrelevant,
        "irrelevant_context_rate": round(irrelevant / returned, 6),
        "source_reads": 0,
    }


def scenario_scope(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    query = "J1 Client Atlas campaign gold launch treatment private"
    baseline, bt = measured(
        lambda: mem.recall(
            query,
            workspace="alpha",
            limit=12,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    candidate, ct = measured(
        lambda: mem.progressive_recall(
            query,
            depth="detail",
            workspace="alpha",
            limit=12,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    baseline_leak = contains_marker(baseline, "BETA-PRIVATE-J1")
    candidate_leak = contains_marker(candidate, "BETA-PRIVATE-J1")
    beta_ids = set(str(item) for item in fx["beta_ids"])
    candidate_leak = candidate_leak or bool(beta_ids.intersection(response_ids(candidate)))
    return {
        "scenario_id": "two_similar_workspaces",
        "baseline_correct": not baseline_leak,
        "candidate_correct": not candidate_leak,
        "baseline_bytes": nbytes(baseline),
        "candidate_bytes": nbytes(candidate),
        "baseline_latency_ms": median_ms(bt),
        "candidate_latency_ms": median_ms(ct),
        "scope_leakage_count": int(candidate_leak),
        "source_reads": 0,
    }


def scenario_stale_source(mem, root: Path, fx: Mapping[str, Any], samples: int) -> Dict[str, Any]:
    query = "J1 CANONICAL SOURCE MARKER Alpha render profile ACEScg"
    detail, timings = measured(
        lambda: mem.progressive_recall(
            query,
            depth="detail",
            workspace="alpha",
            limit=8,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        ),
        samples,
    )
    indexed = next(
        item
        for item in detail["items"]
        if isinstance(item, Mapping)
        and item.get("record_type") == "indexed_record"
        and "CURRENT.md" in str(item.get("evidence", {}).get("path", ""))
    )
    path = Path(fx["canonical_source_path"])
    path.write_text(
        "# Current Context\n\n## Current state\n\n"
        "J1-CANONICAL-SOURCE-MARKER Alpha render profile changed to Display P3.\n",
        encoding="utf-8",
    )
    source = mem.progressive_recall(
        query,
        depth="source",
        workspace="alpha",
        evidence_ref=indexed,
        max_bytes=8192,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    stale = source.get("status") == "stale"
    return {
        "scenario_id": "canonical_source_changed_after_derived_artifact",
        "baseline_correct": True,
        "candidate_correct": stale and not bool(source.get("exact_evidence")),
        "baseline_bytes": 0,
        "candidate_bytes": nbytes(detail) + nbytes(source),
        "baseline_latency_ms": 0.0,
        "candidate_latency_ms": median_ms(timings),
        "source_reads": 1,
        "stale_source_fail_closed": stale,
    }


def rebuild_and_restart(mem, root: Path, fx: Mapping[str, Any]) -> Dict[str, Any]:
    before_canonical = canonical_fingerprint(root)
    orientation_before = mem.get_orientation_map(
        workspace="alpha",
        max_bytes=8192,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    rel_before = mem.rebuild_relationship_projection(root=root, mode=mem.MODE_NATIVE)

    conn, _ = mem.connect_db(root, mem.MODE_NATIVE)
    try:
        conn.execute("DROP TABLE IF EXISTS orientation_maps")
        conn.execute("DROP TABLE IF EXISTS memory_relationships")
        conn.commit()
    finally:
        conn.close()

    orientation_after = mem.get_orientation_map(
        workspace="alpha",
        max_bytes=8192,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    rel_after = mem.rebuild_relationship_projection(root=root, mode=mem.MODE_NATIVE)
    after_canonical = canonical_fingerprint(root)

    restarted = load_memory("_aiverse_memory_j1_restart")
    restart_result = restarted.progressive_recall(
        "J1 ancient Atlas kickoff gold launch treatment",
        depth="summary",
        workspace="alpha",
        limit=6,
        max_bytes=8192,
        root=root,
        mode=restarted.MODE_NATIVE,
    )

    return {
        "canonical_unchanged": before_canonical == after_canonical,
        "orientation_rebuilt_equivalent": (
            orientation_before.get("source_fingerprint")
            == orientation_after.get("source_fingerprint")
            and orientation_before.get("counts") == orientation_after.get("counts")
        ),
        "relationship_rebuilt_equivalent": (
            rel_before.get("projection_fingerprint")
            == rel_after.get("projection_fingerprint")
            and rel_before.get("edge_count") == rel_after.get("edge_count")
        ),
        "restart_recall_ok": str(fx["ancient_digest"]) in response_ids(restart_result),
    }


def run_benchmark(samples: int = DEFAULT_SAMPLES) -> Dict[str, Any]:
    mem = load_memory()
    with tempfile.TemporaryDirectory() as tmp:
        root = native_root(Path(tmp))
        fx = fixture(mem, root)

        scenarios = [
            scenario_prior_session(mem, root, fx, samples),
            scenario_correction(mem, root, fx, samples),
            scenario_exact(mem, root, fx, samples),
            scenario_repeated_context(mem, root, fx, samples),
            scenario_scope(mem, root, fx, samples),
            scenario_stale_source(mem, root, fx, samples),
        ]
        durability = rebuild_and_restart(mem, root, fx)

        baseline_applicable = [row for row in scenarios if row["baseline_bytes"] > 0]
        baseline_correct = sum(1 for row in baseline_applicable if row["baseline_correct"])
        candidate_correct = sum(1 for row in scenarios if row["candidate_correct"])
        source_reads = sum(int(row.get("source_reads") or 0) for row in scenarios)
        leakage = sum(int(row.get("scope_leakage_count") or 0) for row in scenarios)
        exact = next(row for row in scenarios if row["scenario_id"] == "exact_number_date_path_config")
        prior = next(row for row in scenarios if row["scenario_id"] == "very_old_prior_session")
        repeated = next(row for row in scenarios if row["scenario_id"] == "repeated_project_client_context")
        stale = next(row for row in scenarios if row["scenario_id"] == "canonical_source_changed_after_derived_artifact")

        baseline_latencies = [
            row["baseline_latency_ms"]
            for row in baseline_applicable
            if row["baseline_latency_ms"] > 0
        ]
        candidate_latencies = [
            row["candidate_latency_ms"]
            for row in scenarios
            if row["candidate_latency_ms"] > 0
        ]

        return {
            "schema_version": SCHEMA_VERSION,
            "benchmark_version": BENCHMARK_VERSION,
            "owner": "ai-verse-memory",
            "samples_per_timed_operation": max(1, samples),
            "baseline": {
                "applicable_scenarios": len(baseline_applicable),
                "correct_scenarios": baseline_correct,
                "correctness": round(
                    baseline_correct / len(baseline_applicable), 6
                ) if baseline_applicable else 1.0,
                "context_bytes": sum(row["baseline_bytes"] for row in baseline_applicable),
                "median_retrieval_latency_ms": round(
                    statistics.median(baseline_latencies), 3
                ) if baseline_latencies else 0.0,
            },
            "candidate": {
                "total_scenarios": len(scenarios),
                "correct_scenarios": candidate_correct,
                "correctness": round(candidate_correct / len(scenarios), 6),
                "context_bytes": sum(row["candidate_bytes"] for row in scenarios),
                "median_retrieval_latency_ms": round(
                    statistics.median(candidate_latencies), 3
                ) if candidate_latencies else 0.0,
                "exact_fact_recovery": bool(exact["exact_fact_recovered"]),
                "long_history_recovery": bool(prior["long_history_recovered"]),
                "irrelevant_context_rate": repeated["irrelevant_context_rate"],
                "source_reads": source_reads,
            },
            "safety": {
                "scope_leakage_count": leakage,
                "stale_source_fail_closed": bool(stale["stale_source_fail_closed"]),
                "canonical_mutation_during_rebuild": not durability["canonical_unchanged"],
            },
            "durability": durability,
            "scenarios": scenarios,
        }


def main() -> int:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
