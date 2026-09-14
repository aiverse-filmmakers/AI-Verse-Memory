"""Versioned bounded progressive retrieval for AI-Verse Memory.

This is an additive routing surface over established Memory owners:
- catalog -> B2 orientation map
- summary -> targeted session digests plus compact indexed-record excerpts
- detail -> bounded targeted digest/index detail

Canonical exact-source reads intentionally remain outside C1. C2 extends this same
API to source depth. Legacy recall() is not modified here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

PROGRESSIVE_RECALL_SCHEMA = 1
PROGRESSIVE_RECALL_VERSION = "memory.progressive-recall.v1"
SUPPORTED_DEPTHS = ("catalog", "summary", "detail", "source")
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
DEFAULT_MAX_BYTES = 16384
MIN_MAX_BYTES = 4096
MAX_MAX_BYTES = 65536
BUDGET_ENV = "AI_VERSE_PROGRESSIVE_RECALL_MAX_BYTES"
MAX_QUERY_CHARS = 4096
SUMMARY_EXCERPT_CHARS = 480
SUMMARY_DIGEST_CHARS = 1200
DETAIL_TEXT_CHARS = 2800
DETAIL_WHY_CHARS = 900
DETAIL_DIGEST_CHARS = 2200
MAX_DETAIL_LIST_ITEMS = 8
MAX_RELATION_NEIGHBORS = 4
MAX_RELATION_SCAN = 200

_HISTORY_INTENT_TERMS = frozenset({
    "before", "previous", "previously", "prior", "old", "older", "history",
    "historical", "corrected", "correction", "superseded", "supersedes", "replaced",
})
_PROVENANCE_INTENT_TERMS = frozenset({
    "source", "sources", "context", "evidence", "origin", "provenance",
    "session", "run", "incident", "derived", "why",
})
_HISTORY_RELATIONS = frozenset({"supersedes", "superseded_by"})
_PROVENANCE_RELATIONS = frozenset({"derived_from"})
SOURCE_WINDOW_MIN_CHARS = 256
SOURCE_WINDOW_MAX_CHARS = 12000


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _serialized_bytes(value: object) -> int:
    return len(_stable_json(value).encode("utf-8"))


def _truncate(value: object, limit: int) -> tuple[str, bool]:
    text = str(value or "")
    if len(text) <= limit:
        return text, False
    if limit <= 1:
        return text[:limit], True
    return text[: max(0, limit - 1)].rstrip() + "…", True


def _bounded_list(values: object, limit: int = MAX_DETAIL_LIST_ITEMS) -> tuple[List[Any], bool]:
    if not isinstance(values, list):
        return [], False
    return list(values[:limit]), len(values) > limit


def _resolve_budget(max_bytes: Optional[int]) -> int:
    raw = max_bytes
    if raw is None:
        env = os.getenv(BUDGET_ENV, "").strip()
        if env:
            try:
                raw = int(env)
            except ValueError as exc:
                raise ValueError(f"{BUDGET_ENV} must be an integer") from exc
        else:
            raw = DEFAULT_MAX_BYTES
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError("progressive recall max_bytes must be an integer")
    if raw < MIN_MAX_BYTES or raw > MAX_MAX_BYTES:
        raise ValueError(
            f"progressive recall max_bytes must be between {MIN_MAX_BYTES} and {MAX_MAX_BYTES}"
        )
    return raw


def _validate(
    *,
    version: str,
    depth: str,
    query: str,
    limit: int,
    max_bytes: Optional[int],
) -> tuple[str, str, int, int]:
    if version != PROGRESSIVE_RECALL_VERSION:
        raise ValueError(
            f"Unsupported progressive recall version: {version!r}; "
            f"expected {PROGRESSIVE_RECALL_VERSION!r}"
        )
    if depth not in SUPPORTED_DEPTHS:
        raise ValueError(f"Unsupported progressive recall depth: {depth!r}")
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must be at most {MAX_QUERY_CHARS} characters")
    if depth != "catalog" and not query:
        raise ValueError(f"{depth} depth requires a non-empty query")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
    return depth, query, limit, _resolve_budget(max_bytes)


def _target_scope(engine, root: Path, mode: str, scope: Optional[str], workspace: Optional[str]) -> str:
    scopes, primary = engine.allowed_scopes(
        root,
        mode,
        scope=scope,
        workspace=workspace,
        all_workspaces=False,
    )
    if primary:
        return str(primary)
    if scope:
        return engine.normalize_scope(scope, root, mode)
    if mode == engine.MODE_NATIVE:
        return "operator"
    return "global"


def _row_value(row, key: str, default: Any = "") -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _evidence_pointer(row) -> Dict[str, Any]:
    return {
        "path": str(_row_value(row, "path")),
        "source_identity": str(_row_value(row, "source_identity")),
        "source_version": str(_row_value(row, "source_version")),
        "freshness": str(_row_value(row, "freshness")),
    }


def _record_summary(row) -> Dict[str, Any]:
    excerpt, clipped = _truncate(_row_value(row, "text"), SUMMARY_EXCERPT_CHARS)
    item = {
        "record_type": "indexed_record",
        "id": str(_row_value(row, "id")),
        "kind": str(_row_value(row, "kind")),
        "type": str(_row_value(row, "type")),
        "scope": str(_row_value(row, "scope")),
        "excerpt": excerpt,
        "updated_at": str(_row_value(row, "updated_at") or _row_value(row, "created_at")),
        "evidence": _evidence_pointer(row),
        "deeper_evidence_available": bool(_row_value(row, "path")),
    }
    if clipped:
        item["content_truncated"] = True
    return item


def _record_detail(row) -> Dict[str, Any]:
    text, text_clipped = _truncate(_row_value(row, "text"), DETAIL_TEXT_CHARS)
    why, why_clipped = _truncate(_row_value(row, "why"), DETAIL_WHY_CHARS)
    item = {
        "record_type": "indexed_record",
        "id": str(_row_value(row, "id")),
        "kind": str(_row_value(row, "kind")),
        "type": str(_row_value(row, "type")),
        "scope": str(_row_value(row, "scope")),
        "status": str(_row_value(row, "status")),
        "importance": _row_value(row, "importance", 0),
        "confidence": _row_value(row, "confidence", 0),
        "updated_at": str(_row_value(row, "updated_at") or _row_value(row, "created_at")),
        "source": str(_row_value(row, "source")),
        "tags": str(_row_value(row, "tags")),
        "text": text,
        "why": why,
        "evidence": _evidence_pointer(row),
        "deeper_evidence_available": bool(_row_value(row, "path")),
    }
    if text_clipped or why_clipped:
        item["content_truncated"] = True
    return item


def _digest_summary(record: Dict[str, Any]) -> Dict[str, Any]:
    summary, clipped = _truncate(record.get("summary", ""), SUMMARY_DIGEST_CHARS)
    item = {
        "record_type": "session_digest",
        "id": str(record.get("id") or ""),
        "scope": str(record.get("scope") or ""),
        "session_id": str(record.get("session_id") or ""),
        "run_id": str(record.get("run_id") or ""),
        "topic": str(record.get("topic") or ""),
        "summary": summary,
        "completed_at": str(record.get("completed_at") or record.get("created_at") or ""),
        "evidence": {
            "path": str(record.get("path") or ""),
            "canonical_version": str(record.get("canonical_version") or ""),
            "digest_fingerprint": str(record.get("digest_fingerprint") or ""),
            "source_fingerprint": str(record.get("source_fingerprint") or ""),
        },
        "deeper_evidence_available": bool(
            record.get("path") or record.get("source_refs") or record.get("source_coverage")
        ),
    }
    if clipped:
        item["content_truncated"] = True
    return item


def _digest_detail(record: Dict[str, Any]) -> Dict[str, Any]:
    summary, summary_clipped = _truncate(record.get("summary", ""), DETAIL_DIGEST_CHARS)
    outcomes, outcomes_clipped = _bounded_list(record.get("significant_outcomes"))
    unresolved, unresolved_clipped = _bounded_list(record.get("unresolved_items"))
    refs, refs_clipped = _bounded_list(record.get("source_refs"))
    coverage, coverage_clipped = _bounded_list(record.get("source_coverage"))
    item = {
        "record_type": "session_digest",
        "id": str(record.get("id") or ""),
        "scope": str(record.get("scope") or ""),
        "session_id": str(record.get("session_id") or ""),
        "run_id": str(record.get("run_id") or ""),
        "topic": str(record.get("topic") or ""),
        "summary": summary,
        "significant_outcomes": outcomes,
        "unresolved_items": unresolved,
        "completed_at": str(record.get("completed_at") or record.get("created_at") or ""),
        "provenance": record.get("provenance") if isinstance(record.get("provenance"), dict) else {},
        "evidence": {
            "path": str(record.get("path") or ""),
            "source_refs": refs,
            "source_coverage": coverage,
            "source_version": str(record.get("source_version") or ""),
            "source_fingerprint": str(record.get("source_fingerprint") or ""),
            "canonical_version": str(record.get("canonical_version") or ""),
            "digest_fingerprint": str(record.get("digest_fingerprint") or ""),
        },
        "deeper_evidence_available": bool(
            record.get("path") or record.get("source_refs") or record.get("source_coverage")
        ),
    }
    if summary_clipped or outcomes_clipped or unresolved_clipped or refs_clipped or coverage_clipped:
        item["content_truncated"] = True
    return item


def _interleave(
    digests: Sequence[Dict[str, Any]],
    records: Sequence[Any],
    *,
    depth: str,
    limit: int,
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    count = max(len(digests), len(records))
    for index in range(count):
        if index < len(digests):
            result.append(
                _digest_summary(digests[index])
                if depth == "summary"
                else _digest_detail(digests[index])
            )
            if len(result) >= limit:
                break
        if index < len(records):
            result.append(
                _record_summary(records[index])
                if depth == "summary"
                else _record_detail(records[index])
            )
            if len(result) >= limit:
                break
    return result



def _relationship_intent(engine, query: str) -> List[str]:
    terms = {str(term).casefold() for term in engine.tokenize(query)}
    relations = set()
    if terms & _HISTORY_INTENT_TERMS:
        relations.update(_HISTORY_RELATIONS)
    if terms & _PROVENANCE_INTENT_TERMS:
        relations.update(_PROVENANCE_RELATIONS)
    return sorted(relations)


def _indexed_relationship_detail(
    engine,
    *,
    record_id: str,
    expected_scope: str,
    root: Path,
    mode: str,
) -> Optional[Dict[str, Any]]:
    conn, fts = engine.connect_db(root, mode)
    try:
        engine._purge_invalid_indexed_sources(conn, fts, root, mode)
        if mode == engine.MODE_NATIVE:
            engine._refresh_native_canonical_sources(conn, fts, root, mode)
        engine._ensure_historical_source_state(conn, root, mode)
        row = conn.execute(
            """
            SELECT i.*, s.source_identity, s.source_version, s.freshness, s.indexed_at
            FROM items i
            LEFT JOIN source_state s ON s.item_id=i.id
            WHERE i.id=? AND i.scope=?
            LIMIT 1
            """,
            (record_id, expected_scope),
        ).fetchone()
        if row is None or not engine._indexed_source_is_valid(row, root, mode):
            return None
        return _record_detail(row)
    finally:
        conn.close()


def _relationship_neighbors(
    engine,
    *,
    items: Sequence[Dict[str, Any]],
    relation_types: Sequence[str],
    scope: Optional[str],
    workspace: Optional[str],
    root: Path,
    mode: str,
    limit: int,
) -> List[Dict[str, Any]]:
    if not relation_types or limit <= 0:
        return []

    seeds = {
        str(item.get("id") or "")
        for item in items
        if item.get("record_type") == "indexed_record" and item.get("id")
    }
    if not seeds:
        return []

    edges = engine.list_relationships(
        scope=scope,
        workspace=workspace,
        limit=MAX_RELATION_SCAN,
        root=root,
        mode=mode,
    )
    wanted_relations = set(relation_types)
    existing = {
        (str(item.get("record_type") or ""), str(item.get("id") or ""))
        for item in items
    }
    neighbors: List[Dict[str, Any]] = []

    for edge in edges:
        relation = str(edge.get("relation_type") or "")
        source_ref = str(edge.get("source_ref") or "")
        if relation not in wanted_relations or source_ref not in seeds:
            continue

        target_kind = str(edge.get("target_kind") or "")
        target_ref = str(edge.get("target_ref") or "")
        target_scope = str(edge.get("target_scope") or edge.get("scope") or "")
        if not target_ref or not target_scope:
            continue

        neighbor: Optional[Dict[str, Any]] = None
        if target_kind == "atomic_memory" and relation in _HISTORY_RELATIONS:
            neighbor = _indexed_relationship_detail(
                engine,
                record_id=target_ref,
                expected_scope=target_scope,
                root=root,
                mode=mode,
            )
        elif target_kind == "session_digest" and relation in _PROVENANCE_RELATIONS:
            try:
                record = engine.read_session_digest(
                    target_ref,
                    scope=target_scope,
                    root=root,
                    mode=mode,
                )
            except (FileNotFoundError, RuntimeError, ValueError):
                continue
            if str(record.get("scope") or "") != target_scope:
                continue
            neighbor = _digest_detail(record)

        if neighbor is None:
            continue

        key = (str(neighbor.get("record_type") or ""), str(neighbor.get("id") or ""))
        if key in existing:
            continue

        neighbor["relationship_neighbor"] = True
        neighbor["relationship"] = {
            "edge_id": str(edge.get("edge_id") or ""),
            "relation_type": relation,
            "source_ref": source_ref,
            "target_ref": target_ref,
            "one_hop_only": True,
        }
        neighbors.append(neighbor)
        existing.add(key)
        if len(neighbors) >= limit:
            break

    return neighbors


def _item_shell(item: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "record_type",
        "id",
        "kind",
        "type",
        "scope",
        "session_id",
        "run_id",
        "topic",
        "updated_at",
        "completed_at",
        "evidence",
        "deeper_evidence_available",
    )
    shell = {key: item[key] for key in keep if key in item}
    shell["content_omitted_for_budget"] = True
    return shell


def _append_with_budget(
    response: Dict[str, Any],
    items: Sequence[Dict[str, Any]],
    max_bytes: int,
    *,
    total_candidates: int,
) -> Dict[str, Any]:
    response["items"] = []
    truncated = False
    for item in items:
        candidate = dict(response)
        candidate["items"] = list(response["items"]) + [item]
        if _serialized_bytes(candidate) <= max_bytes:
            response["items"].append(item)
            if item.get("content_truncated"):
                truncated = True
            continue

        shell = _item_shell(item)
        candidate["items"] = list(response["items"]) + [shell]
        if _serialized_bytes(candidate) <= max_bytes:
            response["items"].append(shell)
        truncated = True
        break

    if len(response["items"]) < total_candidates:
        truncated = True
    response["truncated"] = truncated
    response["returned_items"] = len(response["items"])
    if _serialized_bytes(response) > max_bytes:
        raise ValueError(
            f"progressive recall core response exceeds configured budget {max_bytes}"
        )
    return response


def _authorized_scope(
    engine,
    *,
    requested_scope: Optional[str],
    workspace: Optional[str],
    evidence_scope: str,
    root: Path,
    mode: str,
) -> str:
    normalized_evidence = engine.normalize_scope(evidence_scope, root, mode)
    visible, primary = engine.allowed_scopes(
        root,
        mode,
        scope=requested_scope,
        workspace=workspace,
        all_workspaces=False,
    )
    if visible is not None and normalized_evidence not in visible:
        raise ValueError(
            f"Exact-source evidence scope {normalized_evidence} is not authorized for this request"
        )
    return str(primary or normalized_evidence)


def _normalize_evidence_ref(value: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if value is None or not isinstance(value, Mapping):
        raise ValueError("source depth requires evidence_ref from a prior detail item")
    record_type = str(value.get("record_type") or "").strip()
    record_id = str(value.get("id") or "").strip()
    scope = str(value.get("scope") or "").strip()
    evidence = value.get("evidence")
    if record_type not in {"indexed_record", "session_digest"}:
        raise ValueError("evidence_ref record_type must be indexed_record or session_digest")
    if not record_id:
        raise ValueError("evidence_ref requires id")
    if not scope:
        raise ValueError("evidence_ref requires scope")
    if not isinstance(evidence, Mapping):
        raise ValueError("evidence_ref requires an evidence object")
    return {
        "record_type": record_type,
        "id": record_id,
        "scope": scope,
        "evidence": dict(evidence),
    }


def _source_failure(
    *,
    scope: str,
    budget: int,
    record_type: str,
    record_id: str,
    status: str,
    reason: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    response = {
        "schema_version": PROGRESSIVE_RECALL_SCHEMA,
        "api_version": PROGRESSIVE_RECALL_VERSION,
        "depth": "source",
        "scope": scope,
        "budget_bytes": budget,
        "status": status,
        "reason": reason,
        "exact_evidence": False,
        "source_depth_available": True,
        "record_type": record_type,
        "id": record_id,
        "provenance": {
            "owner": "ai-verse-memory",
            "kind": "exact_source_validation",
            "scope_revalidated": True,
            "content_returned": False,
        },
    }
    if evidence:
        response["evidence"] = dict(evidence)
    if _serialized_bytes(response) > budget:
        raise ValueError(f"exact-source failure response exceeds configured budget {budget}")
    return response


def _resolved_index_path(engine, row, root: Path, mode: str) -> Path:
    stored = Path(str(_row_value(row, "path")))
    if mode == engine.MODE_NATIVE:
        if stored.is_absolute() or not stored.parts:
            raise ValueError("Indexed native source path is not safely relative")
        source = root / stored
        if not engine._indexed_source_is_valid(row, root, mode):
            raise ValueError("Indexed native source failed containment or scope validation")
        return source.resolve(strict=True)

    source = stored if stored.is_absolute() else root / stored
    resolved = source.resolve(strict=True)
    home = engine.paths(root, mode)["home"].resolve(strict=True)
    try:
        resolved.relative_to(home)
    except ValueError as exc:
        raise ValueError("Standalone indexed source resolves outside Memory home") from exc
    if not resolved.is_file():
        raise ValueError("Standalone indexed source is not a regular file")
    return resolved


def _source_window(engine, text: str, query: str, max_chars: int) -> Dict[str, Any]:
    if max_chars < SOURCE_WINDOW_MIN_CHARS:
        max_chars = SOURCE_WINDOW_MIN_CHARS
    max_chars = min(SOURCE_WINDOW_MAX_CHARS, max_chars)
    total = len(text)
    if total <= max_chars:
        start = 0
        stop = total
        matched = True if query and query.casefold() in text.casefold() else False
    else:
        lowered = text.casefold()
        query_lower = query.casefold().strip()
        hit = lowered.find(query_lower) if query_lower else -1
        if hit < 0:
            terms = sorted(
                {term for term in engine.tokenize(query) if len(term) >= 2},
                key=len,
                reverse=True,
            )
            for term in terms:
                hit = lowered.find(term.casefold())
                if hit >= 0:
                    break
        matched = hit >= 0
        if hit < 0:
            hit = 0
        start = max(0, hit - max_chars // 3)
        stop = min(total, start + max_chars)
        if stop - start < max_chars:
            start = max(0, stop - max_chars)

    content = text[start:stop]
    start_line = text.count("\n", 0, start) + 1
    end_line = start_line + content.count("\n")
    return {
        "encoding": "utf-8",
        "content": content,
        "query_match": matched,
        "window_start_char": start,
        "window_end_char": stop,
        "total_chars": total,
        "start_line": start_line,
        "end_line": end_line,
        "content_truncated": start > 0 or stop < total,
    }


def _fit_exact_source_response(
    engine,
    *,
    base: Dict[str, Any],
    text: str,
    query: str,
    budget: int,
) -> Dict[str, Any]:
    max_chars = min(SOURCE_WINDOW_MAX_CHARS, max(SOURCE_WINDOW_MIN_CHARS, budget - 1800))
    while True:
        response = dict(base)
        response["source"] = _source_window(engine, text, query, max_chars)
        if _serialized_bytes(response) <= budget:
            return response
        if max_chars <= SOURCE_WINDOW_MIN_CHARS:
            break
        max_chars = max(SOURCE_WINDOW_MIN_CHARS, int(max_chars * 0.72))
    raise ValueError(f"exact-source response cannot fit configured budget {budget}")


def _indexed_exact_source(
    engine,
    *,
    evidence_ref: Mapping[str, Any],
    query: str,
    requested_scope: Optional[str],
    workspace: Optional[str],
    root: Path,
    mode: str,
    budget: int,
) -> Dict[str, Any]:
    record_id = str(evidence_ref["id"])
    evidence_scope = str(evidence_ref["scope"])
    target_scope = _authorized_scope(
        engine,
        requested_scope=requested_scope,
        workspace=workspace,
        evidence_scope=evidence_scope,
        root=root,
        mode=mode,
    )
    expected = evidence_ref["evidence"]
    expected_path = str(expected.get("path") or "")
    expected_identity = str(expected.get("source_identity") or "")
    expected_version = str(expected.get("source_version") or "")
    if not expected_path or not expected_version:
        raise ValueError("indexed_record source descent requires path and source_version")

    p = engine.ensure_layout(root, mode)
    if not p["db"].exists():
        engine.rebuild(silent=True, root=root, mode=mode)
    conn, fts = engine.connect_db(root, mode)
    try:
        engine._purge_invalid_indexed_sources(conn, fts, root, mode)
        if mode == engine.MODE_NATIVE:
            engine._refresh_native_canonical_sources(conn, fts, root, mode)
        engine._ensure_historical_source_state(conn, root, mode)
        row = conn.execute(
            """
            SELECT i.*, s.source_identity, s.source_version, s.freshness, s.indexed_at
            FROM items i
            LEFT JOIN source_state s ON s.item_id=i.id
            WHERE i.id=?
            """,
            (record_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="indexed_record",
            record_id=record_id,
            status="unavailable",
            reason="source_missing_or_no_longer_indexed",
            evidence={"path": expected_path, "expected_source_version": expected_version},
        )

    row_scope = str(_row_value(row, "scope"))
    if engine.normalize_scope(row_scope, root, mode) != engine.normalize_scope(evidence_scope, root, mode):
        raise ValueError("Exact-source record scope no longer matches evidence_ref")
    row_path = str(_row_value(row, "path"))
    if row_path != expected_path:
        raise ValueError("Exact-source record path does not match evidence_ref")
    current_identity = str(_row_value(row, "source_identity"))
    if expected_identity and current_identity != expected_identity:
        raise ValueError("Exact-source identity does not match evidence_ref")

    try:
        source_path = _resolved_index_path(engine, row, root, mode)
        current_version = engine._canonical_source_version(source_path, root, row, mode)
    except (FileNotFoundError, OSError, ValueError):
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="indexed_record",
            record_id=record_id,
            status="unavailable",
            reason="source_failed_containment_or_read_validation",
            evidence={"path": expected_path, "expected_source_version": expected_version},
        )

    if current_version != expected_version:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="indexed_record",
            record_id=record_id,
            status="stale",
            reason="source_version_mismatch",
            evidence={
                "path": row_path,
                "source_identity": current_identity,
                "expected_source_version": expected_version,
                "current_source_version": current_version,
            },
        )

    try:
        raw = source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="indexed_record",
            record_id=record_id,
            status="unavailable",
            reason="source_read_failed",
            evidence={"path": row_path, "source_version": current_version},
        )

    base = {
        "schema_version": PROGRESSIVE_RECALL_SCHEMA,
        "api_version": PROGRESSIVE_RECALL_VERSION,
        "depth": "source",
        "scope": target_scope,
        "budget_bytes": budget,
        "status": "ok",
        "reason": None,
        "exact_evidence": True,
        "source_depth_available": True,
        "record_type": "indexed_record",
        "id": record_id,
        "kind": str(_row_value(row, "kind")),
        "record_scope": row_scope,
        "evidence": {
            "path": row_path,
            "source_identity": current_identity,
            "source_version": current_version,
            "freshness": "current",
        },
        "provenance": {
            "owner": "ai-verse-memory",
            "kind": "exact_canonical_source",
            "scope_revalidated": True,
            "containment_revalidated": True,
            "version_revalidated": True,
            "content_returned": True,
        },
    }
    return _fit_exact_source_response(
        engine,
        base=base,
        text=raw,
        query=query,
        budget=budget,
    )


def _digest_exact_source(
    engine,
    *,
    evidence_ref: Mapping[str, Any],
    requested_scope: Optional[str],
    workspace: Optional[str],
    root: Path,
    mode: str,
    budget: int,
) -> Dict[str, Any]:
    record_id = str(evidence_ref["id"])
    evidence_scope = str(evidence_ref["scope"])
    target_scope = _authorized_scope(
        engine,
        requested_scope=requested_scope,
        workspace=workspace,
        evidence_scope=evidence_scope,
        root=root,
        mode=mode,
    )
    expected = evidence_ref["evidence"]
    expected_path = str(expected.get("path") or "")
    expected_version = str(expected.get("canonical_version") or "")
    expected_digest_fingerprint = str(expected.get("digest_fingerprint") or "")
    if not expected_path or not expected_version:
        raise ValueError("session_digest source descent requires path and canonical_version")

    try:
        record = engine.read_session_digest(
            record_id,
            scope=evidence_scope,
            root=root,
            mode=mode,
        )
    except FileNotFoundError:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="unavailable",
            reason="canonical_digest_missing",
            evidence={"path": expected_path, "expected_canonical_version": expected_version},
        )
    except (RuntimeError, ValueError, OSError):
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="unavailable",
            reason="canonical_digest_failed_containment_or_scope_validation",
            evidence={"path": expected_path, "expected_canonical_version": expected_version},
        )

    current_path = str(record.get("path") or "")
    if current_path != expected_path:
        raise ValueError("Session-digest canonical path does not match evidence_ref")
    path = Path(current_path)
    if mode == engine.MODE_NATIVE:
        if path.is_absolute():
            raise ValueError("Native session-digest evidence path must be relative")
        path = root / path
    try:
        current_version = engine._source_version(path.resolve(strict=True))
    except (FileNotFoundError, OSError, ValueError):
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="unavailable",
            reason="canonical_digest_read_failed",
            evidence={"path": expected_path, "expected_canonical_version": expected_version},
        )

    if current_version != expected_version:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="stale",
            reason="canonical_digest_version_mismatch",
            evidence={
                "path": current_path,
                "expected_canonical_version": expected_version,
                "current_canonical_version": current_version,
            },
        )
    current_digest_fingerprint = str(record.get("digest_fingerprint") or "")
    if expected_digest_fingerprint and current_digest_fingerprint != expected_digest_fingerprint:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="stale",
            reason="digest_fingerprint_mismatch",
            evidence={
                "path": current_path,
                "canonical_version": current_version,
                "expected_digest_fingerprint": expected_digest_fingerprint,
                "current_digest_fingerprint": current_digest_fingerprint,
            },
        )

    refs = record.get("source_refs") if isinstance(record.get("source_refs"), list) else []
    coverage = record.get("source_coverage") if isinstance(record.get("source_coverage"), list) else []
    if not refs:
        return _source_failure(
            scope=target_scope,
            budget=budget,
            record_type="session_digest",
            record_id=record_id,
            status="unavailable",
            reason="original_source_not_available",
            evidence={
                "path": current_path,
                "canonical_version": current_version,
                "digest_fingerprint": current_digest_fingerprint,
            },
        )

    response = {
        "schema_version": PROGRESSIVE_RECALL_SCHEMA,
        "api_version": PROGRESSIVE_RECALL_VERSION,
        "depth": "source",
        "scope": target_scope,
        "budget_bytes": budget,
        "status": "external_source_required",
        "reason": "session_digest_is_navigation_not_original_transcript_evidence",
        "exact_evidence": False,
        "source_depth_available": True,
        "record_type": "session_digest",
        "id": record_id,
        "record_scope": evidence_scope,
        "evidence": {
            "path": current_path,
            "canonical_version": current_version,
            "digest_fingerprint": current_digest_fingerprint,
            "source_fingerprint": str(record.get("source_fingerprint") or ""),
            "source_version": str(record.get("source_version") or ""),
            "external_source_refs": list(refs[:MAX_DETAIL_LIST_ITEMS]),
            "source_coverage": list(coverage[:MAX_DETAIL_LIST_ITEMS]),
        },
        "provenance": {
            "owner": "ai-verse-memory",
            "kind": "validated_digest_source_pointer",
            "scope_revalidated": True,
            "containment_revalidated": True,
            "version_revalidated": True,
            "content_returned": False,
            "external_owner_required": True,
        },
    }
    if _serialized_bytes(response) > budget:
        response["evidence"]["external_source_refs"] = response["evidence"]["external_source_refs"][:2]
        response["evidence"]["source_coverage"] = response["evidence"]["source_coverage"][:2]
    if _serialized_bytes(response) > budget:
        raise ValueError(f"session-digest source pointer response exceeds configured budget {budget}")
    return response


def _exact_source_response(
    engine,
    *,
    evidence_ref: Optional[Mapping[str, Any]],
    query: str,
    requested_scope: Optional[str],
    workspace: Optional[str],
    root: Path,
    mode: str,
    budget: int,
) -> Dict[str, Any]:
    normalized = _normalize_evidence_ref(evidence_ref)
    if normalized["record_type"] == "indexed_record":
        return _indexed_exact_source(
            engine,
            evidence_ref=normalized,
            query=query,
            requested_scope=requested_scope,
            workspace=workspace,
            root=root,
            mode=mode,
            budget=budget,
        )
    return _digest_exact_source(
        engine,
        evidence_ref=normalized,
        requested_scope=requested_scope,
        workspace=workspace,
        root=root,
        mode=mode,
        budget=budget,
    )


def _catalog_response(
    engine,
    *,
    scope: Optional[str],
    workspace: Optional[str],
    root: Path,
    mode: str,
    max_bytes: int,
) -> Dict[str, Any]:
    # Reserve envelope space and let B2 perform its own deterministic catalog
    # truncation. The supported minima leave enough room for the v1 envelope.
    reserve = 900
    catalog_budget = max(
        int(engine.ORIENTATION_MAP_MIN_MAX_BYTES),
        min(
            int(engine.ORIENTATION_MAP_MAX_MAX_BYTES),
            max_bytes - reserve,
        ),
    )
    while True:
        catalog = engine.get_orientation_map(
            scope=scope,
            workspace=workspace,
            root=root,
            mode=mode,
            max_bytes=catalog_budget,
        )
        response = {
            "schema_version": PROGRESSIVE_RECALL_SCHEMA,
            "api_version": PROGRESSIVE_RECALL_VERSION,
            "depth": "catalog",
            "scope": catalog["scope"],
            "budget_bytes": max_bytes,
            "truncated": bool(catalog.get("truncated")),
            "deeper_evidence_available": bool(
                catalog["counts"]["atomic_memory"]
                or catalog["counts"]["indexed_sources"]
                or catalog["counts"]["session_digests"]
            ),
            "next_depth": "summary",
            "source_depth_available": False,
            "catalog": catalog,
            "provenance": {
                "owner": "ai-verse-memory",
                "kind": "derived_orientation",
                "source_fingerprint": catalog["source_fingerprint"],
            },
        }
        if _serialized_bytes(response) <= max_bytes:
            return response
        if catalog_budget <= int(engine.ORIENTATION_MAP_MIN_MAX_BYTES):
            raise ValueError(
                f"progressive catalog response cannot fit configured budget {max_bytes}"
            )
        catalog_budget = max(
            int(engine.ORIENTATION_MAP_MIN_MAX_BYTES),
            catalog_budget - 512,
        )


def apply(engine) -> None:
    required = (
        "get_orientation_map",
        "recall_session_digests",
        "recall",
        "allowed_scopes",
        "normalize_scope",
        "ORIENTATION_MAP_MIN_MAX_BYTES",
        "ORIENTATION_MAP_MAX_MAX_BYTES",
        "connect_db",
        "_purge_invalid_indexed_sources",
        "_refresh_native_canonical_sources",
        "_ensure_historical_source_state",
        "_indexed_source_is_valid",
        "_canonical_source_version",
        "_source_version",
        "paths",
        "read_session_digest",
        "list_relationships",
        "tokenize",
    )
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError(
            "Progressive recall requires established Memory retrieval surfaces: "
            + ", ".join(missing)
        )

    def progressive_recall(
        query: str = "",
        *,
        version: str = PROGRESSIVE_RECALL_VERSION,
        depth: str = "catalog",
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = DEFAULT_LIMIT,
        max_bytes: Optional[int] = None,
        evidence_ref: Optional[Mapping[str, Any]] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        depth_value, query_value, limit_value, budget = _validate(
            version=version,
            depth=depth,
            query=query,
            limit=limit,
            max_bytes=max_bytes,
        )
        resolved_root = Path(root or engine.repository_root()).resolve()
        resolved_mode = mode or engine.detect_mode(resolved_root)

        if depth_value == "source":
            return _exact_source_response(
                engine,
                evidence_ref=evidence_ref,
                query=query_value,
                requested_scope=scope,
                workspace=workspace,
                root=resolved_root,
                mode=resolved_mode,
                budget=budget,
            )

        if evidence_ref is not None:
            raise ValueError("evidence_ref is only valid for source depth")

        if depth_value == "catalog":
            return _catalog_response(
                engine,
                scope=scope,
                workspace=workspace,
                root=resolved_root,
                mode=resolved_mode,
                max_bytes=budget,
            )

        target_scope = _target_scope(
            engine,
            resolved_root,
            resolved_mode,
            scope,
            workspace,
        )
        digests = engine.recall_session_digests(
            query_value,
            scope=scope,
            workspace=workspace,
            limit=limit_value,
            root=resolved_root,
            mode=resolved_mode,
        )
        records = engine.recall(
            query_value,
            scope=scope,
            workspace=workspace,
            limit=limit_value,
            include_history=False,
            root=resolved_root,
            mode=resolved_mode,
            all_workspaces=False,
        )
        items = _interleave(
            digests,
            records,
            depth=depth_value,
            limit=limit_value,
        )
        relationship_types = (
            _relationship_intent(engine, query_value)
            if depth_value == "detail"
            else []
        )
        relationship_neighbors: List[Dict[str, Any]] = []
        if relationship_types and len(items) < limit_value:
            relationship_neighbors = _relationship_neighbors(
                engine,
                items=items,
                relation_types=relationship_types,
                scope=scope,
                workspace=workspace,
                root=resolved_root,
                mode=resolved_mode,
                limit=min(MAX_RELATION_NEIGHBORS, limit_value - len(items)),
            )
            items.extend(relationship_neighbors)
        deeper = any(bool(item.get("deeper_evidence_available")) for item in items)
        response = {
            "schema_version": PROGRESSIVE_RECALL_SCHEMA,
            "api_version": PROGRESSIVE_RECALL_VERSION,
            "depth": depth_value,
            "scope": target_scope,
            "budget_bytes": budget,
            "deeper_evidence_available": deeper,
            "next_depth": "detail" if depth_value == "summary" and items else (
                "source" if depth_value == "detail" and deeper else None
            ),
            "source_depth_available": bool(depth_value == "detail" and deeper),
            "candidate_counts": {
                "session_digests": len(digests),
                "indexed_records": len(records),
                "relationship_neighbors": len(relationship_neighbors),
            },
            "provenance": {
                "owner": "ai-verse-memory",
                "kind": "progressive_retrieval",
                "query_bound": True,
                "relationship_expansion": {
                    "enabled": bool(relationship_types),
                    "relations": relationship_types,
                    "one_hop_only": True,
                    "max_neighbors": MAX_RELATION_NEIGHBORS,
                    "neighbors_added": len(relationship_neighbors),
                },
            },
        }
        return _append_with_budget(
            response,
            items,
            budget,
            total_candidates=len(items),
        )

    engine.progressive_recall = progressive_recall
    engine.PROGRESSIVE_RECALL_SCHEMA = PROGRESSIVE_RECALL_SCHEMA
    engine.PROGRESSIVE_RECALL_VERSION = PROGRESSIVE_RECALL_VERSION
    engine.PROGRESSIVE_RECALL_SUPPORTED_DEPTHS = SUPPORTED_DEPTHS
    engine.PROGRESSIVE_RECALL_DEFAULT_MAX_BYTES = DEFAULT_MAX_BYTES
    engine.PROGRESSIVE_RECALL_MIN_MAX_BYTES = MIN_MAX_BYTES
    engine.PROGRESSIVE_RECALL_MAX_MAX_BYTES = MAX_MAX_BYTES
    engine.PROGRESSIVE_RECALL_MAX_RELATION_NEIGHBORS = MAX_RELATION_NEIGHBORS
    engine.PROGRESSIVE_RECALL_MAX_RELATION_SCAN = MAX_RELATION_SCAN
