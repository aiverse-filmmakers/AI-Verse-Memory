"""Tiny rebuildable per-scope orientation map for AI-Verse Memory.

The map is a disposable projection. Canonical atomic Memory, indexed owner
sources, and canonical session digests remain authoritative. The projection
contains only compact routing metadata, counts, explicit tags/topics, and
digest pointers. It never copies full Memory text or digest summaries.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ORIENTATION_MAP_SCHEMA = 2
MAX_TOPIC_ENTRIES = 12
MAX_RECENT_DIGESTS = 8
MAX_ROUTE_PATHS_PER_KIND = 2
DEFAULT_MAX_BYTES = 8192
MIN_MAX_BYTES = 1024
MAX_MAX_BYTES = 65536
BUDGET_ENV = "AI_VERSE_ORIENTATION_MAP_MAX_BYTES"


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _serialized_bytes(value: object) -> int:
    return len(_stable_json(value).encode("utf-8"))


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
        raise ValueError("orientation map max_bytes must be an integer")
    if raw < MIN_MAX_BYTES or raw > MAX_MAX_BYTES:
        raise ValueError(
            f"orientation map max_bytes must be between {MIN_MAX_BYTES} and {MAX_MAX_BYTES}"
        )
    return raw


def _fingerprint(
    target_scope: str,
    visible_scopes: Sequence[str],
    atomic_rows: Sequence[Dict[str, str]],
    indexed_sources: Sequence[Dict[str, str]],
    digests: Sequence[Dict[str, str]],
) -> str:
    payload = {
        "scope": target_scope,
        "visible_scopes": list(visible_scopes),
        "atomic": [
            [row["id"], row["scope"], row["path"], row["source_version"]]
            for row in atomic_rows
        ],
        "sources": [
            [
                row["id"],
                row["kind"],
                row["scope"],
                row["path"],
                row["source_version"],
                row["freshness"],
            ]
            for row in indexed_sources
        ],
        "session_digests": [
            [
                row["id"],
                row["scope"],
                row["canonical_version"],
                row["digest_fingerprint"],
            ]
            for row in digests
        ],
    }
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return "sha256:" + digest


def _enforce_budget(projection: Dict[str, Any], max_bytes: int) -> Dict[str, Any]:
    bounded = json.loads(_stable_json(projection))
    bounded["budget_bytes"] = max_bytes
    bounded["truncated"] = False
    if _serialized_bytes(bounded) <= max_bytes:
        return bounded

    bounded["truncated"] = True

    # Routes retain kind/scope/count even when path samples are removed.
    while _serialized_bytes(bounded) > max_bytes:
        changed = False
        for route in reversed(bounded.get("source_routes", [])):
            paths = route.get("paths") or []
            if paths:
                paths.pop()
                changed = True
                break
        if not changed:
            break

    while _serialized_bytes(bounded) > max_bytes and bounded.get("recent_sessions"):
        bounded["recent_sessions"].pop()

    while _serialized_bytes(bounded) > max_bytes and bounded.get("topics"):
        bounded["topics"].pop()

    while _serialized_bytes(bounded) > max_bytes and bounded.get("source_routes"):
        bounded["source_routes"].pop()

    size = _serialized_bytes(bounded)
    if size > max_bytes:
        raise ValueError(
            f"orientation map core metadata requires {size} bytes, above configured budget {max_bytes}"
        )
    return bounded


def _target_and_visible_scopes(
    engine,
    root: Path,
    mode: str,
    *,
    scope: Optional[str],
    workspace: Optional[str],
) -> Tuple[str, List[str]]:
    if workspace is not None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("workspace must be a non-empty string")
        workspace_scope = f"workspace:{workspace.strip()}"
        if scope not in (None, "", workspace_scope):
            raise ValueError("scope conflicts with workspace")
        target = engine.normalize_scope(workspace_scope, root, mode)
    elif scope:
        target = engine.normalize_scope(scope, root, mode)
    else:
        target = "operator" if mode == engine.MODE_NATIVE else "global"
        target = engine.normalize_scope(target, root, mode)

    if mode == engine.MODE_NATIVE:
        visible, _ = engine.allowed_scopes(
            root,
            mode,
            scope=target,
            workspace=None,
            all_workspaces=False,
        )
        scopes = list(visible or [target])
    else:
        scopes = [target]
        if target != "global":
            scopes.append("global")

    deduped: List[str] = []
    for item in scopes:
        normalized = engine.normalize_scope(item, root, mode)
        if normalized not in deduped:
            deduped.append(normalized)
    return target, deduped


def _connect_projection(engine, root: Path, mode: str) -> sqlite3.Connection:
    p = engine.ensure_layout(root, mode)
    if not p["db"].exists():
        engine.rebuild(silent=True, root=root, mode=mode)
    conn = sqlite3.connect(p["db"])
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orientation_maps (
            scope TEXT PRIMARY KEY,
            projection_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _atomic_metadata(
    engine,
    root: Path,
    mode: str,
    visible_scopes: Sequence[str],
) -> List[Dict[str, str]]:
    allowed = set(visible_scopes)
    rows: List[Dict[str, str]] = []
    for path in engine.iter_atomic_files(root, mode):
        try:
            meta, _ = engine.parse_markdown(path)
            physical_scope = engine._validated_atomic_scope(path, root, mode, meta)
        except (OSError, ValueError):
            continue
        if physical_scope not in allowed:
            continue
        if (meta.get("status") or "active") != "active":
            continue
        rows.append(
            {
                "id": str(meta.get("id") or path.stem),
                "scope": physical_scope,
                "type": str(meta.get("type") or "fact"),
                "tags": str(meta.get("tags") or ""),
                "path": (
                    engine.relpath(path, root)
                    if mode == engine.MODE_NATIVE
                    else str(path.resolve())
                ),
                "source_version": engine._source_version(path),
            }
        )
    rows.sort(key=lambda row: (row["scope"], row["type"], row["id"], row["path"]))
    return rows


def _indexed_sources(
    engine,
    root: Path,
    mode: str,
    visible_scopes: Sequence[str],
) -> List[Dict[str, str]]:
    if mode == engine.MODE_STANDALONE:
        # Standalone sources do not have the native incremental refresh path.
        # Rebuild only the disposable index so manual profile/scenario edits are
        # reflected without ever rewriting canonical source files.
        engine.rebuild(silent=True, root=root, mode=mode)

    conn, fts = engine.connect_db(root, mode)
    try:
        engine._purge_invalid_indexed_sources(conn, fts, root, mode)
        if mode == engine.MODE_NATIVE:
            engine._refresh_native_canonical_sources(conn, fts, root, mode)
        placeholders = ",".join("?" for _ in visible_scopes)
        rows = conn.execute(
            f"""
            SELECT i.id, i.kind, i.path, i.scope, i.status,
                   s.source_version, s.freshness
            FROM items i
            LEFT JOIN source_state s ON s.item_id=i.id
            WHERE i.kind!='memory'
              AND i.status='active'
              AND i.scope IN ({placeholders})
            ORDER BY i.scope, i.kind, i.path, i.id
            """,
            list(visible_scopes),
        ).fetchall()
        result: List[Dict[str, str]] = []
        for row in rows:
            if not engine._indexed_source_is_valid(row, root, mode):
                continue
            stored_path = str(row["path"])
            source_path = Path(stored_path)
            if not source_path.is_absolute():
                source_path = root / source_path
            version = str(row["source_version"] or "")
            if not version:
                try:
                    version = engine._source_version(source_path)
                except OSError:
                    continue
            result.append(
                {
                    "id": str(row["id"]),
                    "kind": str(row["kind"]),
                    "path": stored_path,
                    "scope": str(row["scope"]),
                    "source_version": version,
                    "freshness": str(row["freshness"] or "fresh"),
                }
            )
        return result
    finally:
        conn.close()


def _session_digests(
    engine,
    root: Path,
    mode: str,
    visible_scopes: Sequence[str],
) -> List[Dict[str, str]]:
    engine.refresh_session_digest_index(root=root, mode=mode)
    conn = _connect_projection(engine, root, mode)
    try:
        placeholders = ",".join("?" for _ in visible_scopes)
        rows = conn.execute(
            f"""
            SELECT id, scope, session_id, run_id, topic, completed_at, created_at,
                   canonical_version, digest_fingerprint
            FROM session_digest_items
            WHERE scope IN ({placeholders})
            ORDER BY completed_at DESC, created_at DESC, id DESC
            """,
            list(visible_scopes),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "scope": str(row["scope"]),
                "session_id": str(row["session_id"] or ""),
                "run_id": str(row["run_id"] or ""),
                "topic": str(row["topic"] or ""),
                "completed_at": str(row["completed_at"] or row["created_at"] or ""),
                "canonical_version": str(row["canonical_version"] or ""),
                "digest_fingerprint": str(row["digest_fingerprint"] or ""),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _tag_values(raw: str) -> Iterable[str]:
    for item in re.split(r"[,;|]+", raw or ""):
        value = re.sub(r"\s+", " ", item).strip()
        if value:
            yield value


def _compact_topics(
    atomic_rows: Sequence[Dict[str, str]],
    digests: Sequence[Dict[str, str]],
) -> List[Dict[str, Any]]:
    aggregate: Dict[str, Dict[str, Any]] = {}

    def add(label: str, origin: str) -> None:
        display = re.sub(r"\s+", " ", label).strip()
        if not display:
            return
        key = display.casefold()
        entry = aggregate.setdefault(
            key,
            {"label": display, "count": 0, "origins": set()},
        )
        entry["count"] += 1
        entry["origins"].add(origin)

    for row in atomic_rows:
        for tag in _tag_values(row.get("tags", "")):
            add(tag, "memory_tag")
    for row in digests:
        add(row.get("topic", ""), "session_digest")

    ordered = sorted(
        aggregate.values(),
        key=lambda item: (
            -int(item["count"]),
            str(item["label"]).casefold(),
            str(item["label"]),
        ),
    )
    return [
        {
            "label": item["label"],
            "count": int(item["count"]),
            "origins": sorted(item["origins"]),
        }
        for item in ordered[:MAX_TOPIC_ENTRIES]
    ]


def _source_routes(rows: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str], List[str]] = {}
    for row in rows:
        grouped.setdefault((row["scope"], row["kind"]), []).append(row["path"])

    routes: List[Dict[str, Any]] = []
    for (scope, kind), paths in sorted(grouped.items()):
        unique = sorted(set(paths))
        routes.append(
            {
                "scope": scope,
                "kind": kind,
                "count": len(unique),
                "paths": unique[:MAX_ROUTE_PATHS_PER_KIND],
            }
        )
    return routes


def _counts_by(rows: Sequence[Dict[str, str]], key: str, output_key: str) -> List[Dict[str, Any]]:
    counts = Counter(row[key] for row in rows)
    return [
        {output_key: name, "count": int(count)}
        for name, count in sorted(counts.items(), key=lambda item: item[0])
    ]


def _projection(
    target_scope: str,
    visible_scopes: Sequence[str],
    atomic_rows: Sequence[Dict[str, str]],
    indexed_sources: Sequence[Dict[str, str]],
    digests: Sequence[Dict[str, str]],
    *,
    source_fingerprint: str,
    max_bytes: int,
) -> Dict[str, Any]:
    recent = [
        {
            "digest_id": row["id"],
            "session_id": row["session_id"],
            "run_id": row["run_id"],
            "scope": row["scope"],
            "topic": row["topic"],
            "completed_at": row["completed_at"],
        }
        for row in digests[:MAX_RECENT_DIGESTS]
    ]
    projection = {
        "schema_version": ORIENTATION_MAP_SCHEMA,
        "scope": target_scope,
        "visible_scopes": list(visible_scopes),
        "source_fingerprint": source_fingerprint,
        "counts": {
            "atomic_memory": len(atomic_rows),
            "indexed_sources": len(indexed_sources),
            "session_digests": len(digests),
        },
        "memory_types": _counts_by(atomic_rows, "type", "type"),
        "source_kinds": _counts_by(indexed_sources, "kind", "kind"),
        "source_routes": _source_routes(indexed_sources),
        "topics": _compact_topics(atomic_rows, digests),
        "recent_sessions": recent,
    }
    return _enforce_budget(projection, max_bytes)


def _install_rebuild(engine):
    def rebuild_orientation_map(
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        target_scope, visible_scopes = _target_and_visible_scopes(
            engine,
            root,
            mode,
            scope=scope,
            workspace=workspace,
        )

        atomic_rows = _atomic_metadata(engine, root, mode, visible_scopes)
        sources = _indexed_sources(engine, root, mode, visible_scopes)
        digests = _session_digests(engine, root, mode, visible_scopes)
        budget = _resolve_budget(max_bytes)
        source_fingerprint = _fingerprint(
            target_scope,
            visible_scopes,
            atomic_rows,
            sources,
            digests,
        )
        projection = _projection(
            target_scope,
            visible_scopes,
            atomic_rows,
            sources,
            digests,
            source_fingerprint=source_fingerprint,
            max_bytes=budget,
        )

        conn = _connect_projection(engine, root, mode)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO orientation_maps(scope, projection_json) VALUES (?, ?)",
                (target_scope, _stable_json(projection)),
            )
            conn.commit()
        finally:
            conn.close()
        return projection

    return rebuild_orientation_map


def _install_get(engine):
    rebuild = engine.rebuild_orientation_map

    def get_orientation_map(
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Always refresh from authoritative evidence before returning derived
        # navigation. This makes a stale stored projection untrusted by design.
        return rebuild(
            scope=scope,
            workspace=workspace,
            root=root,
            mode=mode,
            max_bytes=max_bytes,
        )

    return get_orientation_map


def _install_diagnostics(engine):
    def get_orientation_map_diagnostics(
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        projection = engine.get_orientation_map(
            scope=scope,
            workspace=workspace,
            root=root,
            mode=mode,
            max_bytes=max_bytes,
        )
        size = _serialized_bytes(projection)
        return {
            "schema_version": 1,
            "scope": projection["scope"],
            "visible_scope_count": len(projection["visible_scopes"]),
            "source_fingerprint": projection["source_fingerprint"],
            "freshness": "fresh",
            "projection_bytes": size,
            "estimated_tokens": (size + 3) // 4,
            "token_estimate_method": "utf8_bytes_div_4_ceiling",
            "budget_bytes": projection["budget_bytes"],
            "truncated": bool(projection["truncated"]),
            "source_counts": dict(projection["counts"]),
            "returned_entries": {
                "memory_types": len(projection["memory_types"]),
                "source_kinds": len(projection["source_kinds"]),
                "source_routes": len(projection["source_routes"]),
                "topics": len(projection["topics"]),
                "recent_sessions": len(projection["recent_sessions"]),
            },
        }

    return get_orientation_map_diagnostics


def apply(engine) -> None:
    required = (
        "iter_atomic_files",
        "parse_markdown",
        "_validated_atomic_scope",
        "connect_db",
        "_purge_invalid_indexed_sources",
        "_refresh_native_canonical_sources",
        "_indexed_source_is_valid",
        "allowed_scopes",
        "refresh_session_digest_index",
        "_source_version",
    )
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError(
            "Orientation map requires established Memory projections: "
            + ", ".join(missing)
        )

    engine.rebuild_orientation_map = _install_rebuild(engine)
    engine.get_orientation_map = _install_get(engine)
    engine.get_orientation_map_diagnostics = _install_diagnostics(engine)
    engine.ORIENTATION_MAP_SCHEMA = ORIENTATION_MAP_SCHEMA
    engine.ORIENTATION_MAP_MAX_TOPIC_ENTRIES = MAX_TOPIC_ENTRIES
    engine.ORIENTATION_MAP_MAX_RECENT_DIGESTS = MAX_RECENT_DIGESTS
    engine.ORIENTATION_MAP_DEFAULT_MAX_BYTES = DEFAULT_MAX_BYTES
    engine.ORIENTATION_MAP_MIN_MAX_BYTES = MIN_MAX_BYTES
    engine.ORIENTATION_MAP_MAX_MAX_BYTES = MAX_MAX_BYTES
