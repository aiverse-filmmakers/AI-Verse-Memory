"""Bounded Purpose-relevant historical read surface for AI-Verse Memory."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

PURPOSE_HISTORY_VERSION = "memory.purpose-history.v1"
DEFAULT_LIMIT = 8
MAX_LIMIT = 20
DEFAULT_MAX_BYTES = 8192
MIN_MAX_BYTES = 2048
MAX_MAX_BYTES = 32768
DEFAULT_MAX_AGE_DAYS = 90
MAX_MAX_AGE_DAYS = 3650
MAX_PURPOSE_REFS = 32
MAX_QUERY_CHARS = 4096
EXCERPT_CHARS = 640


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _serialized_bytes(value: object) -> int:
    return len(_stable_json(value).encode("utf-8"))


def _parse_time(value: object) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _row_value(row, key: str, default: Any = "") -> Any:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _canonical_ref(ref: Mapping[str, Any], scope: str, index: int) -> Dict[str, str]:
    if not isinstance(ref, Mapping):
        raise ValueError(f"purpose_refs[{index}] must be an object")
    owner = str(ref.get("owner") or "").strip()
    ref_scope = str(ref.get("scope") or "").strip()
    kind = str(ref.get("kind") or "").strip()
    ref_id = str(ref.get("id") or "").strip()
    if not all((owner, ref_scope, kind, ref_id)):
        raise ValueError(f"purpose_refs[{index}] must contain owner, scope, kind, and id")
    if ref_scope != scope:
        raise ValueError(f"purpose_refs[{index}] scope {ref_scope!r} does not match request scope {scope!r}")
    result = {"owner": owner, "scope": ref_scope, "kind": kind, "id": ref_id}
    version = ref.get("version")
    if version is not None:
        if not isinstance(version, str) or not version:
            raise ValueError(f"purpose_refs[{index}].version must be a non-empty string")
        result["version"] = version
    return result


def _validate(
    *,
    scope: str,
    purpose_refs: Sequence[Mapping[str, Any]],
    query: str,
    limit: int,
    max_bytes: int,
    max_age_days: int,
) -> tuple[List[Dict[str, str]], str, int, int, int]:
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("Purpose history scope must be a non-empty string")
    scope = scope.strip()
    if scope != "operator" and not scope.startswith("workspace:"):
        raise ValueError("Purpose history scope must be operator or workspace:<id>")
    if not isinstance(purpose_refs, Sequence) or isinstance(purpose_refs, (str, bytes)):
        raise ValueError("purpose_refs must be an array")
    if not 1 <= len(purpose_refs) <= MAX_PURPOSE_REFS:
        raise ValueError(f"purpose_refs must contain between 1 and {MAX_PURPOSE_REFS} refs")
    refs = [_canonical_ref(ref, scope, index) for index, ref in enumerate(purpose_refs)]
    refs.sort(key=lambda ref: (ref["owner"], ref["scope"], ref["kind"], ref["id"], ref.get("version", "")))

    if not isinstance(query, str) or not query.strip():
        raise ValueError("Purpose history query must be non-empty and derived from active Purpose context")
    query = query.strip()
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"Purpose history query must be at most {MAX_QUERY_CHARS} characters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"Purpose history limit must be between 1 and {MAX_LIMIT}")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not MIN_MAX_BYTES <= max_bytes <= MAX_MAX_BYTES:
        raise ValueError(f"Purpose history max_bytes must be between {MIN_MAX_BYTES} and {MAX_MAX_BYTES}")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or not 1 <= max_age_days <= MAX_MAX_AGE_DAYS:
        raise ValueError(f"Purpose history max_age_days must be between 1 and {MAX_MAX_AGE_DAYS}")
    return refs, query, limit, max_bytes, max_age_days


def _history_item(row) -> Dict[str, Any]:
    text = str(_row_value(row, "text"))
    clipped = len(text) > EXCERPT_CHARS
    excerpt = text[:EXCERPT_CHARS].rstrip()
    if clipped and excerpt:
        excerpt += "…"
    item = {
        "id": str(_row_value(row, "id")),
        "type": str(_row_value(row, "type")),
        "scope": str(_row_value(row, "scope")),
        "occurred_at": str(_row_value(row, "updated_at") or _row_value(row, "created_at")),
        "excerpt": excerpt,
    }
    if clipped:
        item["content_truncated"] = True
    return item


def apply(engine) -> None:
    if not hasattr(engine, "recall"):
        raise RuntimeError("Purpose history requires the established Memory recall owner surface")

    def read_purpose_history(
        *,
        scope: str,
        purpose_refs: Sequence[Mapping[str, Any]],
        query: str,
        limit: int = DEFAULT_LIMIT,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_age_days: int = DEFAULT_MAX_AGE_DAYS,
        now: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        refs, query_value, limit_value, budget, age_days = _validate(
            scope=scope,
            purpose_refs=purpose_refs,
            query=query,
            limit=limit,
            max_bytes=max_bytes,
            max_age_days=max_age_days,
        )
        observed = _parse_time(now) if now is not None else datetime.now(timezone.utc)
        if observed is None:
            raise ValueError("Purpose history now must be a valid ISO-8601 timestamp")
        cutoff = observed - timedelta(days=age_days)
        workspace = scope.split(":", 1)[1] if scope.startswith("workspace:") else None

        rows = engine.recall(
            query_value,
            scope=scope,
            workspace=workspace,
            limit=min(50, max(limit_value * 4, limit_value)),
            include_history=False,
            root=root,
            mode=mode,
            all_workspaces=False,
        )

        eligible = []
        for row in rows:
            if str(_row_value(row, "kind")) != "memory":
                continue
            if str(_row_value(row, "scope")) != scope:
                continue
            occurred = _parse_time(_row_value(row, "updated_at") or _row_value(row, "created_at"))
            if occurred is None or occurred < cutoff or occurred > observed:
                continue
            eligible.append((occurred, str(_row_value(row, "id")), row))
        eligible.sort(key=lambda item: (-item[0].timestamp(), item[1]))

        response: Dict[str, Any] = {
            "api_version": PURPOSE_HISTORY_VERSION,
            "scope": scope,
            "query": query_value,
            "purpose_refs": refs,
            "max_age_days": age_days,
            "limit": limit_value,
            "budget_bytes": budget,
            "history": [],
            "truncated": False,
        }
        candidates = eligible[:limit_value]
        response["truncated"] = len(eligible) > len(candidates)
        for _, _, row in candidates:
            item = _history_item(row)
            response["history"].append(item)
            if _serialized_bytes(response) > budget:
                response["history"].pop()
                response["truncated"] = True
                break
        response["returned"] = len(response["history"])
        response["candidate_count"] = len(eligible)
        if _serialized_bytes(response) > budget:
            raise ValueError(f"Purpose history envelope cannot fit configured budget {budget}")
        return response

    engine.read_purpose_history = read_purpose_history
    engine.PURPOSE_HISTORY_VERSION = PURPOSE_HISTORY_VERSION
    engine.PURPOSE_HISTORY_DEFAULT_LIMIT = DEFAULT_LIMIT
    engine.PURPOSE_HISTORY_MAX_LIMIT = MAX_LIMIT
    engine.PURPOSE_HISTORY_DEFAULT_MAX_BYTES = DEFAULT_MAX_BYTES
