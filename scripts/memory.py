#!/usr/bin/env python3
"""Compatibility-gated entrypoint for the AI-Verse Memory engine."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

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
_public_beta = _load_sibling("_aiverse_memory_public_beta", "public_beta.py")
_public_beta.apply(_engine)

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


_AUTO_CAPTURE_TYPES = {
    "fact",
    "preference",
    "entity",
    "event",
    "experience",
    "workflow",
    "lesson",
    "correction",
}
_AUTO_CAPTURE_FIELDS = {
    "text",
    "type",
    "scope",
    "workspace",
    "importance",
    "confidence",
    "source",
    "why",
    "tags",
    "effect_id",
    "evidence_refs",
    "admission",
}
_AUTO_ADMISSION_FIELDS = {
    "durable",
    "historical",
    "current_truth",
    "contains_secret",
    "strategic",
    "permission_expansion",
    "privacy_ambiguous",
    "external_authority",
}
_SECRET_PATTERNS = (
    re.compile(r"(?i)\\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|private[_ -]?key)\\s*[:=]\\s*[^\\s,;]{6,}"),
    re.compile(r"\\bsk-[A-Za-z0-9_-]{20,}\\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def _auto_capture_secret_like(value: object) -> bool:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return any(pattern.search(rendered) for pattern in _SECRET_PATTERNS)


def capture_candidate(
    candidate: Mapping[str, Any],
    *,
    root: Optional[Path] = None,
    mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Admit one low-risk historical candidate into canonical Memory.

    This is a thin deterministic gate over the existing owner writer. It does
    not classify conversations itself and it does not create another store.
    Callers must provide bounded evidence and explicit safety assertions.
    """

    if not isinstance(candidate, Mapping):
        raise ValueError("Memory capture candidate must be an object")
    unknown = set(candidate) - _AUTO_CAPTURE_FIELDS
    if unknown:
        raise ValueError(f"Unsupported Memory capture candidate fields: {sorted(unknown)}")

    admission = candidate.get("admission")
    if not isinstance(admission, Mapping):
        raise ValueError("Memory capture candidate requires an admission object")
    unknown_admission = set(admission) - _AUTO_ADMISSION_FIELDS
    if unknown_admission:
        raise ValueError(f"Unsupported Memory admission fields: {sorted(unknown_admission)}")

    required_positive = ("durable", "historical")
    required_negative = (
        "current_truth",
        "contains_secret",
        "strategic",
        "permission_expansion",
        "privacy_ambiguous",
        "external_authority",
    )
    if any(admission.get(key) is not True for key in required_positive):
        return {
            "state": "ignored",
            "reason": "candidate is not explicitly durable historical evidence",
            "changed": False,
        }
    if any(admission.get(key) is not False for key in required_negative):
        return {
            "state": "blocked",
            "reason": "candidate crosses a current-truth, privacy, secret, strategic, permission, or external-authority boundary",
            "changed": False,
        }

    text = candidate.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Memory capture candidate text must be non-empty")
    text = text.strip()
    if len(text) > 5000:
        raise ValueError("Memory capture candidate text exceeds 5000 characters")

    mem_type = candidate.get("type")
    if mem_type not in _AUTO_CAPTURE_TYPES:
        return {
            "state": "blocked",
            "reason": f"memory type {mem_type!r} is not eligible for automatic historical capture",
            "changed": False,
        }

    confidence = candidate.get("confidence", 1.0)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Memory capture confidence must be numeric")
    confidence = float(confidence)
    if confidence < 0.75:
        return {
            "state": "ignored",
            "reason": "candidate confidence is below the automatic capture threshold",
            "changed": False,
        }

    source = candidate.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Automatic Memory capture requires a provenance source")
    source = source.strip()

    evidence_refs = candidate.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        raise ValueError("Automatic Memory capture requires at least one evidence reference")
    refs: List[str] = []
    for index, ref in enumerate(evidence_refs):
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError(f"evidence_refs[{index}] must be a non-empty string")
        value = ref.strip()
        if len(value) > 500:
            raise ValueError(f"evidence_refs[{index}] exceeds 500 characters")
        if value not in refs:
            refs.append(value)
    if len(refs) > 32:
        raise ValueError("Automatic Memory capture accepts at most 32 evidence references")

    effect_id = candidate.get("effect_id")
    if not isinstance(effect_id, str) or not effect_id.strip():
        raise ValueError("Automatic Memory capture requires an effect_id for retry safety")
    effect_id = effect_id.strip()
    if len(effect_id) > 500:
        raise ValueError("Memory capture effect_id exceeds 500 characters")

    workspace = candidate.get("workspace")
    scope = candidate.get("scope")
    if workspace is not None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("Memory capture workspace must be a non-empty string")
        workspace_scope = f"workspace:{workspace.strip()}"
        if scope not in (None, "", workspace_scope):
            raise ValueError("Memory capture scope conflicts with workspace")
        scope = workspace_scope
    elif scope is not None and not isinstance(scope, str):
        raise ValueError("Memory capture scope must be a string")

    sanitized = {
        "text": text,
        "type": mem_type,
        "scope": scope,
        "source": source,
        "why": candidate.get("why", ""),
        "tags": candidate.get("tags", ""),
        "evidence_refs": refs,
        "effect_id": effect_id,
    }
    if _auto_capture_secret_like(sanitized):
        return {
            "state": "blocked",
            "reason": "candidate contains secret-like material",
            "changed": False,
        }

    importance = candidate.get("importance", 3)
    if isinstance(importance, bool) or not isinstance(importance, int):
        raise ValueError("Memory capture importance must be an integer")

    resolved_root = Path(root or _engine.repository_root()).resolve()
    resolved_mode = mode or detect_mode(resolved_root)
    mem_id, path, created = _engine.write_atomic(
        text=text,
        mem_type=mem_type,
        scope=scope,
        importance=importance,
        confidence=confidence,
        source=source,
        why=str(candidate.get("why", "") or ""),
        tags=str(candidate.get("tags", "") or ""),
        root=resolved_root,
        mode=resolved_mode,
        effect_id=effect_id,
        evidence_refs=refs,
    )
    return {
        "state": "captured" if created else "existing",
        "changed": bool(created),
        "memory_id": mem_id,
        "type": mem_type,
        "scope": _engine.normalize_scope(scope, resolved_root, resolved_mode),
        "path": _engine.relpath(path, resolved_root) if resolved_mode == _engine.MODE_NATIVE else str(path),
        "source": source,
        "evidence_refs": refs,
    }


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
