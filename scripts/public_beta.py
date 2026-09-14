#!/usr/bin/env python3
"""Public-beta hardening for the existing AI-Verse Memory engine.

This module deliberately does not replace the Markdown + rebuildable SQLite
architecture. It strengthens the existing owner boundary with write
containment, serialized canonical mutation, retry-safe effects, and
snapshot-bound legacy adoption.
"""

from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

PUBLIC_BETA_SCHEMA = 1
LOCK_STALE_SECONDS = 600
LOCK_WAIT_SECONDS = 10
_LOCK_LOCAL = threading.local()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _payload_digest(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return _sha256_bytes(raw)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise RuntimeError(f"Unsafe canonical file destination: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise RuntimeError(f"Canonical file destination became unsafe: {path}")
        os.replace(temp_name, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
        except (AttributeError, OSError):
            dir_fd = None
        if dir_fd is not None:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
            finally:
                os.close(dir_fd)
    finally:
        try:
            Path(temp_name).unlink()
        except FileNotFoundError:
            pass


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_json(path: Path, payload: object) -> None:
    _atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _safe_existing_dir(path: Path, label: str) -> Path:
    if not path.exists():
        raise RuntimeError(f"Required {label} does not exist: {path}")
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Unsafe {label}: expected real directory, found {path}")
    return path.resolve(strict=True)


def _safe_child_dir(parent: Path, name: str, *, create: bool = True) -> Path:
    if parent.is_symlink() or not parent.is_dir():
        raise RuntimeError(f"Unsafe canonical parent directory: {parent}")
    parent_real = parent.resolve(strict=True)
    child = parent / name
    if child.exists():
        if child.is_symlink() or not child.is_dir():
            raise RuntimeError(f"Unsafe canonical directory: {child}")
    elif create:
        try:
            child.mkdir(mode=0o700)
        except FileExistsError:
            # Another serialized contender may have created the same owner
            # directory between the existence check and mkdir. Revalidate it.
            if child.is_symlink() or not child.is_dir():
                raise RuntimeError(f"Unsafe canonical directory: {child}")
    else:
        return child
    child_real = child.resolve(strict=True)
    try:
        child_real.relative_to(parent_real)
    except ValueError as exc:
        raise RuntimeError(f"Canonical directory escapes owner boundary: {child}") from exc
    return child


def _native_atomic_base(engine, root: Path, scope: str) -> Path:
    root = Path(root).resolve(strict=True)
    operator = root / "operator"
    workspaces = root / "workspaces"
    _safe_existing_dir(operator, "operator root")
    _safe_existing_dir(workspaces, "workspace root")
    normalized = engine.normalize_scope(scope, root, engine.MODE_NATIVE)
    if normalized == "operator":
        owner = operator
    else:
        wid = normalized.split(":", 1)[1]
        owner = workspaces / wid
        _safe_existing_dir(owner, f"workspace {wid}")
        manifest = owner / "WORKSPACE.yaml"
        if not manifest.exists() or manifest.is_symlink() or not manifest.is_file():
            raise RuntimeError(f"Unsafe or missing workspace manifest: {manifest}")
    memory = _safe_child_dir(owner, "memory")
    atomic = _safe_child_dir(memory, "atomic")
    owner_real = owner.resolve(strict=True)
    try:
        atomic.resolve(strict=True).relative_to(owner_real)
    except ValueError as exc:
        raise RuntimeError(f"Atomic Memory path escapes canonical owner: {atomic}") from exc
    return atomic


def _standalone_home(engine, root: Path) -> Path:
    p = engine.paths(root, engine.MODE_STANDALONE)
    home = Path(p["home"])
    if home.exists():
        if home.is_symlink() or not home.is_dir():
            raise RuntimeError(f"Unsafe standalone Memory home: {home}")
    else:
        home.mkdir(parents=True, mode=0o700)
    return home


def _standalone_atomic_base(engine, root: Path) -> Path:
    home = _standalone_home(engine, root)
    return _safe_child_dir(home, "memories")


def _safe_atomic_path(engine, mem_id: str, created_at: str, scope: str, root: Path, mode: str) -> Path:
    if "/" in mem_id or "\\" in mem_id or mem_id in {".", ".."}:
        raise ValueError("Invalid memory id")
    normalized = engine.normalize_scope(scope, root, mode)
    base = (
        _native_atomic_base(engine, root, normalized)
        if mode == engine.MODE_NATIVE
        else _standalone_atomic_base(engine, root)
    )
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    year = _safe_child_dir(base, f"{dt.year:04d}")
    month = _safe_child_dir(year, f"{dt.month:02d}")
    target = month / f"{mem_id}.md"
    if target.exists() and target.is_symlink():
        raise RuntimeError(f"Unsafe canonical memory destination: {target}")
    base_real = base.resolve(strict=True)
    try:
        month.resolve(strict=True).relative_to(base_real)
    except ValueError as exc:
        raise RuntimeError(f"Memory destination escapes canonical scope: {target}") from exc
    return target


def _state_dir(engine, root: Path, mode: str) -> Path:
    if mode == engine.MODE_NATIVE:
        operator = Path(root).resolve(strict=True) / "operator"
        _safe_existing_dir(operator, "operator root")
        memory = _safe_child_dir(operator, "memory")
        return _safe_child_dir(memory, ".ai-verse-memory-state")
    home = _standalone_home(engine, root)
    return _safe_child_dir(home, "state")


def _lock_counts() -> Dict[str, int]:
    counts = getattr(_LOCK_LOCAL, "counts", None)
    if counts is None:
        counts = {}
        _LOCK_LOCAL.counts = counts
    return counts


def _lock_is_stale(lock: Path) -> bool:
    try:
        age = max(0.0, time.time() - lock.stat().st_mtime)
    except OSError:
        return False
    if age < LOCK_STALE_SECONDS:
        return False
    pid = 0
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
        pid = int(payload.get("pid") or 0)
    except Exception:
        pid = 0
    return not _pid_alive(pid)


@contextmanager
def _mutation_lock(engine, root: Path, mode: str):
    state = _state_dir(engine, root, mode)
    lock = state / "mutation.lock"
    key = str(lock.resolve(strict=False))
    counts = _lock_counts()
    if counts.get(key, 0):
        counts[key] += 1
        try:
            yield
        finally:
            counts[key] -= 1
        return

    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError as exc:
            if _lock_is_stale(lock):
                try:
                    lock.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for AI-Verse Memory canonical mutation lock: {lock}") from exc
            time.sleep(0.05)
        except OSError as exc:
            raise RuntimeError(f"Could not acquire Memory mutation lock: {exc}") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": PUBLIC_BETA_SCHEMA, "pid": os.getpid(), "created_at": _now_iso()}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        counts[key] = 1
        _recover_transactions(engine, root, mode)
        yield
    finally:
        counts.pop(key, None)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _assert_path_within(path: Path, boundary: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(boundary.resolve(strict=True))
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"Path escapes canonical Memory boundary: {path}") from exc


def _transaction_dir(engine, root: Path, mode: str) -> Path:
    state = _state_dir(engine, root, mode)
    return _safe_child_dir(state, "transactions")


def _recover_transactions(engine, root: Path, mode: str) -> None:
    tx_dir = _transaction_dir(engine, root, mode)
    boundary = Path(root).resolve(strict=True) if mode == engine.MODE_NATIVE else _standalone_home(engine, root).resolve(strict=True)
    for journal in sorted(tx_dir.glob("*.json")):
        if journal.is_symlink() or not journal.is_file():
            raise RuntimeError(f"Unsafe Memory transaction journal: {journal}")
        payload = json.loads(journal.read_text(encoding="utf-8"))
        if payload.get("schema_version") != PUBLIC_BETA_SCHEMA or payload.get("status") != "prepared":
            continue
        for effect in payload.get("files", []):
            target = Path(root) / effect["path"] if mode == engine.MODE_NATIVE else Path(effect["path"])
            _assert_path_within(target.parent, boundary)
            _atomic_write_text(target, effect["content"])
        journal.unlink()


def _write_transaction(engine, root: Path, mode: str, tx_id: str, files: Sequence[Tuple[Path, str]]) -> Path:
    tx_dir = _transaction_dir(engine, root, mode)
    payload_files = []
    for path, content in files:
        stored = engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path)
        payload_files.append({"path": stored, "content": content})
    journal = tx_dir / f"{tx_id}.json"
    _atomic_write_json(
        journal,
        {
            "schema_version": PUBLIC_BETA_SCHEMA,
            "operation": "supersede",
            "status": "prepared",
            "created_at": _now_iso(),
            "files": payload_files,
        },
    )
    return journal


def _effect_dir(engine, root: Path, mode: str) -> Path:
    state = _state_dir(engine, root, mode)
    return _safe_child_dir(state, "effects")


def _effect_path(engine, root: Path, mode: str, effect_id: str) -> Path:
    key = hashlib.sha256(effect_id.encode("utf-8")).hexdigest()
    return _effect_dir(engine, root, mode) / f"{key}.json"


def _load_effect(engine, root: Path, mode: str, effect_id: str, digest: str):
    if not effect_id:
        return None
    path = _effect_path(engine, root, mode, effect_id)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Unsafe Memory effect receipt: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("effect_id") != effect_id:
        raise RuntimeError("Memory effect receipt identity mismatch")
    if payload.get("input_digest") != digest:
        raise RuntimeError(f"Idempotency key {effect_id!r} was already used for a different Memory effect")
    return payload


def _record_effect(engine, root: Path, mode: str, effect_id: str, digest: str, mem_id: str, path: Path) -> None:
    if not effect_id:
        return
    receipt = _effect_path(engine, root, mode, effect_id)
    _atomic_write_json(
        receipt,
        {
            "schema_version": PUBLIC_BETA_SCHEMA,
            "effect_id": effect_id,
            "operation": "remember",
            "input_digest": digest,
            "memory_id": mem_id,
            "path": engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path),
            "completed_at": _now_iso(),
        },
    )


def _authority_file(engine, root: Path, mode: str) -> Path:
    if mode == engine.MODE_STANDALONE:
        return _standalone_home(engine, root) / "AUTHORITY.json"
    return _state_dir(engine, root, mode) / "authority-handoff.json"


def _assert_writable_authority(engine, root: Path, mode: str) -> None:
    if mode != engine.MODE_STANDALONE:
        return
    authority = _authority_file(engine, root, mode)
    if not authority.exists():
        return
    if authority.is_symlink() or not authority.is_file():
        raise RuntimeError(f"Unsafe standalone authority marker: {authority}")
    payload = json.loads(authority.read_text(encoding="utf-8"))
    if payload.get("status") == "retired":
        replacement = payload.get("replacement_root") or "the adopted AI-Verse OS"
        raise RuntimeError(
            "This standalone Memory store is retired and preserved as historical evidence. "
            f"Canonical writes moved to {replacement}."
        )


def _patched_write_atomic(engine, original_rebuild):
    def write_atomic(
        text: str,
        mem_type: str,
        scope: Optional[str] = None,
        importance: int = 3,
        confidence: float = 1.0,
        source: str = "",
        why: str = "",
        tags: str = "",
        valid_from: str = "",
        supersedes: str = "",
        force: bool = False,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
        effect_id: str = "",
        evidence_refs: Optional[Sequence[str]] = None,
    ):
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        if mem_type not in engine.MEMORY_TYPES:
            raise ValueError(f"Unsupported memory type: {mem_type}")
        text = text.strip()
        if not text:
            raise ValueError("Memory text cannot be empty")
        normalized_scope = engine.normalize_scope(scope, root, mode)
        refs = [str(item).strip() for item in (evidence_refs or []) if str(item).strip()]
        effect_payload = {
            "operation": "remember",
            "text": text,
            "type": mem_type,
            "scope": normalized_scope,
            "importance": int(importance),
            "confidence": float(confidence),
            "source": source,
            "why": why,
            "tags": tags,
            "valid_from": valid_from,
            "supersedes": supersedes,
            "evidence_refs": refs,
        }
        effect_digest = _payload_digest(effect_payload)

        with _mutation_lock(engine, root, mode):
            _assert_writable_authority(engine, root, mode)
            existing_effect = _load_effect(engine, root, mode, effect_id, effect_digest)
            if existing_effect:
                mem_id = str(existing_effect["memory_id"])
                path = engine.locate_memory(mem_id, root, mode)
                if not path:
                    raise RuntimeError(f"Idempotent Memory effect {effect_id!r} points to missing canonical memory")
                return mem_id, path, False

            duplicate = engine.find_exact_active(text, normalized_scope, root, mode)
            if duplicate and not force:
                path = root / duplicate[1] if mode == engine.MODE_NATIVE else Path(duplicate[1])
                _record_effect(engine, root, mode, effect_id, effect_digest, duplicate[0], path)
                return duplicate[0], path, False

            created = engine.now_iso()
            mem_id = engine.memory_id(text, normalized_scope)
            path = _safe_atomic_path(engine, mem_id, created, normalized_scope, root, mode)
            normalized_type = "state" if mem_type == "project_state" and mode == engine.MODE_NATIVE else mem_type
            meta = {
                "id": mem_id,
                "type": normalized_type,
                "scope": normalized_scope,
                "status": "active",
                "importance": str(max(1, min(5, int(importance)))),
                "confidence": f"{max(0.0, min(1.0, float(confidence))):.2f}",
                "created_at": created,
                "updated_at": created,
                "valid_from": valid_from,
                "valid_to": "",
                "supersedes": supersedes,
                "superseded_by": "",
                "source": source,
                "tags": tags,
            }
            if refs:
                meta["evidence_refs"] = json.dumps(refs, separators=(",", ":"))
            body = f"# Memory\n\n{text}\n"
            if why.strip():
                body += f"\n# Why it matters\n\n{why.strip()}\n"
            _atomic_write_text(path, engine.render_frontmatter(meta) + "\n\n" + body)
            original_rebuild(silent=True, root=root, mode=mode)
            _record_effect(engine, root, mode, effect_id, effect_digest, mem_id, path)
            return mem_id, path, True

    return write_atomic


def _root_and_mode_for_memory_path(engine, path: Path) -> Tuple[Path, str]:
    path = Path(path).absolute()
    for parent in [path.parent, *path.parents]:
        manifest = parent / "AI-VERSE.yaml"
        if manifest.exists():
            return parent.resolve(), engine.detect_mode(parent)
        if parent.name == ".ai-verse-memory":
            return parent.parent.resolve(), engine.MODE_STANDALONE
    root = engine.repository_root()
    return root, engine.detect_mode(root)


def _patched_update_meta(engine):
    def update_meta(path: Path, changes: Dict[str, str]) -> None:
        path = Path(path)
        root, mode = _root_and_mode_for_memory_path(engine, path)
        with _mutation_lock(engine, root, mode):
            _assert_writable_authority(engine, root, mode)
            if mode == engine.MODE_NATIVE:
                engine._native_source_identity(path, root, expected_kind="memory")
            else:
                _assert_path_within(path, _standalone_atomic_base(engine, root))
            meta, body = engine.parse_markdown(path)
            if not meta:
                raise ValueError(f"Not an AI-Verse atomic memory: {path}")
            meta.update(changes)
            meta["updated_at"] = engine.now_iso()
            _atomic_write_text(path, engine.render_frontmatter(meta) + "\n\n" + body.strip() + "\n")

    return update_meta


def _patched_forget(engine, original_rebuild):
    def forget_memory(mem_id: str, confirmed: bool, root: Optional[Path] = None, mode: Optional[str] = None) -> None:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        with _mutation_lock(engine, root, mode):
            _assert_writable_authority(engine, root, mode)
            path = engine.locate_memory(mem_id, root, mode)
            if not path:
                raise SystemExit(f"Memory not found: {mem_id}")
            if not confirmed:
                raise SystemExit(f"Refusing to delete {mem_id} without --yes. This removes canonical Markdown memory.")
            if mode == engine.MODE_NATIVE:
                engine._native_source_identity(path, root, expected_kind="memory")
            else:
                _assert_path_within(path, _standalone_atomic_base(engine, root))
            path.unlink()
            original_rebuild(silent=True, root=root, mode=mode)
            print(f"Forgot: {mem_id}")

    return forget_memory


def _patched_supersede(engine, original_rebuild):
    def supersede(args: argparse.Namespace, root: Path, mode: str) -> None:
        root = Path(root).resolve()
        with _mutation_lock(engine, root, mode):
            _assert_writable_authority(engine, root, mode)
            old_path = engine.locate_memory(args.id, root, mode)
            if not old_path:
                raise SystemExit(f"Memory not found: {args.id}")
            if mode == engine.MODE_NATIVE:
                engine._native_source_identity(old_path, root, expected_kind="memory")
            old_meta, old_body = engine.parse_markdown(old_path)
            new_type = args.type or old_meta.get("type", "fact")
            new_scope = args.scope or old_meta.get("scope") or engine.infer_scope_from_path(old_path, root, mode)
            if getattr(args, "workspace", None):
                new_scope = f"workspace:{args.workspace}"
            normalized_scope = engine.normalize_scope(new_scope, root, mode)
            created = engine.now_iso()
            new_id = engine.memory_id(args.text, normalized_scope)
            new_path = _safe_atomic_path(engine, new_id, created, normalized_scope, root, mode)
            new_meta = {
                "id": new_id,
                "type": "state" if new_type == "project_state" and mode == engine.MODE_NATIVE else new_type,
                "scope": normalized_scope,
                "status": "active",
                "importance": str(args.importance if args.importance is not None else int(old_meta.get("importance", "3") or 3)),
                "confidence": f"{args.confidence if args.confidence is not None else float(old_meta.get('confidence', '1') or 1):.2f}",
                "created_at": created,
                "updated_at": created,
                "valid_from": getattr(args, "valid_from", "") or "",
                "valid_to": "",
                "supersedes": args.id,
                "superseded_by": "",
                "source": getattr(args, "source", "") or "",
                "tags": getattr(args, "tags", "") or old_meta.get("tags", ""),
            }
            new_body = f"# Memory\n\n{args.text.strip()}\n"
            if getattr(args, "why", "").strip():
                new_body += f"\n# Why it matters\n\n{args.why.strip()}\n"
            new_content = engine.render_frontmatter(new_meta) + "\n\n" + new_body

            old_meta = dict(old_meta)
            old_meta.update({"status": "superseded", "valid_to": created, "superseded_by": new_id, "updated_at": created})
            old_content = engine.render_frontmatter(old_meta) + "\n\n" + old_body.strip() + "\n"
            tx_id = f"supersede-{hashlib.sha256((args.id + new_id).encode('utf-8')).hexdigest()[:24]}"
            journal = _write_transaction(engine, root, mode, tx_id, [(new_path, new_content), (old_path, old_content)])
            _atomic_write_text(new_path, new_content)
            _atomic_write_text(old_path, old_content)
            original_rebuild(silent=True, root=root, mode=mode)
            try:
                journal.unlink()
            except FileNotFoundError:
                pass
            print(f"Superseded: {args.id} -> {new_id}")
            print(engine.relpath(new_path, root))

    return supersede


def _patched_rebuild(engine, original_rebuild):
    def rebuild(silent: bool = False, root: Optional[Path] = None, mode: Optional[str] = None) -> int:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        with _mutation_lock(engine, root, mode):
            return original_rebuild(silent=silent, root=root, mode=mode)

    return rebuild


def _legacy_snapshot(engine, root: Path, source_root: Optional[Path]) -> dict:
    source_base, legacy = engine._legacy_source(root, source_root)
    old_memories = legacy / "memories"
    memories_real = old_memories.resolve(strict=True)
    records = []
    digest_rows = []
    counts = {"migratable": 0, "duplicate": 0, "unresolved": 0, "invalid": 0}
    for old_path in sorted(old_memories.rglob("*.md")):
        try:
            display_source = old_path.relative_to(source_base).as_posix()
        except ValueError:
            display_source = str(old_path)
        record = {"path": display_source}
        try:
            if old_path.is_symlink() or not old_path.is_file():
                raise ValueError("not a regular file")
            resolved_old = old_path.resolve(strict=True)
            resolved_old.relative_to(memories_real)
            file_sha = _sha256_file(old_path)
            meta, body = engine.parse_markdown(old_path)
            mem_id = meta.get("id")
            if not mem_id:
                raise ValueError("missing id")
            mapped = engine.map_legacy_scope(meta.get("scope", "global"), root)
            record.update(
                {
                    "file_sha256": file_sha,
                    "id": mem_id,
                    "legacy_scope": meta.get("scope", "global"),
                    "mapped_scope": mapped,
                }
            )
            if not mapped:
                record.update({"result": "unresolved", "reason": meta.get("scope", "")})
                counts["unresolved"] += 1
            else:
                existing = engine.locate_memory(mem_id, root, engine.MODE_NATIVE)
                if existing:
                    existing_meta, existing_body = engine.parse_markdown(existing)
                    if existing_meta.get("scope") == mapped and existing_body.strip() == body.strip():
                        record.update({"result": "duplicate", "reason": engine.relpath(existing, root)})
                        counts["duplicate"] += 1
                    else:
                        record.update({"result": "invalid", "reason": "destination id conflict"})
                        counts["invalid"] += 1
                else:
                    record.update({"result": "migratable", "reason": mapped})
                    counts["migratable"] += 1
        except (OSError, ValueError) as exc:
            record.update({"result": "invalid", "reason": str(exc), "file_sha256": None})
            counts["invalid"] += 1
        records.append(record)
        digest_rows.append(
            {
                "path": record.get("path"),
                "sha256": record.get("file_sha256"),
            }
        )
    source_fingerprint = _payload_digest(digest_rows)
    scope_fingerprint = _payload_digest(engine.workspace_ids(root))
    return {
        "schema_version": PUBLIC_BETA_SCHEMA,
        "source_root": str(source_base),
        "legacy_root": str(legacy),
        "source_fingerprint": source_fingerprint,
        "target_scope_fingerprint": scope_fingerprint,
        "records": records,
        "counts": counts,
    }


def _migration_paths(engine, root: Path) -> Tuple[Path, Path]:
    operator = Path(root).resolve(strict=True) / "operator"
    _safe_existing_dir(operator, "operator root")
    memory = _safe_child_dir(operator, "memory")
    report_dir = _safe_child_dir(memory, "migrations")
    return (
        report_dir / "legacy-ai-verse-memory-plan.json",
        report_dir / "legacy-ai-verse-memory-migration.md",
    )


def _write_migration_report(path: Path, snapshot: dict, applied: bool, copied: int, handoff_complete: bool) -> None:
    lines = [
        "# Legacy AI-Verse Memory Migration",
        "",
        f"Generated: {_now_iso()}",
        f"Applied: {'yes' if applied else 'no'}",
        f"Source: `{snapshot['legacy_root']}`",
        f"Source fingerprint: `{snapshot['source_fingerprint']}`",
        f"Authority handoff: {'complete' if handoff_complete else 'pending'}",
        "",
        "The source memory Markdown is preserved. After a verified handoff the old supported writer is retired, while the old bytes remain historical evidence.",
        "",
        "| Source | Result | Destination / note |",
        "|---|---|---|",
    ]
    for record in snapshot["records"]:
        lines.append(f"| `{record['path']}` | {record['result']} | `{record.get('reason', '')}` |")
    if copied:
        lines.extend(["", f"Copied this apply: {copied}"])
    _atomic_write_text(path, "\n".join(lines) + "\n")


def _retirement_stub(authority_file: Path) -> str:
    return f'''#!/usr/bin/env python3
"""Retired AI-Verse Memory standalone writer."""
from __future__ import annotations
import json
from pathlib import Path

authority = Path(__file__).with_name("AUTHORITY.json")
payload = json.loads(authority.read_text(encoding="utf-8")) if authority.exists() else {{}}
replacement = payload.get("replacement_root", "the adopted AI-Verse OS")
raise SystemExit(
    "This standalone AI-Verse Memory writer was retired after canonical authority handoff. "
    f"Use the adopted Memory at {{replacement}}. The old memory files remain preserved as evidence."
)
'''


def _retire_legacy_authority(engine, root: Path, snapshot: dict, counts: dict) -> dict:
    legacy = Path(snapshot["legacy_root"])
    handoff_id = "handoff-" + hashlib.sha256(
        (snapshot["source_fingerprint"] + "\n" + str(root.resolve())).encode("utf-8")
    ).hexdigest()[:24]
    receipt = {
        "schema_version": PUBLIC_BETA_SCHEMA,
        "handoff_id": handoff_id,
        "status": "complete",
        "completed_at": _now_iso(),
        "source_root": snapshot["source_root"],
        "legacy_root": snapshot["legacy_root"],
        "source_fingerprint": snapshot["source_fingerprint"],
        "target_root": str(root.resolve()),
        "target_scope_fingerprint": snapshot["target_scope_fingerprint"],
        "counts": counts,
    }
    native_authority = _authority_file(engine, root, engine.MODE_NATIVE)
    _atomic_write_json(native_authority, receipt)

    source_authority = legacy / "AUTHORITY.json"
    _atomic_write_json(
        source_authority,
        {
            "schema_version": PUBLIC_BETA_SCHEMA,
            "handoff_id": handoff_id,
            "status": "retired",
            "retired_at": receipt["completed_at"],
            "source_fingerprint": snapshot["source_fingerprint"],
            "replacement_root": str(root.resolve()),
            "reason": "Canonical Memory authority adopted by native AI-Verse Memory.",
        },
    )
    old_writer = legacy / "memory.py"
    if old_writer.exists():
        if old_writer.is_symlink() or not old_writer.is_file():
            raise RuntimeError(f"Cannot retire unsafe legacy Memory writer: {old_writer}")
        backup = legacy / "memory.py.pre-handoff"
        if not backup.exists():
            shutil.copy2(old_writer, backup)
        _atomic_write_text(old_writer, _retirement_stub(source_authority))
    return receipt


def _patched_migrate_legacy(engine, original_rebuild):
    def migrate_legacy(root: Path, apply: bool = False, source_root: Optional[Path] = None) -> Dict[str, int]:
        root = Path(root).resolve()
        if engine.detect_mode(root) != engine.MODE_NATIVE:
            raise ValueError("migrate-legacy is only for AI-Verse OS v2 native mode")
        with _mutation_lock(engine, root, engine.MODE_NATIVE):
            plan_path, report_path = _migration_paths(engine, root)
            snapshot = _legacy_snapshot(engine, root, source_root)
            base_counts = dict(snapshot["counts"])
            result_counts = {
                "migratable": base_counts["migratable"],
                "copied": 0,
                "duplicate": base_counts["duplicate"],
                "unresolved": base_counts["unresolved"],
                "invalid": base_counts["invalid"],
                "handoff_complete": 0,
            }
            if not apply:
                plan = dict(snapshot)
                plan["planned_at"] = _now_iso()
                _atomic_write_json(plan_path, plan)
                _write_migration_report(report_path, snapshot, False, 0, False)
                print(f"Legacy migration plan: {engine.relpath(plan_path, root)}")
                print(f"Legacy migration report: {engine.relpath(report_path, root)}")
                print(json.dumps(result_counts, indent=2))
                return result_counts

            if not plan_path.exists():
                raise ValueError("Migration apply requires a reviewed dry run first")
            if plan_path.is_symlink() or not plan_path.is_file():
                raise ValueError("Migration plan is unsafe")
            planned = json.loads(plan_path.read_text(encoding="utf-8"))
            if planned.get("source_root") != snapshot["source_root"]:
                raise ValueError("Migration source differs from the reviewed dry run; run dry run again")
            if planned.get("source_fingerprint") != snapshot["source_fingerprint"]:
                raise ValueError("Legacy Memory source drifted after dry run; review a new migration plan before apply")
            if planned.get("target_scope_fingerprint") != snapshot["target_scope_fingerprint"]:
                raise ValueError("Target workspace topology changed after dry run; review a new migration plan before apply")

            source_base = Path(snapshot["source_root"])
            legacy = Path(snapshot["legacy_root"])
            for record in snapshot["records"]:
                if record["result"] != "migratable":
                    continue
                old_path = source_base / record["path"]
                meta, body = engine.parse_markdown(old_path)
                mapped = str(record["mapped_scope"])
                mem_id = str(record["id"])
                existing = engine.locate_memory(mem_id, root, engine.MODE_NATIVE)
                if existing:
                    existing_meta, existing_body = engine.parse_markdown(existing)
                    if existing_meta.get("scope") == mapped and existing_body.strip() == body.strip():
                        result_counts["duplicate"] += 1
                        continue
                    raise ValueError(f"Destination id conflict during migration: {mem_id}")

                new_meta = dict(meta)
                old_scope = new_meta.get("scope", "global")
                new_meta["scope"] = mapped
                if old_scope != mapped:
                    new_meta["legacy_scope"] = old_scope
                display_source = str(record["path"])
                if not new_meta.get("source"):
                    new_meta["source"] = f"legacy:{display_source}"
                new_meta["migration_source_path"] = display_source
                new_meta["migration_source_sha256"] = str(record["file_sha256"])
                new_meta["migration_source_fingerprint"] = snapshot["source_fingerprint"]
                new_meta["migrated_at"] = _now_iso()
                created = new_meta.get("created_at") or _now_iso()
                target = _safe_atomic_path(engine, mem_id, created, mapped, root, engine.MODE_NATIVE)
                _atomic_write_text(target, engine.render_frontmatter(new_meta) + "\n\n" + body.strip() + "\n")
                result_counts["copied"] += 1

            original_rebuild(silent=True, root=root, mode=engine.MODE_NATIVE)

            blocking = result_counts["unresolved"] + result_counts["invalid"]
            if blocking == 0:
                for record in snapshot["records"]:
                    if record["result"] not in {"migratable", "duplicate"}:
                        continue
                    destination = engine.locate_memory(str(record["id"]), root, engine.MODE_NATIVE)
                    if not destination:
                        raise RuntimeError(f"Migration verification failed for {record['id']}")
                    meta, _ = engine.parse_markdown(destination)
                    if meta.get("scope") != record.get("mapped_scope"):
                        raise RuntimeError(f"Migration verification scope mismatch for {record['id']}")
                _retire_legacy_authority(engine, root, snapshot, result_counts)
                result_counts["handoff_complete"] = 1

            final_snapshot = _legacy_snapshot(engine, root, source_root)
            # Retirement metadata and writer stub are outside memories/, so the source-memory
            # fingerprint remains stable and proves the historical records were not rewritten.
            if final_snapshot["source_fingerprint"] != snapshot["source_fingerprint"]:
                raise RuntimeError("Legacy source memory bytes changed during migration")
            _write_migration_report(
                report_path,
                snapshot,
                True,
                result_counts["copied"],
                bool(result_counts["handoff_complete"]),
            )
            print(f"Legacy migration report: {engine.relpath(report_path, root)}")
            print(json.dumps(result_counts, indent=2))
            return result_counts

    return migrate_legacy


def _patched_migration_complete(engine):
    def migration_complete(summary: str, root: Optional[Path] = None, mode: Optional[str] = None) -> None:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        with _mutation_lock(engine, root, mode):
            p = engine.paths(root, mode)
            if mode == engine.MODE_NATIVE:
                plan_path, _ = _migration_paths(engine, root)
                legacy = root / ".ai-verse-memory"
                if plan_path.exists():
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                    handoff = _authority_file(engine, root, mode)
                    if not handoff.exists():
                        raise ValueError("Migration cannot be marked complete before canonical authority handoff")
                    receipt = json.loads(handoff.read_text(encoding="utf-8"))
                    if receipt.get("status") != "complete" or receipt.get("source_fingerprint") != plan.get("source_fingerprint"):
                        raise ValueError("Migration handoff receipt does not match the reviewed source snapshot")
                elif legacy.exists():
                    raise ValueError("Legacy Memory exists. Run migrate-legacy dry run and apply before marking migration complete.")
            payload = {
                "schema_version": PUBLIC_BETA_SCHEMA,
                "completed_at": _now_iso(),
                "version": engine.VERSION,
                "mode": mode,
                "summary": summary.strip() or "Initial historical-memory migration completed.",
            }
            _atomic_write_json(p["migration"], payload)
            print(f"Migration marked complete: {engine.relpath(p['migration'], root)}")

    return migration_complete


def component_state_path(engine, root: Path, mode: str) -> Path:
    if mode == engine.MODE_NATIVE:
        return Path(root) / "operator" / "memory" / ".ai-verse-memory-state" / "component.json"
    return Path(engine.paths(root, mode)["home"]) / "state" / "component.json"


def read_component_state(engine, root: Path, mode: str) -> dict:
    path = component_state_path(engine, root, mode)
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"Unsafe Memory component state: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_component_state(engine, root: Path, mode: str, **changes) -> dict:
    with _mutation_lock(engine, root, mode):
        payload = read_component_state(engine, root, mode)
        payload.update(
            {
                "schema_version": PUBLIC_BETA_SCHEMA,
                "component_id": "ai-verse-memory",
                "version": engine.VERSION,
                **changes,
            }
        )
        payload["updated_at"] = _now_iso()
        _atomic_write_json(component_state_path(engine, root, mode), payload)
        return payload


def apply(engine) -> None:
    """Patch only public-beta seams while preserving the existing engine model."""
    engine.MEMORY_TYPES.update({"lesson", "correction"})
    original_rebuild = engine.rebuild
    engine.atomic_path = lambda mem_id, created_at, scope, root=None, mode=None: _safe_atomic_path(
        engine,
        mem_id,
        created_at,
        scope,
        Path(root or engine.repository_root()).resolve(),
        mode or engine.detect_mode(root or engine.repository_root()),
    )
    engine.rebuild = _patched_rebuild(engine, original_rebuild)
    engine.write_atomic = _patched_write_atomic(engine, original_rebuild)
    engine.update_meta = _patched_update_meta(engine)
    engine.forget_memory = _patched_forget(engine, original_rebuild)
    engine.supersede = _patched_supersede(engine, original_rebuild)
    engine.migrate_legacy = _patched_migrate_legacy(engine, original_rebuild)
    engine.migration_complete = _patched_migration_complete(engine)

    # Export owner-safe helpers for the lifecycle CLI and acceptance tests.
    engine.public_beta_mutation_lock = lambda root, mode: _mutation_lock(engine, Path(root), mode)
    engine.public_beta_atomic_write_json = _atomic_write_json
    engine.public_beta_atomic_write_text = _atomic_write_text
    engine.public_beta_payload_digest = _payload_digest
    engine.public_beta_effect_path = lambda root, mode, effect_id: _effect_path(engine, Path(root), mode, effect_id)
    engine.public_beta_load_effect = lambda root, mode, effect_id, digest: _load_effect(
        engine, Path(root), mode, effect_id, digest
    )
    engine.public_beta_safe_child_dir = _safe_child_dir
    engine.public_beta_native_memory_base = lambda root, scope: _native_atomic_base(
        engine, Path(root), scope
    ).parent
    engine.public_beta_standalone_home = lambda root: _standalone_home(engine, Path(root))
    engine.public_beta_authority_file = lambda root, mode: _authority_file(engine, Path(root), mode)
    engine.public_beta_assert_writable_authority = lambda root, mode: _assert_writable_authority(engine, Path(root), mode)
    engine.public_beta_component_state_path = lambda root, mode: component_state_path(engine, Path(root), mode)
    engine.public_beta_read_component_state = lambda root, mode: read_component_state(engine, Path(root), mode)
    engine.public_beta_write_component_state = lambda root, mode, **changes: write_component_state(
        engine, Path(root), mode, **changes
    )

    # Session digests are an additive Memory-owned extension. Load them here,
    # after hardening helpers are attached, so the compatibility entrypoint can
    # evolve independently and concurrent runtime work does not need to edit it.
    digest_path = Path(__file__).resolve().parent / "session_digest.py"
    if digest_path.exists():
        module_name = "_aiverse_memory_session_digest"
        module = sys.modules.get(module_name)
        if module is None:
            spec = importlib.util.spec_from_file_location(module_name, digest_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Could not load session digest extension: {digest_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        module.apply(engine)
