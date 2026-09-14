"""Selective promotion from session digests into canonical atomic Memory.

This module does not classify conversations and owns no canonical state. It
binds caller-supplied promotion candidates to one canonical session digest,
checks scope/evidence boundaries, derives retry-safe effect identities when
needed, and routes every candidate through Memory's existing capture authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

MAX_PROMOTIONS_PER_DIGEST = 8
_DIGEST_EVIDENCE_PREFIX = "memory:session-digest:"


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _normalized_scope(engine, root: Path, mode: str, scope: Optional[str], workspace: Optional[str]) -> str:
    requested = scope
    if workspace is not None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("workspace must be a non-empty string")
        workspace_scope = f"workspace:{workspace.strip()}"
        if requested not in (None, "", workspace_scope):
            raise ValueError("scope conflicts with workspace")
        requested = workspace_scope
    return engine.normalize_scope(requested, root, mode)


def _candidate_scope(engine, root: Path, mode: str, candidate: Mapping[str, Any], digest_scope: str) -> str:
    scope = candidate.get("scope")
    workspace = candidate.get("workspace")
    if workspace is not None:
        if not isinstance(workspace, str) or not workspace.strip():
            raise ValueError("promotion candidate workspace must be a non-empty string")
        workspace_scope = f"workspace:{workspace.strip()}"
        if scope not in (None, "", workspace_scope):
            raise ValueError("promotion candidate scope conflicts with workspace")
        scope = workspace_scope
    normalized = engine.normalize_scope(scope or digest_scope, root, mode)
    if normalized != digest_scope:
        raise ValueError("promotion candidate cannot cross the session digest scope")
    return normalized


def _prepare_candidates(
    engine,
    digest: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    root: Path,
    mode: str,
) -> list[Dict[str, Any]]:
    if isinstance(candidates, (str, bytes)) or not isinstance(candidates, Sequence):
        raise ValueError("promotion candidates must be a sequence of objects")
    if not candidates:
        raise ValueError("promotion requires at least one candidate")
    if len(candidates) > MAX_PROMOTIONS_PER_DIGEST:
        raise ValueError(
            f"promotion accepts at most {MAX_PROMOTIONS_PER_DIGEST} candidates per session digest"
        )

    digest_id = str(digest["id"])
    digest_scope = str(digest["scope"])
    digest_ref = _DIGEST_EVIDENCE_PREFIX + digest_id
    allowed_refs = {
        digest_ref,
        *[str(item) for item in digest.get("source_refs") or []],
        *[str(item) for item in digest.get("source_coverage") or []],
    }

    prepared: list[Dict[str, Any]] = []
    for index, raw in enumerate(candidates):
        if not isinstance(raw, Mapping):
            raise ValueError(f"promotion candidate {index} must be an object")
        candidate = dict(raw)
        normalized_scope = _candidate_scope(
            engine, root, mode, candidate, digest_scope
        )
        candidate.pop("workspace", None)
        candidate["scope"] = normalized_scope

        refs = candidate.get("evidence_refs")
        if refs is None:
            refs = []
        if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
            raise ValueError(f"promotion candidate {index} evidence_refs must be a sequence")
        normalized_refs = []
        for ref_index, raw_ref in enumerate(refs):
            if not isinstance(raw_ref, str) or not raw_ref.strip():
                raise ValueError(
                    f"promotion candidate {index} evidence_refs[{ref_index}] must be a non-empty string"
                )
            ref = raw_ref.strip()
            if ref not in allowed_refs:
                raise ValueError(
                    f"promotion candidate {index} evidence ref is not covered by the session digest: {ref}"
                )
            if ref not in normalized_refs:
                normalized_refs.append(ref)
        if digest_ref not in normalized_refs:
            normalized_refs.append(digest_ref)
        candidate["evidence_refs"] = normalized_refs

        source = candidate.get("source")
        if source in (None, ""):
            candidate["source"] = digest_ref
        elif not isinstance(source, str) or not source.strip():
            raise ValueError(f"promotion candidate {index} source must be a non-empty string")
        else:
            candidate["source"] = source.strip()

        effect_id = candidate.get("effect_id")
        if effect_id in (None, ""):
            effect_basis = dict(candidate)
            effect_basis.pop("effect_id", None)
            effect_id = "session-promotion:" + hashlib.sha256(
                (digest_id + "\n" + _stable_json(effect_basis)).encode("utf-8")
            ).hexdigest()[:32]
            candidate["effect_id"] = effect_id
        elif not isinstance(effect_id, str) or not effect_id.strip():
            raise ValueError(f"promotion candidate {index} effect_id must be a non-empty string")
        else:
            candidate["effect_id"] = effect_id.strip()

        prepared.append(candidate)
    return prepared


def _install(engine, capture_candidate):
    def promote_session_digest(
        digest_id: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not isinstance(digest_id, str) or not digest_id.strip():
            raise ValueError("digest_id must be a non-empty string")
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        requested_scope = _normalized_scope(engine, root, mode, scope, workspace)
        digest = engine.read_session_digest(
            digest_id.strip(),
            scope=requested_scope,
            root=root,
            mode=mode,
        )
        prepared = _prepare_candidates(engine, digest, candidates, root, mode)

        results = []
        counts = {"captured": 0, "existing": 0, "ignored": 0, "blocked": 0}
        for index, candidate in enumerate(prepared):
            result = capture_candidate(candidate, root=root, mode=mode)
            state = str(result.get("state") or "blocked")
            if state not in counts:
                state = "blocked"
            counts[state] += 1
            results.append(
                {
                    "index": index,
                    "type": candidate.get("type"),
                    **result,
                }
            )

        return {
            "digest_id": digest["id"],
            "scope": digest["scope"],
            "attempted": len(prepared),
            **counts,
            "results": results,
        }

    return promote_session_digest


def apply(engine, capture_candidate) -> None:
    required = ("read_session_digest", "normalize_scope", "repository_root", "detect_mode")
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError(
            "Session promotion requires Memory digest/runtime helpers: " + ", ".join(missing)
        )
    engine.promote_session_digest = _install(engine, capture_candidate)
    engine.MAX_PROMOTIONS_PER_DIGEST = MAX_PROMOTIONS_PER_DIGEST
