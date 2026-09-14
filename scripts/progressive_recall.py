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
from typing import Any, Dict, List, Optional, Sequence

PROGRESSIVE_RECALL_SCHEMA = 1
PROGRESSIVE_RECALL_VERSION = "memory.progressive-recall.v1"
SUPPORTED_DEPTHS = ("catalog", "summary", "detail")
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
        if depth == "source":
            raise ValueError(
                "source depth is reserved for the C2 exact-source extension and is not available yet"
            )
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
            "source_depth_available": False,
            "candidate_counts": {
                "session_digests": len(digests),
                "indexed_records": len(records),
            },
            "provenance": {
                "owner": "ai-verse-memory",
                "kind": "progressive_retrieval",
                "query_bound": True,
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
