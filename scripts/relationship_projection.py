"""Deterministic rebuildable relationship projection for AI-Verse Memory.

D1 deliberately projects only explicit canonical metadata/provenance:
- atomic Memory supersedes / superseded_by links;
- atomic evidence_refs and session-digest source bindings;
- session-digest source_refs / source_coverage;
- session-digest session identity.

The projection is disposable SQLite state.  It contains no canonical fact text
and performs no semantic inference or neighbor expansion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

RELATIONSHIP_SCHEMA = 1
MAX_RELATION_LIMIT = 200
MAX_REFERENCE_CHARS = 4096
_DIGEST_REF_PREFIX = "memory:session-digest:"
_ALLOWED_RELATION_TYPES = {
    "supersedes",
    "superseded_by",
    "derived_from",
    "same_session",
}


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_ref(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_REFERENCE_CHARS:
        return ""
    return normalized


def _json_string_list(raw: object) -> List[str]:
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        ref = _safe_ref(item)
        if ref and ref not in result:
            result.append(ref)
    return result


def _json_object(raw: object) -> Dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_relationships (
            edge_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            scope TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_ref TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_version TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            target_scope TEXT,
            target_path TEXT,
            target_version TEXT,
            evidence_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_relationship_scope "
        "ON memory_relationships(scope, relation_type, source_ref)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memory_relationship_target "
        "ON memory_relationships(scope, target_ref, relation_type)"
    )
    conn.commit()


def _edge_key(edge: Mapping[str, Any]) -> Tuple[str, str, str, str, str, str]:
    return (
        str(edge["scope"]),
        str(edge["relation_type"]),
        str(edge["source_kind"]),
        str(edge["source_ref"]),
        str(edge["target_kind"]),
        str(edge["target_ref"]),
    )


def _edge_id(key: Sequence[str]) -> str:
    return "rel-" + hashlib.sha256(
        ("\n".join([str(RELATIONSHIP_SCHEMA), *key])).encode("utf-8")
    ).hexdigest()[:40]


def _add_edge(
    edges: Dict[Tuple[str, str, str, str, str, str], Dict[str, Any]],
    *,
    scope: str,
    relation_type: str,
    source_kind: str,
    source_ref: str,
    source_path: str,
    source_version: str,
    target_kind: str,
    target_ref: str,
    target_scope: str = "",
    target_path: str = "",
    target_version: str = "",
    evidence: Mapping[str, Any],
) -> None:
    if relation_type not in _ALLOWED_RELATION_TYPES:
        raise ValueError(f"unsupported relationship type: {relation_type}")
    source_ref = _safe_ref(source_ref)
    target_ref = _safe_ref(target_ref)
    if not source_ref or not target_ref:
        return

    edge = {
        "scope": scope,
        "relation_type": relation_type,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "source_path": source_path,
        "source_version": source_version,
        "target_kind": target_kind,
        "target_ref": target_ref,
        "target_scope": target_scope,
        "target_path": target_path,
        "target_version": target_version,
    }
    key = _edge_key(edge)
    descriptor = dict(evidence)
    previous = edges.get(key)
    if previous is None:
        edge["evidence"] = [descriptor]
        edges[key] = edge
        return

    evidence_rows = list(previous["evidence"])
    if descriptor not in evidence_rows:
        evidence_rows.append(descriptor)
        evidence_rows.sort(key=_stable_json)
        previous["evidence"] = evidence_rows

    # Canonical target metadata is deterministic for one rebuild.  Prefer the
    # non-empty validated values if multiple explicit fields point to the same
    # target.
    for field in ("target_scope", "target_path", "target_version"):
        if not previous.get(field) and edge.get(field):
            previous[field] = edge[field]


def _atomic_records(engine, root: Path, mode: str) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    for path in engine.iter_atomic_files(root=root, mode=mode):
        try:
            meta, _ = engine.parse_markdown(path)
            record_id = _safe_ref(meta.get("id"))
            if not record_id:
                continue
            scope = engine._validated_atomic_scope(path, root, mode, meta)
            version = engine._source_version(path)
            records[record_id] = {
                "id": record_id,
                "scope": scope,
                "path": engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path),
                "version": version,
                "meta": dict(meta),
            }
        except (ValueError, OSError):
            continue
    return records


def _digest_records(engine, root: Path, mode: str) -> Dict[str, Dict[str, Any]]:
    # The existing digest refresh is itself rebuildable and validates canonical
    # digest path/scope/version before rows become visible here.
    engine.refresh_session_digest_index(root=root, mode=mode)
    conn, _ = engine.connect_db(root, mode)
    try:
        rows = conn.execute(
            """
            SELECT id, path, scope, session_id, run_id, source_refs,
                   source_coverage, provenance, source_fingerprint,
                   source_version, digest_fingerprint, canonical_version
            FROM session_digest_items
            ORDER BY scope, id
            """
        ).fetchall()
    finally:
        conn.close()

    records: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        digest_id = _safe_ref(row["id"])
        scope = _safe_ref(row["scope"])
        if not digest_id or not scope:
            continue
        try:
            normalized_scope = engine.normalize_scope(scope, root, mode)
        except ValueError:
            continue
        if normalized_scope != scope:
            continue
        records[digest_id] = {
            "id": digest_id,
            "scope": scope,
            "path": str(row["path"] or ""),
            "version": str(row["canonical_version"] or ""),
            "session_id": _safe_ref(row["session_id"]),
            "run_id": _safe_ref(row["run_id"]),
            "source_refs": _json_string_list(row["source_refs"]),
            "source_coverage": _json_string_list(row["source_coverage"]),
            "provenance": _json_object(row["provenance"]),
            "source_fingerprint": str(row["source_fingerprint"] or ""),
            "source_version": str(row["source_version"] or ""),
            "digest_fingerprint": str(row["digest_fingerprint"] or ""),
        }
    return records


def _canonical_target(
    target: Optional[Mapping[str, Any]],
    expected_scope: str,
) -> Optional[Tuple[str, str, str]]:
    if target is None or str(target.get("scope") or "") != expected_scope:
        return None
    return (
        str(target.get("scope") or ""),
        str(target.get("path") or ""),
        str(target.get("version") or ""),
    )


def _atomic_edges(
    engine,
    atomics: Mapping[str, Mapping[str, Any]],
    digests: Mapping[str, Mapping[str, Any]],
    edges: Dict[Tuple[str, str, str, str, str, str], Dict[str, Any]],
) -> None:
    for record_id in sorted(atomics):
        record = atomics[record_id]
        meta = record["meta"]
        scope = str(record["scope"])
        source_path = str(record["path"])
        source_version = str(record["version"])

        for relation_type, field in (
            ("supersedes", "supersedes"),
            ("superseded_by", "superseded_by"),
        ):
            target_id = _safe_ref(meta.get(field))
            if not target_id:
                continue
            target = atomics.get(target_id)
            canonical = _canonical_target(target, scope)
            if canonical is None:
                # A canonical-to-canonical edge is emitted only when both ends
                # currently exist in the same authorized scope.
                continue
            target_scope, target_path, target_version = canonical
            _add_edge(
                edges,
                scope=scope,
                relation_type=relation_type,
                source_kind="atomic_memory",
                source_ref=record_id,
                source_path=source_path,
                source_version=source_version,
                target_kind="atomic_memory",
                target_ref=target_id,
                target_scope=target_scope,
                target_path=target_path,
                target_version=target_version,
                evidence={"field": field, "value": target_id},
            )

        refs = _json_string_list(meta.get("evidence_refs"))
        source_ref = _safe_ref(meta.get("source"))
        if source_ref.startswith(_DIGEST_REF_PREFIX) and source_ref not in refs:
            refs.append(source_ref)

        for ref in refs:
            if ref.startswith(_DIGEST_REF_PREFIX):
                digest_id = ref[len(_DIGEST_REF_PREFIX) :]
                target = digests.get(digest_id)
                canonical = _canonical_target(target, scope)
                if canonical is None:
                    continue
                target_scope, target_path, target_version = canonical
                _add_edge(
                    edges,
                    scope=scope,
                    relation_type="derived_from",
                    source_kind="atomic_memory",
                    source_ref=record_id,
                    source_path=source_path,
                    source_version=source_version,
                    target_kind="session_digest",
                    target_ref=digest_id,
                    target_scope=target_scope,
                    target_path=target_path,
                    target_version=target_version,
                    evidence={"field": "evidence_refs", "value": ref},
                )
                continue

            _add_edge(
                edges,
                scope=scope,
                relation_type="derived_from",
                source_kind="atomic_memory",
                source_ref=record_id,
                source_path=source_path,
                source_version=source_version,
                target_kind="external_ref",
                target_ref=ref,
                evidence={"field": "evidence_refs", "value": ref},
            )


def _digest_edges(
    digests: Mapping[str, Mapping[str, Any]],
    edges: Dict[Tuple[str, str, str, str, str, str], Dict[str, Any]],
) -> None:
    for digest_id in sorted(digests):
        record = digests[digest_id]
        scope = str(record["scope"])
        source_path = str(record["path"])
        source_version = str(record["version"])
        provenance = record.get("provenance")
        provenance = dict(provenance) if isinstance(provenance, Mapping) else {}
        provenance_summary = {
            key: provenance[key]
            for key in ("owner", "kind", "session_id", "run_id")
            if key in provenance
        }
        common = {
            "provenance": provenance_summary,
            "source_fingerprint": str(record.get("source_fingerprint") or ""),
            "source_version": str(record.get("source_version") or ""),
            "digest_fingerprint": str(record.get("digest_fingerprint") or ""),
        }

        for field in ("source_refs", "source_coverage"):
            for ref in record.get(field) or []:
                _add_edge(
                    edges,
                    scope=scope,
                    relation_type="derived_from",
                    source_kind="session_digest",
                    source_ref=digest_id,
                    source_path=source_path,
                    source_version=source_version,
                    target_kind="external_ref",
                    target_ref=str(ref),
                    evidence={**common, "field": field, "value": str(ref)},
                )

        session_id = str(record.get("session_id") or "")
        if session_id:
            target = f"gateway:session:{session_id}"
            _add_edge(
                edges,
                scope=scope,
                relation_type="same_session",
                source_kind="session_digest",
                source_ref=digest_id,
                source_path=source_path,
                source_version=source_version,
                target_kind="session",
                target_ref=target,
                evidence={
                    **common,
                    "field": "session_id",
                    "session_id": session_id,
                    "run_id": str(record.get("run_id") or ""),
                },
            )


def _build(engine, root: Path, mode: str) -> List[Dict[str, Any]]:
    atomics = _atomic_records(engine, root, mode)
    digests = _digest_records(engine, root, mode)
    edges: Dict[Tuple[str, str, str, str, str, str], Dict[str, Any]] = {}
    _atomic_edges(engine, atomics, digests, edges)
    _digest_edges(digests, edges)

    output: List[Dict[str, Any]] = []
    for key in sorted(edges):
        row = dict(edges[key])
        evidence = list(row.pop("evidence"))
        row["edge_id"] = _edge_id(key)
        row["schema_version"] = RELATIONSHIP_SCHEMA
        row["evidence"] = evidence
        output.append(row)
    return output


def _replace_projection(
    engine,
    root: Path,
    mode: str,
    edges: Sequence[Mapping[str, Any]],
) -> None:
    conn, _ = engine.connect_db(root, mode)
    try:
        _table(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM memory_relationships")
        for edge in edges:
            conn.execute(
                """
                INSERT INTO memory_relationships
                (edge_id, schema_version, scope, relation_type,
                 source_kind, source_ref, source_path, source_version,
                 target_kind, target_ref, target_scope, target_path,
                 target_version, evidence_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge["edge_id"],
                    edge["schema_version"],
                    edge["scope"],
                    edge["relation_type"],
                    edge["source_kind"],
                    edge["source_ref"],
                    edge["source_path"],
                    edge["source_version"],
                    edge["target_kind"],
                    edge["target_ref"],
                    edge.get("target_scope") or None,
                    edge.get("target_path") or None,
                    edge.get("target_version") or None,
                    _stable_json(edge["evidence"]),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _projection_summary(edges: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    relation_types: Dict[str, int] = {}
    scopes: Dict[str, int] = {}
    normalized = []
    for edge in edges:
        relation = str(edge["relation_type"])
        scope = str(edge["scope"])
        relation_types[relation] = relation_types.get(relation, 0) + 1
        scopes[scope] = scopes.get(scope, 0) + 1
        normalized.append(dict(edge))
    return {
        "schema_version": RELATIONSHIP_SCHEMA,
        "edge_count": len(edges),
        "relation_types": {key: relation_types[key] for key in sorted(relation_types)},
        "scopes": {key: scopes[key] for key in sorted(scopes)},
        "projection_fingerprint": _hash(_stable_json(normalized)),
    }


def apply(engine) -> None:
    required = (
        "iter_atomic_files",
        "parse_markdown",
        "_validated_atomic_scope",
        "_source_version",
        "relpath",
        "refresh_session_digest_index",
        "connect_db",
        "normalize_scope",
        "allowed_scopes",
    )
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError(
            "Relationship projection requires established Memory owner surfaces: "
            + ", ".join(missing)
        )

    def rebuild_relationship_projection(
        *,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        resolved_root = Path(root or engine.repository_root()).resolve()
        resolved_mode = mode or engine.detect_mode(resolved_root)
        edges = _build(engine, resolved_root, resolved_mode)
        _replace_projection(engine, resolved_root, resolved_mode, edges)
        return _projection_summary(edges)

    def refresh_relationship_projection(
        *,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        # D1 intentionally favors deterministic freshness over caching.  This
        # can become incremental only if later benchmarks prove the complexity
        # earns its cost.
        return rebuild_relationship_projection(root=root, mode=mode)

    def list_relationships(
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        relation_type: Optional[str] = None,
        source_ref: Optional[str] = None,
        target_ref: Optional[str] = None,
        limit: int = 100,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RELATION_LIMIT
        ):
            raise ValueError(
                f"relationship limit must be an integer between 1 and {MAX_RELATION_LIMIT}"
            )
        if relation_type is not None and relation_type not in _ALLOWED_RELATION_TYPES:
            raise ValueError(f"unsupported relationship type: {relation_type!r}")
        wanted_source = _safe_ref(source_ref) if source_ref is not None else ""
        wanted_target = _safe_ref(target_ref) if target_ref is not None else ""
        if source_ref is not None and not wanted_source:
            raise ValueError("source_ref is invalid")
        if target_ref is not None and not wanted_target:
            raise ValueError("target_ref is invalid")

        resolved_root = Path(root or engine.repository_root()).resolve()
        resolved_mode = mode or engine.detect_mode(resolved_root)
        refresh_relationship_projection(root=resolved_root, mode=resolved_mode)

        scopes, _ = engine.allowed_scopes(
            resolved_root,
            resolved_mode,
            scope=scope,
            workspace=workspace,
            all_workspaces=False,
        )
        visible = list(scopes or [])
        conn, _ = engine.connect_db(resolved_root, resolved_mode)
        try:
            clauses: List[str] = []
            params: List[Any] = []
            if visible:
                placeholders = ",".join("?" for _ in visible)
                clauses.append(f"scope IN ({placeholders})")
                params.extend(visible)
            else:
                # Fail closed rather than turning an empty visibility set into
                # an unscoped relationship query.
                return []
            if relation_type is not None:
                clauses.append("relation_type=?")
                params.append(relation_type)
            if wanted_source:
                clauses.append("source_ref=?")
                params.append(wanted_source)
            if wanted_target:
                clauses.append("target_ref=?")
                params.append(wanted_target)

            where = " AND ".join(clauses)
            rows = conn.execute(
                f"""
                SELECT * FROM memory_relationships
                WHERE {where}
                ORDER BY relation_type, scope, source_kind, source_ref,
                         target_kind, target_ref, edge_id
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        finally:
            conn.close()

        output: List[Dict[str, Any]] = []
        for row in rows:
            output.append(
                {
                    "edge_id": str(row["edge_id"]),
                    "schema_version": int(row["schema_version"]),
                    "scope": str(row["scope"]),
                    "relation_type": str(row["relation_type"]),
                    "source_kind": str(row["source_kind"]),
                    "source_ref": str(row["source_ref"]),
                    "source_path": str(row["source_path"]),
                    "source_version": str(row["source_version"]),
                    "target_kind": str(row["target_kind"]),
                    "target_ref": str(row["target_ref"]),
                    "target_scope": str(row["target_scope"] or ""),
                    "target_path": str(row["target_path"] or ""),
                    "target_version": str(row["target_version"] or ""),
                    "evidence": json.loads(row["evidence_json"] or "[]"),
                }
            )
        return output

    engine.rebuild_relationship_projection = rebuild_relationship_projection
    engine.refresh_relationship_projection = refresh_relationship_projection
    engine.list_relationships = list_relationships
    engine.RELATIONSHIP_SCHEMA = RELATIONSHIP_SCHEMA
    engine.RELATIONSHIP_TYPES = tuple(sorted(_ALLOWED_RELATION_TYPES))
    engine.RELATIONSHIP_MAX_LIMIT = MAX_RELATION_LIMIT
