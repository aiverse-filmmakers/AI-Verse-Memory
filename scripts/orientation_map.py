"""Tiny rebuildable per-scope orientation map for AI-Verse Memory.

The map is a disposable projection. Canonical atomic Memory, indexed owner
sources, and canonical session digests remain authoritative. The projection
contains only compact routing metadata, counts, explicit tags/topics, and
digest pointers. It never copies full Memory text or digest summaries.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ORIENTATION_MAP_SCHEMA = 1
MAX_TOPIC_ENTRIES = 12
MAX_RECENT_DIGESTS = 8
MAX_ROUTE_PATHS_PER_KIND = 2


def _stable_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


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
            SELECT id, kind, path, scope, status
            FROM items
            WHERE kind!='memory'
              AND status='active'
              AND scope IN ({placeholders})
            ORDER BY scope, kind, path, id
            """,
            list(visible_scopes),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "path": str(row["path"]),
                "scope": str(row["scope"]),
            }
            for row in rows
            if engine._indexed_source_is_valid(row, root, mode)
        ]
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
            SELECT id, scope, session_id, run_id, topic, completed_at, created_at
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
    return {
        "schema_version": ORIENTATION_MAP_SCHEMA,
        "scope": target_scope,
        "visible_scopes": list(visible_scopes),
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


def _install_rebuild(engine):
    def rebuild_orientation_map(
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
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
        projection = _projection(
            target_scope,
            visible_scopes,
            atomic_rows,
            sources,
            digests,
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
    ) -> Dict[str, Any]:
        # B1 always refreshes before returning the projection. B2 may add a
        # fingerprinted cache policy, byte budget, and diagnostics without
        # weakening this freshness behavior.
        return rebuild(
            scope=scope,
            workspace=workspace,
            root=root,
            mode=mode,
        )

    return get_orientation_map


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
    )
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError(
            "Orientation map requires established Memory projections: "
            + ", ".join(missing)
        )

    engine.rebuild_orientation_map = _install_rebuild(engine)
    engine.get_orientation_map = _install_get(engine)
    engine.ORIENTATION_MAP_SCHEMA = ORIENTATION_MAP_SCHEMA
    engine.ORIENTATION_MAP_MAX_TOPIC_ENTRIES = MAX_TOPIC_ENTRIES
    engine.ORIENTATION_MAP_MAX_RECENT_DIGESTS = MAX_RECENT_DIGESTS
