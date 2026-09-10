#!/usr/bin/env python3
"""Compatibility-gated entrypoint for the AI-Verse Memory engine."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import List, Optional

_HERE = Path(__file__).resolve().parent
_MAX_FTS_QUERY_TERMS = 64


def _load_sibling(module_name: str, filename: str):
    path = _HERE / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load required Memory component: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_compat = _load_sibling("_aiverse_memory_os_compat", "os_compat.py")
_engine = _load_sibling("_aiverse_memory_engine", "memory_engine.py")

# Preserve the established public/module surface, including private helpers used
# by the repository acceptance suite, while keeping the implementation payload
# isolated from this compatibility gate.
for _name in dir(_engine):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_engine, _name)


def detect_os_compatibility(root: Optional[Path] = None):
    root = (root or _engine.repository_root()).resolve()
    return _compat.detect_os_compatibility(root)


def detect_mode(root: Optional[Path] = None) -> str:
    root = (root or _engine.repository_root()).resolve()
    result = _compat.require_supported_os_or_none(root)
    if result.status == _compat.OS_COMPATIBLE:
        return _engine.MODE_NATIVE
    return _engine.MODE_STANDALONE


# Every engine function that resolves its own mode uses this shared gate.
_engine.detect_mode = detect_mode


def _fts_query_terms(query: str) -> List[str]:
    """Return a bounded set of unique terms without discarding late task signals.

    Brain and other semantic callers intentionally place descriptive task signals
    after a human-readable retrieval prefix. The former engine behavior used only
    the first 12 tokens for FTS candidate selection, which could exclude every
    task-specific term before lexical ranking had a chance to see the right row.
    """

    result: List[str] = []
    seen = set()
    for token in _engine.tokenize(query):
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
        if len(result) >= _MAX_FTS_QUERY_TERMS:
            break
    return result


def recall(
    query: str,
    scope: Optional[str] = None,
    limit: int = 8,
    include_history: bool = False,
    root: Optional[Path] = None,
    mode: Optional[str] = None,
    workspace: Optional[str] = None,
    all_workspaces: bool = False,
):
    """Recall through bounded FTS candidate generation that preserves semantic signals."""

    root = root or _engine.repository_root()
    mode = mode or detect_mode(root)
    p = _engine.ensure_layout(root, mode)
    if not p["db"].exists():
        _engine.rebuild(silent=True, root=root, mode=mode)
    conn, fts = _engine.connect_db(root, mode)
    _engine._purge_invalid_indexed_sources(conn, fts, root, mode)
    _engine._refresh_native_canonical_sources(conn, fts, root, mode)
    _engine._ensure_historical_source_state(conn, root, mode)
    scopes, primary_scope = _engine.allowed_scopes(root, mode, scope, workspace, all_workspaces)

    status_clause = "" if include_history else "AND i.status='active'"
    scope_clause = ""
    params: List[str] = []
    if scopes:
        placeholders = ",".join("?" for _ in scopes)
        scope_clause = f"AND i.scope IN ({placeholders})"
        params.extend(scopes)

    candidates = []
    terms = _fts_query_terms(query)
    used_fts = False
    if fts and terms:
        fts_query = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        try:
            sql = f"""
                SELECT i.*, s.source_identity, s.source_version, s.freshness, s.indexed_at
                FROM item_fts f
                JOIN items i ON i.id=f.id
                LEFT JOIN source_state s ON s.item_id=i.id
                WHERE item_fts MATCH ? {status_clause} {scope_clause}
                LIMIT 200
            """
            candidates = conn.execute(sql, [fts_query] + params).fetchall()
            used_fts = True
        except _engine.sqlite3.OperationalError:
            used_fts = False

    if not used_fts:
        sql = f"""
            SELECT i.*, s.source_identity, s.source_version, s.freshness, s.indexed_at
            FROM items i
            LEFT JOIN source_state s ON s.item_id=i.id
            WHERE 1=1 {status_clause} {scope_clause}
            ORDER BY i.importance DESC, i.updated_at DESC
            LIMIT 2000
        """
        candidates = conn.execute(sql, params).fetchall()

    candidates = [
        row
        for row in candidates
        if _engine._indexed_source_is_valid(row, root, mode) and _engine.row_matches_query(row, query)
    ]
    ranked = sorted(
        candidates,
        key=lambda row: _engine.custom_score(row, query, primary_scope),
        reverse=True,
    )
    conn.close()
    return ranked[: max(1, min(50, limit))]


# The engine CLI and any engine function resolving recall at runtime use the
# compatibility-gated implementation above. The public wrapper exports it too.
_engine.recall = recall


def mode_report(root: Path) -> None:
    result = detect_os_compatibility(root)
    mode = detect_mode(root)
    p = _engine.paths(root, mode)
    print(f"OS compatibility: {result.status}")
    print(f"Compatibility reason: {result.reason}")
    print(f"Mode: {mode}")
    print(f"Root: {root}")
    if mode == _engine.MODE_NATIVE:
        print(f"Operator atomic memory: {_engine.relpath(p['operator_atomic'], root)}")
        print("Workspace atomic memory: workspaces/<id>/memory/atomic/")
        print(f"Derived index: {_engine.relpath(p['db'], root)}")
        print("Current context, profile, decisions, and workspace manifests are indexed in place and remain canonical where they live.")
    else:
        print(f"Memory home: {p['home']}")
        print(f"Derived index: {p['db']}")


_engine.mode_report = mode_report


def main() -> int:
    try:
        return _engine.main()
    except RuntimeError as exc:
        if str(exc).startswith("Incompatible AI-Verse OS:"):
            print(f"error: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
