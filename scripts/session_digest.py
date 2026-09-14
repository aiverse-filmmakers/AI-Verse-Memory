"""First-class durable session-digest storage for AI-Verse Memory.

A session digest is compact historical context. It is not a transcript and it
does not replace Gateway-owned raw conversation history. This module installs a
small public API onto the established Memory engine after public-beta hardening
has attached the canonical mutation/idempotency helpers.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

SESSION_DIGEST_SCHEMA = 1
MAX_TOPIC_CHARS = 240
MAX_SUMMARY_CHARS = 6000
MAX_ITEM_CHARS = 1200
MAX_ITEMS = 24
MAX_REF_CHARS = 2048
MAX_REFS = 96
MAX_PROVENANCE_CHARS = 4096
MAX_RENDERED_BYTES = 32 * 1024

_DIGEST_ID_RE = re.compile(r"^sdg-[a-f0-9]{32}$")


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _required_identifier(label: str, value: object, *, max_chars: int = 512) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if len(cleaned) > max_chars:
        raise ValueError(f"{label} exceeds {max_chars} characters")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"{label} contains control characters")
    return cleaned


def _optional_identifier(label: str, value: object, *, max_chars: int = 512) -> str:
    if value is None or value == "":
        return ""
    return _required_identifier(label, value, max_chars=max_chars)


def _bounded_text(label: str, value: object, *, max_chars: int, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    cleaned = value.strip()
    if required and not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if len(cleaned) > max_chars:
        raise ValueError(f"{label} exceeds {max_chars} characters")
    return cleaned


def _bounded_list(
    label: str,
    values: Optional[Sequence[object]],
    *,
    max_items: int,
    max_chars: int,
) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{label} must be a sequence of strings")
    if len(values) > max_items:
        raise ValueError(f"{label} may contain at most {max_items} items")
    result: list[str] = []
    seen = set()
    for raw in values:
        if not isinstance(raw, str):
            raise ValueError(f"{label} entries must be strings")
        item = " ".join(raw.replace("\r", " ").replace("\n", " ").split()).strip()
        if not item:
            continue
        if len(item) > max_chars:
            raise ValueError(f"{label} entry exceeds {max_chars} characters")
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _normalized_provenance(value: Optional[Mapping[str, object]]) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("provenance must be an object")
    normalized: Dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = _required_identifier("provenance key", str(raw_key), max_chars=128)
        if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            normalized[key] = raw_value
        elif isinstance(raw_value, Sequence) and not isinstance(raw_value, (str, bytes)):
            items = []
            for item in raw_value:
                if not isinstance(item, (str, int, float, bool)) and item is not None:
                    raise ValueError("provenance arrays may contain only scalar values")
                items.append(item)
            normalized[key] = items
        else:
            raise ValueError("provenance values must be scalars or scalar arrays")
    encoded = _stable_json(normalized)
    if len(encoded) > MAX_PROVENANCE_CHARS:
        raise ValueError(f"provenance exceeds {MAX_PROVENANCE_CHARS} characters")
    return normalized


def _normalized_payload(
    engine,
    *,
    session_id: str,
    summary: str,
    run_id: str,
    scope: str,
    topic: str,
    unresolved_items: Optional[Sequence[object]],
    significant_outcomes: Optional[Sequence[object]],
    source_refs: Optional[Sequence[object]],
    provenance: Optional[Mapping[str, object]],
    source_coverage: Optional[Sequence[object]],
    source_fingerprint: str,
    source_version: str,
    completed_at: str,
    root: Path,
    mode: str,
) -> Dict[str, Any]:
    normalized_scope = engine.normalize_scope(scope, root, mode)
    refs = _bounded_list("source_refs", source_refs, max_items=MAX_REFS, max_chars=MAX_REF_CHARS)
    if not refs:
        raise ValueError("source_refs must contain at least one authoritative source reference")
    coverage = _bounded_list(
        "source_coverage",
        source_coverage if source_coverage is not None else refs,
        max_items=MAX_REFS,
        max_chars=MAX_REF_CHARS,
    )
    if not coverage:
        raise ValueError("source_coverage must contain at least one covered source reference")
    return {
        "schema_version": SESSION_DIGEST_SCHEMA,
        "session_id": _required_identifier("session_id", session_id),
        "run_id": _optional_identifier("run_id", run_id),
        "scope": normalized_scope,
        "topic": _bounded_text("topic", topic, max_chars=MAX_TOPIC_CHARS, required=True),
        "summary": _bounded_text("summary", summary, max_chars=MAX_SUMMARY_CHARS, required=True),
        "unresolved_items": _bounded_list(
            "unresolved_items", unresolved_items, max_items=MAX_ITEMS, max_chars=MAX_ITEM_CHARS
        ),
        "significant_outcomes": _bounded_list(
            "significant_outcomes", significant_outcomes, max_items=MAX_ITEMS, max_chars=MAX_ITEM_CHARS
        ),
        "source_refs": refs,
        "provenance": _normalized_provenance(provenance),
        "source_coverage": coverage,
        "source_fingerprint": _optional_identifier(
            "source_fingerprint", source_fingerprint, max_chars=512
        ),
        "source_version": _optional_identifier("source_version", source_version, max_chars=512),
        # Empty means "the caller did not assert a canonical completion time".
        # The stored display value may use created_at, but idempotency is based on
        # this caller-supplied value so retries without a timestamp remain stable.
        "completed_at": _optional_identifier("completed_at", completed_at, max_chars=128),
    }


def _digest_id(payload: Mapping[str, Any]) -> str:
    identity = "\n".join(
        [
            str(payload["scope"]),
            str(payload["session_id"]),
            str(payload.get("run_id") or ""),
            str(payload.get("source_version") or ""),
        ]
    )
    return "sdg-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _digest_root(engine, root: Path, mode: str, scope: str, *, create: bool) -> Path:
    if mode == engine.MODE_NATIVE:
        memory = engine.public_beta_native_memory_base(root, scope)
        return engine.public_beta_safe_child_dir(memory, "session-digests", create=create)

    home = engine.public_beta_standalone_home(root)
    top = engine.public_beta_safe_child_dir(home, "session-digests", create=create)
    if not top.exists():
        return top / hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
    bucket = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
    return engine.public_beta_safe_child_dir(top, bucket, create=create)


def _digest_path(
    engine,
    root: Path,
    mode: str,
    scope: str,
    digest_id: str,
    *,
    create: bool,
) -> Path:
    if not _DIGEST_ID_RE.fullmatch(digest_id):
        raise ValueError("Invalid session digest id")
    base = _digest_root(engine, root, mode, scope, create=create)
    shard_name = digest_id[4:6]
    if base.exists():
        shard = engine.public_beta_safe_child_dir(base, shard_name, create=create)
    else:
        shard = base / shard_name
    target = shard / f"{digest_id}.md"
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise RuntimeError(f"Unsafe session digest destination: {target}")
    if shard.exists():
        base_real = base.resolve(strict=True)
        try:
            shard.resolve(strict=True).relative_to(base_real)
        except ValueError as exc:
            raise RuntimeError(f"Session digest destination escapes canonical scope: {target}") from exc
    return target


def _render_list(items: Iterable[str]) -> str:
    items = list(items)
    if not items:
        return "_None._"
    return "\n".join(f"- {item}" for item in items)


def _render_digest(engine, digest_id: str, payload: Mapping[str, Any], *, created_at: str, fingerprint: str) -> str:
    completed_at = str(payload.get("completed_at") or created_at)
    meta = {
        "id": digest_id,
        "type": "session_digest",
        "schema_version": str(SESSION_DIGEST_SCHEMA),
        "scope": str(payload["scope"]),
        "status": "active",
        "session_id": str(payload["session_id"]),
        "run_id": str(payload.get("run_id") or ""),
        "topic": str(payload["topic"]),
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": completed_at,
        "source_refs": _stable_json(payload["source_refs"]),
        "source_coverage": _stable_json(payload["source_coverage"]),
        "source_fingerprint": str(payload.get("source_fingerprint") or ""),
        "source_version": str(payload.get("source_version") or ""),
        "provenance": _stable_json(payload["provenance"]),
        "digest_fingerprint": fingerprint,
    }
    body = (
        "# Session digest\n\n"
        "## Summary\n\n"
        f"{payload['summary']}\n\n"
        "## Significant outcomes\n\n"
        f"{_render_list(payload['significant_outcomes'])}\n\n"
        "## Unresolved items\n\n"
        f"{_render_list(payload['unresolved_items'])}\n"
    )
    rendered = engine.render_frontmatter(meta) + "\n\n" + body
    if len(rendered.encode("utf-8")) > MAX_RENDERED_BYTES:
        raise ValueError(f"Rendered session digest exceeds {MAX_RENDERED_BYTES} bytes")
    return rendered


def _json_list(meta: Mapping[str, str], key: str) -> list[str]:
    raw = meta.get(key) or "[]"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Session digest has invalid {key}") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise RuntimeError(f"Session digest has invalid {key}")
    return value


def _json_object(meta: Mapping[str, str], key: str) -> Dict[str, Any]:
    raw = meta.get(key) or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Session digest has invalid {key}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Session digest has invalid {key}")
    return value


def _section(body: str, heading: str, next_heading: Optional[str]) -> str:
    marker = f"## {heading}\n"
    start = body.find(marker)
    if start < 0:
        raise RuntimeError(f"Session digest is missing {heading}")
    start += len(marker)
    if next_heading is None:
        value = body[start:]
    else:
        stop = body.find(f"## {next_heading}\n", start)
        if stop < 0:
            raise RuntimeError(f"Session digest is missing {next_heading}")
        value = body[start:stop]
    return value.strip()


def _bullet_section(body: str, heading: str, next_heading: Optional[str]) -> list[str]:
    value = _section(body, heading, next_heading)
    if value == "_None._":
        return []
    result = []
    for line in value.splitlines():
        if line.startswith("- "):
            result.append(line[2:].strip())
    return result


def _read_path(engine, path: Path, root: Path, mode: str, expected_scope: str, expected_id: str) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Session digest not found: {expected_id}")
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Unsafe session digest file: {path}")

    base = _digest_root(engine, root, mode, expected_scope, create=False)
    if not base.exists():
        raise FileNotFoundError(f"Session digest not found: {expected_id}")
    try:
        path.resolve(strict=True).relative_to(base.resolve(strict=True))
    except ValueError as exc:
        raise RuntimeError("Session digest file escapes canonical scope") from exc

    meta, body = engine.parse_markdown(path)
    if meta.get("type") != "session_digest":
        raise RuntimeError("File is not an AI-Verse session digest")
    if meta.get("id") != expected_id:
        raise RuntimeError("Session digest identity mismatch")
    declared_scope = engine.normalize_scope(meta.get("scope"), root, mode)
    if declared_scope != expected_scope:
        raise RuntimeError("Session digest scope mismatch")

    summary = _section(body, "Summary", "Significant outcomes")
    outcomes = _bullet_section(body, "Significant outcomes", "Unresolved items")
    unresolved = _bullet_section(body, "Unresolved items", None)

    return {
        "id": expected_id,
        "type": "session_digest",
        "schema_version": int(meta.get("schema_version") or SESSION_DIGEST_SCHEMA),
        "scope": declared_scope,
        "status": meta.get("status") or "active",
        "session_id": meta.get("session_id") or "",
        "run_id": meta.get("run_id") or "",
        "topic": meta.get("topic") or "",
        "summary": summary,
        "significant_outcomes": outcomes,
        "unresolved_items": unresolved,
        "source_refs": _json_list(meta, "source_refs"),
        "source_coverage": _json_list(meta, "source_coverage"),
        "source_fingerprint": meta.get("source_fingerprint") or "",
        "source_version": meta.get("source_version") or "",
        "provenance": _json_object(meta, "provenance"),
        "digest_fingerprint": meta.get("digest_fingerprint") or "",
        "created_at": meta.get("created_at") or "",
        "updated_at": meta.get("updated_at") or "",
        "completed_at": meta.get("completed_at") or "",
        "path": engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path),
    }


def _record_effect(engine, root: Path, mode: str, effect_id: str, input_digest: str, digest_id: str, path: Path) -> None:
    if not effect_id:
        return
    receipt = engine.public_beta_effect_path(root, mode, effect_id)
    engine.public_beta_atomic_write_json(
        receipt,
        {
            "schema_version": SESSION_DIGEST_SCHEMA,
            "effect_id": effect_id,
            "operation": "session_digest",
            "input_digest": input_digest,
            "digest_id": digest_id,
            "path": engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path),
            "completed_at": engine.now_iso(),
        },
    )


def _install_write(engine):
    def write_session_digest(
        session_id: str,
        summary: str,
        *,
        run_id: str = "",
        scope: Optional[str] = None,
        topic: str,
        unresolved_items: Optional[Sequence[object]] = None,
        significant_outcomes: Optional[Sequence[object]] = None,
        source_refs: Optional[Sequence[object]] = None,
        provenance: Optional[Mapping[str, object]] = None,
        source_coverage: Optional[Sequence[object]] = None,
        source_fingerprint: str = "",
        source_version: str = "",
        completed_at: str = "",
        root: Optional[Path] = None,
        mode: Optional[str] = None,
        effect_id: str = "",
    ):
        """Persist one immutable compact digest.

        Raw transcript/messages are intentionally not accepted by this API.
        """

        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        normalized_scope = engine.normalize_scope(scope, root, mode)
        payload = _normalized_payload(
            engine,
            session_id=session_id,
            summary=summary,
            run_id=run_id,
            scope=normalized_scope,
            topic=topic,
            unresolved_items=unresolved_items,
            significant_outcomes=significant_outcomes,
            source_refs=source_refs,
            provenance=provenance,
            source_coverage=source_coverage,
            source_fingerprint=source_fingerprint,
            source_version=source_version,
            completed_at=completed_at,
            root=root,
            mode=mode,
        )
        digest_id = _digest_id(payload)
        fingerprint = engine.public_beta_payload_digest(payload)
        effect_payload = {"operation": "session_digest", "digest": payload}
        effect_digest = engine.public_beta_payload_digest(effect_payload)

        with engine.public_beta_mutation_lock(root, mode):
            engine.public_beta_assert_writable_authority(root, mode)
            existing_effect = engine.public_beta_load_effect(root, mode, effect_id, effect_digest)
            target = _digest_path(engine, root, mode, normalized_scope, digest_id, create=True)

            if existing_effect:
                if existing_effect.get("operation") != "session_digest":
                    raise RuntimeError(f"Idempotency key {effect_id!r} belongs to a different Memory operation")
                if existing_effect.get("digest_id") != digest_id:
                    raise RuntimeError("Session digest effect receipt identity mismatch")
                record = _read_path(engine, target, root, mode, normalized_scope, digest_id)
                if record["digest_fingerprint"] != fingerprint:
                    raise RuntimeError("Session digest effect points to changed canonical content")
                return digest_id, target, False

            if target.exists():
                record = _read_path(engine, target, root, mode, normalized_scope, digest_id)
                if record["digest_fingerprint"] != fingerprint:
                    raise RuntimeError(
                        "Session digest identity already exists with different content; "
                        "use a distinct run_id or source_version for a new immutable digest"
                    )
                _record_effect(engine, root, mode, effect_id, effect_digest, digest_id, target)
                return digest_id, target, False

            created_at = engine.now_iso()
            rendered = _render_digest(
                engine,
                digest_id,
                payload,
                created_at=created_at,
                fingerprint=fingerprint,
            )
            engine.public_beta_atomic_write_text(target, rendered)
            # Re-read under the same lock so malformed writes never get an effect receipt.
            _read_path(engine, target, root, mode, normalized_scope, digest_id)
            _record_effect(engine, root, mode, effect_id, effect_digest, digest_id, target)
            return digest_id, target, True

    return write_session_digest


def _install_read(engine):
    def read_session_digest(
        digest_id: str,
        *,
        scope: Optional[str] = None,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        normalized_scope = engine.normalize_scope(scope, root, mode)
        path = _digest_path(engine, root, mode, normalized_scope, digest_id, create=False)
        return _read_path(engine, path, root, mode, normalized_scope, digest_id)

    return read_session_digest


def _install_list(engine):
    def list_session_digests(
        *,
        scope: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 20,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        wanted_session = (
            _required_identifier("session_id", session_id) if session_id is not None else None
        )
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        normalized_scope = engine.normalize_scope(scope, root, mode)
        base = _digest_root(engine, root, mode, normalized_scope, create=False)
        if not base.exists():
            return []
        if base.is_symlink() or not base.is_dir():
            raise RuntimeError(f"Unsafe session digest directory: {base}")

        records: list[Dict[str, Any]] = []
        for shard in sorted(base.iterdir()):
            if shard.is_symlink() or not shard.is_dir():
                continue
            try:
                shard.resolve(strict=True).relative_to(base.resolve(strict=True))
            except ValueError:
                continue
            for path in sorted(shard.glob("sdg-*.md")):
                if path.is_symlink() or not path.is_file():
                    continue
                digest_id = path.stem
                if not _DIGEST_ID_RE.fullmatch(digest_id):
                    continue
                try:
                    record = _read_path(engine, path, root, mode, normalized_scope, digest_id)
                except (FileNotFoundError, RuntimeError, ValueError):
                    continue
                if wanted_session is not None and record["session_id"] != wanted_session:
                    continue
                records.append(record)

        records.sort(
            key=lambda row: (
                row.get("completed_at") or row.get("created_at") or "",
                row.get("id") or "",
            ),
            reverse=True,
        )
        return records[:limit]

    return list_session_digests


def apply(engine) -> None:
    """Attach the session-digest API to the established Memory engine."""

    required = (
        "public_beta_mutation_lock",
        "public_beta_atomic_write_text",
        "public_beta_atomic_write_json",
        "public_beta_assert_writable_authority",
        "public_beta_payload_digest",
        "public_beta_effect_path",
        "public_beta_load_effect",
        "public_beta_safe_child_dir",
        "public_beta_native_memory_base",
        "public_beta_standalone_home",
    )
    missing = [name for name in required if not hasattr(engine, name)]
    if missing:
        raise RuntimeError("Session digest hardening helpers are missing: " + ", ".join(missing))

    engine.write_session_digest = _install_write(engine)
    engine.read_session_digest = _install_read(engine)
    engine.list_session_digests = _install_list(engine)
    engine.SESSION_DIGEST_SCHEMA = SESSION_DIGEST_SCHEMA

    index_path = Path(__file__).resolve().parent / "session_digest_index.py"
    if index_path.exists():
        module_name = "_aiverse_memory_session_digest_index"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(module_name, index_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not load session digest index extension: {index_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        module.apply(engine, sys.modules[__name__])

    orientation_path = Path(__file__).resolve().parent / "orientation_map.py"
    if orientation_path.exists():
        module_name = "_aiverse_memory_orientation_map"
        orientation = sys.modules.get(module_name)
        if orientation is None:
            spec = importlib.util.spec_from_file_location(module_name, orientation_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not load orientation map extension: {orientation_path}")
            orientation = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = orientation
            spec.loader.exec_module(orientation)
        orientation.apply(engine)

    progressive_path = Path(__file__).resolve().parent / "progressive_recall.py"
    if progressive_path.exists():
        module_name = "_aiverse_memory_progressive_recall"
        progressive = sys.modules.get(module_name)
        if progressive is None:
            spec = importlib.util.spec_from_file_location(module_name, progressive_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(
                    f"Could not load progressive recall extension: {progressive_path}"
                )
            progressive = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = progressive
            spec.loader.exec_module(progressive)
        progressive.apply(engine)

    relationships_path = Path(__file__).resolve().parent / "relationship_projection.py"
    if relationships_path.exists():
        module_name = "_aiverse_memory_relationship_projection"
        relationships = sys.modules.get(module_name)
        if relationships is None:
            spec = importlib.util.spec_from_file_location(module_name, relationships_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(
                    f"Could not load relationship projection extension: {relationships_path}"
                )
            relationships = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = relationships
            spec.loader.exec_module(relationships)
        relationships.apply(engine)
