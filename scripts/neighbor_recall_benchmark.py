#!/usr/bin/env python3
"""D2 deterministic benchmark for tightly bounded one-hop Memory neighbor recall.

This is benchmark-only. It does not patch or replace the accepted direct/progressive
recall path. D2 must first prove that relationship traversal earns runtime complexity.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

SCHEMA = 1
VERSION = "memory.d2-neighbor-recall-benchmark.v2"
DIRECT_LIMIT = 6
MAX_NEIGHBORS = 4
MAX_RELATIONS = 200
MAX_BYTES = 12000
SAMPLES = 3
HERE = Path(__file__).resolve().parent

HISTORY_TERMS = {
    "before", "previous", "previously", "prior", "old", "older", "history",
    "historical", "corrected", "correction", "superseded", "supersedes", "replaced",
}
PROVENANCE_TERMS = {
    "source", "sources", "context", "evidence", "origin", "provenance",
    "session", "run", "incident", "derived", "why",
}
HISTORY_RELATIONS = {"supersedes", "superseded_by"}
PROVENANCE_RELATIONS = {"derived_from"}


def load_memory():
    spec = importlib.util.spec_from_file_location(
        "_aiverse_memory_d2_benchmark", HERE / "memory.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load AI-Verse Memory")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stable(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def nbytes(value: object) -> int:
    return len(stable(value).encode("utf-8"))


def native_root(base: Path) -> Path:
    root = base / "os"
    root.mkdir()
    (root / "AI-VERSE.yaml").write_text(
        'schema_version: "2.0"\narchitecture: unified-workspace\n',
        encoding="utf-8",
    )
    (root / "operator").mkdir()
    for wid in ("alpha", "beta"):
        owner = root / "workspaces" / wid
        owner.mkdir(parents=True)
        (owner / "WORKSPACE.yaml").write_text(
            'schema_version: "2.0"\n'
            f'id: "{wid}"\nname: "{wid.title()}"\n'
            'type: "test"\nstatus: "active"\n'
            'purpose: "D2 neighbor recall benchmark"\n',
            encoding="utf-8",
        )
    return root


def digest(mem, root: Path, wid: str, sid: str, rid: str, topic: str, summary: str):
    return mem.write_session_digest(
        sid,
        summary,
        run_id=rid,
        scope=f"workspace:{wid}",
        topic=topic,
        significant_outcomes=[f"{topic} completed"],
        unresolved_items=[],
        source_refs=[f"gateway:session:{sid}", f"gateway:run:{rid}"],
        source_coverage=[f"gateway:run:{rid}:messages:0-8"],
        source_fingerprint="sha256:" + hashlib.sha256(
            f"{wid}:{sid}:{rid}".encode()
        ).hexdigest(),
        source_version="gateway-run-v1",
        provenance={
            "owner": "ai-verse-gateway",
            "kind": "completed_session",
            "session_id": sid,
            "run_id": rid,
        },
        completed_at="2026-09-14T12:00:00+00:00",
        effect_id=f"d2:{wid}:{rid}",
        root=root,
        mode=mem.MODE_NATIVE,
    )


def fixture(mem, root: Path) -> Dict[str, Any]:
    lesson_digest, _, _ = digest(
        mem,
        root,
        "alpha",
        "sess-alpha-lesson",
        "run-alpha-lesson",
        "L19 causal packet",
        "L19 established that a two-pass process removed shimmer while preserving fine texture.",
    )
    lesson_id, _, _ = mem.write_atomic(
        "Aurora export lesson: use a two-pass temporal denoise before final delivery.",
        "lesson",
        "workspace:alpha",
        source=f"memory:session-digest:{lesson_digest}",
        evidence_refs=[
            f"memory:session-digest:{lesson_digest}",
            "gateway:run:run-alpha-lesson",
        ],
        tags="aurora,export,temporal,denoise",
        effect_id="d2-alpha-lesson",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    decision_digest, _, _ = digest(
        mem,
        root,
        "alpha",
        "sess-alpha-decision",
        "run-alpha-decision",
        "D11 rationale packet",
        "D11 recorded that the intermediate preserved chroma before downstream compression.",
    )
    decision_id, _, _ = mem.write_atomic(
        "Orion delivery decision: use ProRes mezzanine before the H264 distribution encode.",
        "decision",
        "workspace:alpha",
        source=f"memory:session-digest:{decision_digest}",
        evidence_refs=[
            f"memory:session-digest:{decision_digest}",
            "gateway:run:run-alpha-decision",
        ],
        tags="orion,delivery,prores,h264",
        effect_id="d2-alpha-decision",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    old_id, _, _ = mem.write_atomic(
        "Atlas target port is 7100.",
        "fact",
        "workspace:alpha",
        tags="atlas,target,port",
        effect_id="d2-alpha-old",
        root=root,
        mode=mem.MODE_NATIVE,
    )
    correction_id, _, _ = mem.supersede_atomic(
        old_id,
        "Atlas target port is 7200.",
        mem_type="correction",
        scope="workspace:alpha",
        evidence_refs=["gateway:run:run-alpha-correction"],
        tags="atlas,target,port,correction",
        effect_id="d2-alpha-correction",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    beta_digest, _, _ = digest(
        mem,
        root,
        "beta",
        "sess-beta-private",
        "run-beta-private",
        "B7 private packet",
        "BETA-PRIVATE-MARKER private summary.",
    )
    beta_id, _, _ = mem.write_atomic(
        "BETA-PRIVATE-MARKER Aurora export lesson must never cross workspace scope.",
        "lesson",
        "workspace:beta",
        source=f"memory:session-digest:{beta_digest}",
        evidence_refs=[f"memory:session-digest:{beta_digest}"],
        tags="aurora,export,temporal,denoise",
        effect_id="d2-beta-private",
        root=root,
        mode=mem.MODE_NATIVE,
    )

    return {
        "beta_ids": {beta_id, beta_digest},
        "ids": {
            "lesson": lesson_id,
            "lesson_digest": lesson_digest,
            "decision": decision_id,
            "decision_digest": decision_digest,
            "old": old_id,
            "correction": correction_id,
        },
        "cases": [
            {
                "name": "lesson_provenance",
                "query": "Aurora export denoise context",
                "expected": lesson_digest,
                "relevant": {lesson_digest},
                "forbidden": set(),
            },
            {
                "name": "decision_provenance",
                "query": "Orion ProRes H264 evidence",
                "expected": decision_digest,
                "relevant": {decision_digest},
                "forbidden": set(),
            },
            {
                "name": "correction_history",
                "query": "Atlas target port before correction",
                "expected": old_id,
                "relevant": {old_id},
                "forbidden": set(),
            },
            {
                "name": "correction_current",
                "query": "current Atlas target port",
                "expected": correction_id,
                "relevant": set(),
                "forbidden": {old_id},
            },
        ],
    }


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
    return hashlib.sha256(stable(rows).encode()).hexdigest()


def direct(mem, root: Path, query: str) -> Dict[str, Any]:
    """Reconstruct the accepted direct-only detail baseline.

    Do not call progressive_recall here: after D2 ships, that public surface may
    itself add relationship neighbors. The benchmark must keep a stable control
    group so future runs still compare direct retrieval against one-hop expansion.
    """
    digests = mem.recall_session_digests(
        query,
        workspace="alpha",
        limit=DIRECT_LIMIT,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    records = mem.recall(
        query,
        workspace="alpha",
        limit=DIRECT_LIMIT,
        include_history=False,
        root=root,
        mode=mem.MODE_NATIVE,
        all_workspaces=False,
    )

    items: List[Dict[str, Any]] = []
    count = max(len(digests), len(records))
    for index in range(count):
        if index < len(digests):
            digest_row = digests[index]
            items.append(
                {
                    "record_type": "session_digest",
                    "id": str(digest_row.get("id") or ""),
                    "scope": str(digest_row.get("scope") or ""),
                    "topic": str(digest_row.get("topic") or ""),
                    "summary": str(digest_row.get("summary") or ""),
                }
            )
            if len(items) >= DIRECT_LIMIT:
                break
        if index < len(records):
            record_row = records[index]
            items.append(
                {
                    "record_type": "indexed_record",
                    "id": str(record_row["id"] or ""),
                    "scope": str(record_row["scope"] or ""),
                    "type": str(record_row["type"] or ""),
                    "status": str(record_row["status"] or ""),
                    "text": str(record_row["text"] or ""),
                }
            )
            if len(items) >= DIRECT_LIMIT:
                break

    response = {
        "schema_version": SCHEMA,
        "benchmark_baseline": "direct-only-detail",
        "depth": "detail",
        "scope": "workspace:alpha",
        "budget_bytes": MAX_BYTES,
        "items": items,
        "returned_items": len(items),
    }
    if nbytes(response) > MAX_BYTES:
        raise RuntimeError("D2 direct-only benchmark baseline exceeded its byte budget")
    return response


def ids(response: Mapping[str, Any]) -> List[str]:
    result: List[str] = []
    for item in response.get("items") or []:
        if isinstance(item, Mapping):
            value = str(item.get("id") or "")
            if value and value not in result:
                result.append(value)
    return result


def relation_intent(mem, query: str) -> Set[str]:
    terms = {str(term).casefold() for term in mem.tokenize(query)}
    allowed: Set[str] = set()
    if terms & HISTORY_TERMS:
        allowed.update(HISTORY_RELATIONS)
    if terms & PROVENANCE_TERMS:
        allowed.update(PROVENANCE_RELATIONS)
    return allowed


def atomic_neighbor(
    mem,
    root: Path,
    mid: str,
    *,
    allow_historical: bool,
) -> Optional[Dict[str, Any]]:
    path = mem.locate_memory(mid, root, mem.MODE_NATIVE)
    if not path:
        return None
    meta, body = mem.parse_markdown(path)
    status = str(meta.get("status") or "active")
    if status != "active" and not allow_historical:
        return None
    if mem.normalize_scope(meta.get("scope"), root, mem.MODE_NATIVE) != "workspace:alpha":
        return None
    return {
        "record_type": "indexed_record",
        "id": mid,
        "type": str(meta.get("type") or ""),
        "scope": "workspace:alpha",
        "status": status,
        "text": body.strip(),
    }


def digest_neighbor(mem, root: Path, did: str) -> Optional[Dict[str, Any]]:
    try:
        row = mem.read_session_digest(
            did,
            scope="workspace:alpha",
            root=root,
            mode=mem.MODE_NATIVE,
        )
    except (FileNotFoundError, RuntimeError, ValueError):
        return None
    return {
        "record_type": "session_digest",
        "id": did,
        "scope": str(row.get("scope") or ""),
        "topic": str(row.get("topic") or ""),
        "summary": str(row.get("summary") or ""),
    }


def neighbors(
    mem,
    root: Path,
    response: Mapping[str, Any],
    query: str,
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    seeds = set(ids(response))
    allowed = relation_intent(mem, query)
    if not seeds or not allowed:
        return [], 0, sorted(allowed)

    edges = mem.list_relationships(
        workspace="alpha",
        limit=MAX_RELATIONS,
        root=root,
        mode=mem.MODE_NATIVE,
    )
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for edge in edges:
        relation = str(edge.get("relation_type") or "")
        if relation not in allowed:
            continue
        if str(edge.get("source_ref") or "") not in seeds:
            continue

        kind = str(edge.get("target_kind") or "")
        ref = str(edge.get("target_ref") or "")
        if not ref or ref in seeds or kind not in {"atomic_memory", "session_digest"}:
            continue

        key = (kind, ref)
        if key in found:
            continue

        if kind == "atomic_memory":
            item = atomic_neighbor(
                mem,
                root,
                ref,
                allow_historical=relation in HISTORY_RELATIONS,
            )
        else:
            item = digest_neighbor(mem, root, ref)
        if item is None:
            continue

        item["neighbor_relation"] = relation
        item["neighbor_direction"] = "outbound"
        item["edge_id"] = str(edge.get("edge_id") or "")
        found[key] = item

    ordered = [found[key] for key in sorted(found)]
    return ordered[:MAX_NEIGHBORS], len(edges), sorted(allowed)


def candidate(mem, root: Path, query: str) -> Dict[str, Any]:
    base = direct(mem, root, query)
    extra, scanned, intent = neighbors(mem, root, base, query)
    return {
        "direct": base,
        "neighbors": extra,
        "relationship_edges_scanned": scanned,
        "relation_intent": intent,
    }


def measured(fn):
    result = None
    times: List[int] = []
    for _ in range(SAMPLES):
        start = time.perf_counter_ns()
        result = fn()
        times.append(time.perf_counter_ns() - start)
    return result, times


def median_ms(times: Sequence[int]) -> float:
    return round(statistics.median(times) / 1_000_000.0, 3) if times else 0.0


def run_benchmark() -> Dict[str, Any]:
    mem = load_memory()
    with tempfile.TemporaryDirectory() as tmp:
        root = native_root(Path(tmp))
        fx = fixture(mem, root)
        mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)
        mem.rebuild_relationship_projection(root=root, mode=mem.MODE_NATIVE)
        before = canonical_fingerprint(root)

        rows = []
        base_times: List[int] = []
        cand_times: List[int] = []
        base_bytes = cand_bytes = neighbor_bytes = 0
        relevant = irrelevant = leakage = stale = 0

        for case in fx["cases"]:
            base, bt = measured(lambda q=case["query"]: direct(mem, root, q))
            cand, ct = measured(lambda q=case["query"]: candidate(mem, root, q))
            base_times += bt
            cand_times += ct

            base_ids = ids(base)
            direct_ids = ids(cand["direct"])
            neighbor_ids = [str(item.get("id") or "") for item in cand["neighbors"]]
            combined = set(direct_ids + neighbor_ids)
            expected = str(case["expected"])
            forbidden = set(case["forbidden"])
            base_ok = expected in base_ids and not forbidden.intersection(base_ids)
            cand_ok = expected in combined and not forbidden.intersection(combined)

            for nid in neighbor_ids:
                if nid in case["relevant"]:
                    relevant += 1
                else:
                    irrelevant += 1
                if nid in forbidden:
                    stale += 1
                if nid in fx["beta_ids"]:
                    leakage += 1
            if "BETA-PRIVATE-MARKER" in stable(cand):
                leakage += 1

            bsize = nbytes(base)
            nsize = nbytes(cand["neighbors"])
            csize = nbytes(cand["direct"]) + nsize
            base_bytes += bsize
            neighbor_bytes += nsize
            cand_bytes += csize

            rows.append(
                {
                    "name": case["name"],
                    "query": case["query"],
                    "expected_id": expected,
                    "baseline_correct": base_ok,
                    "candidate_correct": cand_ok,
                    "baseline_ids": base_ids,
                    "candidate_direct_ids": direct_ids,
                    "neighbor_ids": neighbor_ids,
                    "relation_intent": cand["relation_intent"],
                    "relationship_edges_scanned": cand["relationship_edges_scanned"],
                    "baseline_bytes": bsize,
                    "candidate_bytes": csize,
                    "neighbor_bytes": nsize,
                }
            )

        after = canonical_fingerprint(root)
        bcorrect = sum(1 for row in rows if row["baseline_correct"])
        ccorrect = sum(1 for row in rows if row["candidate_correct"])
        total = len(rows)
        gain = ccorrect - bcorrect
        count = relevant + irrelevant
        bmed = median_ms(base_times)
        cmed = median_ms(cand_times)

        return {
            "schema_version": SCHEMA,
            "benchmark_version": VERSION,
            "bounds": {
                "one_hop_only": True,
                "workspace": "alpha",
                "direct_limit": DIRECT_LIMIT,
                "max_neighbors_per_query": MAX_NEIGHBORS,
                "max_relationship_edges_scanned": MAX_RELATIONS,
                "detail_budget_bytes": MAX_BYTES,
                "query_intent_gated": True,
            },
            "baseline": {
                "correct_scenarios": bcorrect,
                "total_scenarios": total,
                "correctness": round(bcorrect / total, 6),
                "context_bytes": base_bytes,
                "median_latency_ms": bmed,
            },
            "candidate": {
                "correct_scenarios": ccorrect,
                "total_scenarios": total,
                "correctness": round(ccorrect / total, 6),
                "correctness_gain_scenarios": gain,
                "context_bytes": cand_bytes,
                "context_inflation_ratio": round(cand_bytes / base_bytes, 6),
                "neighbor_bytes": neighbor_bytes,
                "neighbors_returned": count,
                "relevant_neighbors": relevant,
                "irrelevant_neighbors": irrelevant,
                "irrelevant_neighbor_rate": (
                    round(irrelevant / count, 6) if count else 0.0
                ),
                "median_latency_ms": cmed,
                "latency_ratio": round(cmed / bmed, 6) if bmed else 1.0,
            },
            "safety": {
                "scope_leakage_count": leakage,
                "stale_neighbor_count": stale,
                "canonical_mutation": before != after,
            },
            "decision": "pending_evidence_review",
            "reason": (
                "D2 first captures a fair baseline/candidate comparison. The ship/reject "
                "decision is frozen only after reviewing measured correctness, context, "
                "latency, irrelevant-neighbor, and safety evidence."
            ),
            "scenarios": rows,
        }


def main() -> int:
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
