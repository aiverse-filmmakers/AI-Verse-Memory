#!/usr/bin/env python3
"""Cross-platform installer for AI-Verse Memory."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

VERSION = "0.3.0-beta.2.dev0"
REPO_RAW = "https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory"
# The descriptor that records the accepted release. Its "revision" is the commit
# a member install must use. The bootstrap scripts read it the same way.
RELEASE_DESCRIPTOR = "release/component-release.json"
DESCRIPTOR_REF = "main"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RESOLVED_BASE_URL: Optional[str] = None


def accepted_revision(descriptor_text: str) -> str:
    """Return the accepted commit from a component-release descriptor."""
    data = json.loads(descriptor_text)
    revision = str(data.get("revision", "")).strip()
    if data.get("release_status") != "accepted" or not _COMMIT_RE.match(revision):
        raise RuntimeError("release/component-release.json does not name an accepted commit")
    return revision


def _fail(message: str) -> None:
    print(f"AI-Verse Memory install error: {message}", file=sys.stderr)
    raise SystemExit(2)


def resolve_base_url() -> str:
    """Developer overrides first, otherwise the accepted release commit."""
    global _RESOLVED_BASE_URL
    override = os.getenv("AI_VERSE_MEMORY_BASE_URL", "").strip()
    if override:
        return override.rstrip("/")
    ref = os.getenv("AI_VERSE_MEMORY_RELEASE_REF", "").strip()  # developer only
    if not ref:
        if _RESOLVED_BASE_URL is not None:
            return _RESOLVED_BASE_URL
        url = f"{REPO_RAW}/{DESCRIPTOR_REF}/{RELEASE_DESCRIPTOR}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed trusted project URL
                text = response.read().decode("utf-8")
        except Exception:
            _fail("Could not download the release file. Check your internet connection and try again.")
        try:
            ref = accepted_revision(text)
        except Exception:
            _fail("The release file is not valid or no release is accepted yet. Please try again later or report this.")
    _RESOLVED_BASE_URL = f"{REPO_RAW}/{ref}"
    return _RESOLVED_BASE_URL


MARKER_START = "<!-- AI-VERSE-MEMORY:START -->"
MARKER_END = "<!-- AI-VERSE-MEMORY:END -->"
LOCAL_REGISTRY = Path(".aiverse/extensions/registry.json")
LOCAL_REGISTRY_LOCK = Path(".aiverse/extensions/registry.json.lock")
MAX_REGISTRY_BYTES = 1024 * 1024

NATIVE_BLOCK = """<!-- AI-VERSE-MEMORY:START -->
## Persistent memory engine

AI-Verse Memory is installed as an optional memory engine. Follow `scripts/ai-verse-memory/MEMORY-PROTOCOL.md` and use `scripts/ai-verse-memory/memory.py` for scoped recall and atomic historical memory.

AI-Verse OS remains the authority for storage and routing: current context, profile, decisions, knowledge, and workspace boundaries stay canonical in the locations defined by `AI-VERSE.yaml`. Memory must never override newer current context, duplicate canonical decisions, or cross workspace boundaries unless the task explicitly requires it.
<!-- AI-VERSE-MEMORY:END -->"""

STANDALONE_BLOCK = """<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, state transitions, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->"""

LEGACY_REGISTRY_BLOCK = (
    "  - id: ai-verse-memory\n"
    "    scope: universal-extension\n"
    "    purpose: \"Provide scoped persistent historical memory, provenance, supersession, and rebuildable local recall without creating a second source of truth.\"\n"
)

WINDOWS_REPARSE_POINT = 0x0400


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _is_symlink_or_reparse(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if os.path.islink(path):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & WINDOWS_REPARSE_POINT)


def assert_safe_lifecycle_path(target: Path, candidate: Path) -> Path:
    """Return a lifecycle path only when its existing chain is physically confined to target."""
    root_input = _absolute_path(target)
    candidate_abs = _absolute_path(candidate)

    if not root_input.exists() or not root_input.is_dir():
        raise RuntimeError(f"Memory lifecycle target does not exist or is not a directory: {root_input}")
    if _is_symlink_or_reparse(root_input):
        raise RuntimeError(f"Memory lifecycle target may not be a symlink/junction/reparse point: {root_input}")

    root_real = root_input.resolve(strict=True)
    walk_root = root_input
    try:
        relative = candidate_abs.relative_to(root_input)
    except ValueError:
        try:
            relative = candidate_abs.relative_to(root_real)
            walk_root = root_real
        except ValueError as exc:
            raise RuntimeError(f"Memory lifecycle path escapes selected target: {candidate_abs}") from exc

    current = walk_root
    for part in relative.parts:
        current = current / part
        if _is_symlink_or_reparse(current):
            raise RuntimeError(f"Unsafe symlink/junction/reparse point in Memory lifecycle path: {current}")
        if current.exists():
            resolved = current.resolve(strict=True)
            try:
                resolved.relative_to(root_real)
            except ValueError as exc:
                raise RuntimeError(f"Memory lifecycle path resolves outside selected target: {current}") from exc

    parent = candidate_abs.parent
    while parent not in (walk_root, root_real) and not parent.exists():
        parent = parent.parent
    if _is_symlink_or_reparse(parent):
        raise RuntimeError(f"Unsafe symlink/junction/reparse parent in Memory lifecycle path: {parent}")
    parent_real = parent.resolve(strict=True)
    try:
        parent_real.relative_to(root_real)
    except ValueError as exc:
        raise RuntimeError(f"Memory lifecycle parent resolves outside selected target: {parent}") from exc
    return candidate_abs


def detect_native(target: Path) -> bool:
    manifest = target / "AI-VERSE.yaml"
    if not manifest.exists():
        return False
    text = manifest.read_text(encoding="utf-8", errors="replace")
    return bool(
        re.search(r"(?m)^schema_version:\s*[\"']?2(?:\.\d+)?[\"']?\s*$", text)
        and re.search(r"(?m)^architecture:\s*[\"']?unified-workspace[\"']?\s*$", text)
        and (target / "operator").exists()
        and (target / "workspaces").exists()
    )


def source_copy(
    relative: str,
    destination: Path,
    source_dir: Optional[Path],
    target_root: Optional[Path] = None,
) -> None:
    if target_root is not None:
        destination = assert_safe_lifecycle_path(target_root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if target_root is not None:
        destination = assert_safe_lifecycle_path(target_root, destination)
    if source_dir:
        src = source_dir / relative
        if not src.exists():
            raise FileNotFoundError(f"Installer source missing: {src}")
        _atomic_copy(src, destination)
        return
    url = f"{resolve_base_url()}/{relative}"
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed trusted project URL
        _atomic_write_bytes(destination, response.read())


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Replace a file in one step so a crash never leaves it half written.

    The bytes go to a temporary file in the same folder, are flushed to disk,
    then replace the target. An existing file keeps its permission bits.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        mode = 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        try:
            os.chmod(temp_name, mode)
        except OSError:
            pass
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass


def _atomic_copy(src: Path, destination: Path) -> None:
    """Copy a file (with its permissions and times) so the destination is never half written."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=str(destination.parent))
    os.close(fd)
    try:
        shutil.copy2(src, temp_name)
        os.replace(temp_name, destination)
    finally:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass


def _write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings on every platform, so later hashes match."""
    _atomic_write_bytes(path, text.encode("utf-8"))


def replace_marker_block(path: Path, block: Optional[str], target_root: Optional[Path] = None) -> None:
    if target_root is not None:
        path = assert_safe_lifecycle_path(target_root, path)
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.S)
    if pattern.search(text):
        replacement = block or ""
        text = pattern.sub(replacement, text)
        text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
    elif block:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if target_root is not None:
        path = assert_safe_lifecycle_path(target_root, path)
    _write_text_lf(path, text)


def ensure_gitignore(target: Path, entry: str, comment: str) -> None:
    path = assert_safe_lifecycle_path(target, target / ".gitignore")
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = text.splitlines()
    if entry in lines:
        return
    addition = f"\n# {comment}\n{entry}\n"
    _write_text_lf(path, text.rstrip() + addition)


def _ensure_extension_dir(target: Path) -> Path:
    base = target.resolve()
    meta = assert_safe_lifecycle_path(base, base / ".aiverse")
    extensions = assert_safe_lifecycle_path(base, meta / "extensions")
    for path in (meta, extensions):
        if path.exists() and path.is_symlink():
            raise RuntimeError(f"Unsafe symlink in extension registry path: {path}")
        if path.exists() and not path.is_dir():
            raise RuntimeError(f"Extension registry path is not a directory: {path}")
        if not path.exists():
            path.mkdir(mode=0o700)
        assert_safe_lifecycle_path(base, path)
    return extensions


def _windows_pid_alive(pid: int) -> bool:
    # Never signal on Windows: os.kill(pid, 0) there terminates the process.
    # Ask the OS for the exit code of a read-only process handle instead.
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied means the process exists but is not ours to inspect.
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        exit_code = wintypes.DWORD(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _pid_alive(pid: int) -> bool:
    # NOTE: identical copy lives in scripts/public_beta.py; the two scripts
    # are downloaded and loaded one by one, so they cannot share a module.
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


REGISTRY_LOCK_STALE_SECONDS = 600
REGISTRY_GUARD_STALE_SECONDS = 30
REGISTRY_UNLINK_ATTEMPTS = 5
REGISTRY_UNLINK_PAUSE_SECONDS = 0.05
# How long to wait for another installer that is clearing a stale lock.
REGISTRY_CLEAR_WAIT_SECONDS = 10


def _read_json_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_identity(path: Path):
    """Identify one specific lock file: which file it is and which token it carries."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return (
        int(getattr(stat, "st_ino", 0) or 0),
        int(getattr(stat, "st_mtime_ns", 0) or 0),
        int(stat.st_size),
        str(_read_json_object(path).get("token") or ""),
    )


def _registry_lock_is_stale(lock: Path) -> bool:
    try:
        age = max(0.0, time.time() - lock.stat().st_mtime)
    except OSError:
        return False
    if age < REGISTRY_LOCK_STALE_SECONDS:
        return False
    try:
        pid = int(_read_json_object(lock).get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    return not _pid_alive(pid)


def _is_windows() -> bool:
    return os.name == "nt"


def _busy_error(exc: BaseException) -> bool:
    """True if this error only means "another program has the file right now".

    On Windows, creating, opening, reading or deleting a file that another
    process has open or is deleting raises PermissionError (or an OSError with
    winerror 5, 32 or 33). Elsewhere a PermissionError is a real problem.
    """
    if not _is_windows():
        return False
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33)


def _release_token_file(path: Path, token: str) -> None:
    """Remove a lock or guard file, but only if it still carries our token.

    Runs in finally blocks: a busy file is retried briefly and then given up
    with a one line warning, so the real error is never hidden.
    """
    for attempt in range(REGISTRY_UNLINK_ATTEMPTS):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("token") != token:
                return
            path.unlink()
            return
        except FileNotFoundError:
            return
        except ValueError:
            return
        except OSError:
            if attempt + 1 < REGISTRY_UNLINK_ATTEMPTS:
                time.sleep(REGISTRY_UNLINK_PAUSE_SECONDS)
    try:
        print(
            f"warning: could not remove the Memory lock file {path}; it will be cleared later as stale.",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 - a warning must never raise
        pass


def _try_take_registry_guard(guard: Path):
    """Try to take the exclusive clearing guard. Return our token, or None if another installer holds it."""
    token = uuid.uuid4().hex
    for _ in range(2):
        try:
            fd = os.open(str(guard), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError as exc:
            if isinstance(exc, FileExistsError):
                pass
            elif _busy_error(exc):
                return None
            else:
                raise
            seen = _file_identity(guard)
            stale = False
            if seen is not None:
                try:
                    old = time.time() - guard.stat().st_mtime >= REGISTRY_GUARD_STALE_SECONDS
                    pid = int(_read_json_object(guard).get("pid") or 0)
                except (OSError, TypeError, ValueError):
                    old, pid = False, 0
                stale = old and not (pid > 0 and _pid_alive(pid))
            if stale and _file_identity(guard) == seen:
                try:
                    guard.unlink()
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    if _busy_error(exc):
                        return None
                    raise
                continue
            return None
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"pid": os.getpid(), "token": token}, handle)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            try:
                guard.unlink()
            except FileNotFoundError:
                pass
            raise
        return token
    return None


def _clear_stale_registry_lock(lock: Path, observed) -> str:
    """Clear one stale lock, one installer at a time.

    The installer takes the exclusive guard `<lock>.clearing`, looks at the lock
    again, and clears it only if it is the same file that was judged stale and
    it is still stale. Nothing is ever put back. Returns "cleared", "gone",
    "fresh" or "busy".
    """
    guard = lock.with_name(lock.name + ".clearing")
    guard_token = _try_take_registry_guard(guard)
    if guard_token is None:
        return "busy"
    try:
        current = _file_identity(lock)
        if current is None:
            return "gone"
        if current != observed or not _registry_lock_is_stale(lock):
            return "fresh"
        for attempt in range(REGISTRY_UNLINK_ATTEMPTS):
            try:
                lock.unlink()
                return "cleared"
            except FileNotFoundError:
                return "gone"
            except OSError as exc:
                if attempt + 1 >= REGISTRY_UNLINK_ATTEMPTS:
                    if _busy_error(exc):
                        return "busy"
                    raise RuntimeError(f"Could not clear stale local extension registry lock: {lock}: {exc}") from exc
                time.sleep(REGISTRY_UNLINK_PAUSE_SECONDS)
        return "cleared"
    finally:
        _release_token_file(guard, guard_token)


@contextmanager
def _registry_lock(target: Path):
    extensions = _ensure_extension_dir(target)
    lock = extensions / "registry.json.lock"
    deadline = time.monotonic() + REGISTRY_CLEAR_WAIT_SECONDS
    while True:
        try:
            fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError as exc:
            observed = _file_identity(lock)
            if observed is not None and _registry_lock_is_stale(lock):
                outcome = _clear_stale_registry_lock(lock, observed)
                if outcome in ("cleared", "gone"):
                    continue
                if outcome == "busy" and time.monotonic() < deadline:
                    time.sleep(0.05)
                    continue
            raise RuntimeError(f"Local extension registry is busy: {lock}") from exc
        except OSError as exc:
            if _busy_error(exc):
                # Windows: the lock file is open or being deleted by another
                # process. Wait inside the deadline, then report busy.
                if time.monotonic() < deadline:
                    time.sleep(0.05)
                    continue
                raise RuntimeError(f"Local extension registry is busy: {lock}") from exc
            raise RuntimeError(f"Could not acquire local extension registry lock: {exc}") from exc
    token = uuid.uuid4().hex
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump({"extension_id": "ai-verse-memory", "pid": os.getpid(), "token": token}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            lock.unlink()
        except OSError:
            pass
        raise
    try:
        yield
    finally:
        _release_token_file(lock, token)


def _read_local_registry(target: Path) -> tuple[dict, Optional[str]]:
    registry = assert_safe_lifecycle_path(target, target / LOCAL_REGISTRY)
    if not registry.exists():
        return {"schema_version": "1.0", "extensions": {}}, None
    if registry.is_symlink() or not registry.is_file():
        raise RuntimeError(f"Local extension registry must be a regular non-symlink file: {registry}")
    if registry.stat().st_size > MAX_REGISTRY_BYTES:
        raise RuntimeError("Local extension registry is too large; left unchanged")
    try:
        raw = registry.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Local extension registry is unreadable; left unchanged: {registry}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Local extension registry must contain a JSON object: {registry}")
    if str(payload.get("schema_version", "")) != "1.0":
        raise RuntimeError(
            f"Unsupported local extension registry schema {payload.get('schema_version')!r}; left unchanged"
        )
    if not isinstance(payload.get("extensions"), dict):
        raise RuntimeError("Local extension registry 'extensions' must be a JSON object; left unchanged")
    return payload, raw


def _write_registry_atomic(target: Path, payload: dict, expected_raw: Optional[str]) -> None:
    extensions = _ensure_extension_dir(target)
    registry = assert_safe_lifecycle_path(target, extensions / "registry.json")
    current_raw = registry.read_text(encoding="utf-8") if registry.exists() else None
    if current_raw != expected_raw:
        raise RuntimeError("Local extension registry changed during Memory lifecycle operation")
    fd, temp_name = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=str(extensions))
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if registry.exists() and (registry.is_symlink() or not registry.is_file()):
            raise RuntimeError("Local extension registry became unsafe before replacement")
        os.replace(temp_name, registry)
    finally:
        try:
            Path(temp_name).unlink()
        except OSError:
            pass


def register_local_extension(target: Path) -> str:
    with _registry_lock(target):
        payload, raw = _read_local_registry(target)
        extensions = payload["extensions"]
        existing = extensions.get("ai-verse-memory", {})
        if existing is None:
            existing = {}
        if not isinstance(existing, dict):
            raise RuntimeError("Existing ai-verse-memory registration is not an object; left unchanged")
        enabled = existing.get("enabled", True)
        if not isinstance(enabled, bool):
            raise RuntimeError("Existing ai-verse-memory enabled field must be boolean; left unchanged")
        entry = dict(existing)
        entry.update(
            {
                "id": "ai-verse-memory",
                "supported": True,
                "installed": True,
                "enabled": enabled,
                "version": VERSION,
                "source": "AI-Verse-Memory",
                "instructions": "scripts/ai-verse-memory/MEMORY-PROTOCOL.md",
                "engine": "scripts/ai-verse-memory/memory.py",
                "adapters": [
                    ".claude/skills/ai-verse-memory/SKILL.md",
                    ".agents/skills/ai-verse-memory/SKILL.md",
                ],
            }
        )
        extensions["ai-verse-memory"] = entry
        _write_registry_atomic(target, payload, raw)
        return "updated" if existing else "registered"


def set_local_extension_enabled(target: Path, enabled: bool) -> dict:
    with _registry_lock(target):
        payload, raw = _read_local_registry(target)
        extensions = payload["extensions"]
        existing = extensions.get("ai-verse-memory")
        if not isinstance(existing, dict):
            raise RuntimeError("AI-Verse Memory is not registered in this OS")
        entry = dict(existing)
        entry["enabled"] = bool(enabled)
        extensions["ai-verse-memory"] = entry
        _write_registry_atomic(target, payload, raw)
        return entry


def unregister_local_extension(target: Path) -> bool:
    with _registry_lock(target):
        payload, raw = _read_local_registry(target)
        extensions = payload["extensions"]
        if "ai-verse-memory" not in extensions:
            return False
        del extensions["ai-verse-memory"]
        _write_registry_atomic(target, payload, raw)
        return True


def _migrate_exact_legacy_marker(path: Path, label: str, target_root: Optional[Path] = None) -> str:
    if target_root is not None:
        path = assert_safe_lifecycle_path(target_root, path)
    if not path.exists():
        return f"{label}: not present"
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER_START not in text and MARKER_END not in text:
        return f"{label}: no legacy marker"

    expected_suffix = "\n\n" + NATIVE_BLOCK + "\n"
    if text.endswith(expected_suffix):
        restored = text[: -len(expected_suffix)] + "\n"
        _write_text_lf(path, restored)
        return f"{label}: migrated exact legacy Memory marker"

    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.S)
    match = pattern.search(text)
    if match and match.group(0) == NATIVE_BLOCK:
        return f"warning: {label} legacy Memory marker is in an unexpected position; left unchanged"
    return f"warning: {label} contains a modified or ambiguous Memory marker; left unchanged"


def _migrate_exact_legacy_registry(target: Path) -> str:
    registry = assert_safe_lifecycle_path(target, target / "skills" / "registry.yaml")
    if not registry.exists():
        return "skills/registry.yaml: not present"
    text = registry.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"(?m)^\s*-\s+id:\s+ai-verse-memory\s*$", text):
        return "skills/registry.yaml: no legacy Memory entry"

    exact = LEGACY_REGISTRY_BLOCK + "\n"
    if exact in text:
        _write_text_lf(registry, text.replace(exact, "", 1))
        return "skills/registry.yaml: migrated exact legacy Memory entry"
    return "warning: skills/registry.yaml contains a modified or ambiguous ai-verse-memory entry; left unchanged"


def migrate_legacy_native_integration(target: Path) -> list[str]:
    results = [
        _migrate_exact_legacy_marker(target / "AGENTS.md", "AGENTS.md", target),
        _migrate_exact_legacy_marker(target / "CLAUDE.md", "CLAUDE.md", target),
        _migrate_exact_legacy_registry(target),
    ]
    return results


def has_local_extension_hook(target: Path) -> bool:
    agents = target / "AGENTS.md"
    if not agents.exists():
        return False
    text = agents.read_text(encoding="utf-8", errors="replace")
    return ".aiverse/extensions/registry.json" in text


def install_skills(target: Path, source_dir: Optional[Path]) -> None:
    destinations = [
        target / ".claude" / "skills" / "ai-verse-memory" / "SKILL.md",
        target / ".agents" / "skills" / "ai-verse-memory" / "SKILL.md",
    ]
    for destination in destinations:
        assert_safe_lifecycle_path(target, destination)
    for destination in destinations:
        source_copy("SKILL.md", destination, source_dir, target_root=target)


def install_hermes(source_dir: Optional[Path]) -> Optional[Path]:
    home = Path.home() / ".hermes"
    if not shutil.which("hermes") and not home.exists():
        return None
    skill = home / "skills" / "ai-verse" / "ai-verse-memory" / "SKILL.md"
    source_copy("SKILL.md", skill, source_dir)
    return skill


def run_engine(engine: Path, target: Path, command: str) -> None:
    result = subprocess.run(
        [sys.executable, str(engine), "--root", str(target), command],
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Memory engine command failed: {command} (exit {result.returncode})")


def install_native(target: Path, source_dir: Optional[Path]) -> None:
    engine_root = target / "scripts" / "ai-verse-memory"
    source_copy("scripts/memory.py", engine_root / "memory.py", source_dir, target_root=target)
    source_copy("scripts/component.py", engine_root / "component.py", source_dir, target_root=target)
    source_copy("protocol/MEMORY-PROTOCOL.md", engine_root / "MEMORY-PROTOCOL.md", source_dir, target_root=target)
    source_copy("migration/MIGRATION.md", engine_root / "MIGRATION.md", source_dir, target_root=target)
    install_skills(target, source_dir)

    migration_results = migrate_legacy_native_integration(target)
    for result in migration_results:
        print(f"Legacy integration: {result}")

    print(f"Local extension registry: {register_local_extension(target)}")
    if not has_local_extension_hook(target):
        print(
            "warning: this AI-Verse OS checkout does not yet contain the local extension runtime hook; "
            "Memory is installed without dirtying tracked OS files, but update AI-Verse OS before relying on automatic extension discovery"
        )

    run_engine(engine_root / "memory.py", target, "init")
    run_engine(engine_root / "memory.py", target, "doctor")

    legacy = target / ".ai-verse-memory"
    if legacy.exists():
        print("\nLegacy v0.1 store detected and left untouched.")
        print("Review first: python scripts/ai-verse-memory/memory.py migrate-legacy")
        print("Apply after review: python scripts/ai-verse-memory/memory.py migrate-legacy --apply")

    print("\nAI-Verse Memory installed in native AI-Verse OS v2 mode.")
    print("Canonical operator memory: operator/memory/atomic/")
    print("Canonical workspace memory: workspaces/<id>/memory/atomic/")
    print("Derived index: runtime/indexes/ai-verse-memory/memory.db")
    print("Engine: scripts/ai-verse-memory/memory.py")
    print("Registration: .aiverse/extensions/registry.json")



def disable_native(target: Path) -> None:
    entry = set_local_extension_enabled(target, False)
    print(f"AI-Verse Memory disabled: enabled={entry['enabled']}")
    print("Canonical operator/workspace Memory and installed engine files were preserved.")


def enable_native(target: Path) -> None:
    entry = set_local_extension_enabled(target, True)
    print(f"AI-Verse Memory enabled: enabled={entry['enabled']}")


def detach_native(target: Path) -> None:
    removed = unregister_local_extension(target)
    print(f"AI-Verse Memory local attachment removed: {removed}")
    print("Canonical operator/workspace Memory was preserved.")
    print("Installed engine/adapters were preserved for explicit re-attachment or repair.")


def install_standalone(target: Path, source_dir: Optional[Path]) -> None:
    runtime = target / ".ai-verse-memory"
    authority = runtime / "AUTHORITY.json"
    if authority.exists():
        try:
            authority_payload = json.loads(authority.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Standalone Memory authority marker is unreadable: {authority}") from exc
        if authority_payload.get("status") == "retired":
            raise RuntimeError(
                "This standalone Memory store was retired after canonical authority handoff; "
                "refusing to reactivate the old writable canonical route"
            )
    source_copy("scripts/memory.py", runtime / "memory.py", source_dir, target_root=target)
    source_copy("scripts/component.py", runtime / "component.py", source_dir, target_root=target)
    source_copy("protocol/MEMORY-PROTOCOL.md", runtime / "MEMORY-PROTOCOL.md", source_dir, target_root=target)
    source_copy("migration/MIGRATION.md", runtime / "MIGRATION.md", source_dir, target_root=target)
    source_copy("templates/scenario.md", runtime / "SCENARIO-TEMPLATE.md", source_dir, target_root=target)
    profile = runtime / "profile.md"
    if not profile.exists():
        source_copy("templates/profile.md", profile, source_dir, target_root=target)
    install_skills(target, source_dir)
    replace_marker_block(target / "AGENTS.md", STANDALONE_BLOCK, target_root=target)
    replace_marker_block(target / "CLAUDE.md", STANDALONE_BLOCK, target_root=target)
    ensure_gitignore(target, ".ai-verse-memory/", "AI-Verse Memory local runtime and personal memory")
    run_engine(runtime / "memory.py", target, "init")
    run_engine(runtime / "memory.py", target, "doctor")
    print("\nAI-Verse Memory installed in standalone compatibility mode.")
    print("Memory store: .ai-verse-memory/")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install or manage AI-Verse Memory")
    parser.add_argument("--target", default=os.getenv("AI_VERSE_MEMORY_TARGET", "."))
    parser.add_argument("--source-dir", default=os.getenv("AI_VERSE_MEMORY_SOURCE_DIR"))
    parser.add_argument(
        "--action",
        choices=("install", "enable", "disable", "detach"),
        default="install",
        help="native attachment lifecycle action; install remains the bootstrap default",
    )
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    if args.action == "install":
        target.mkdir(parents=True, exist_ok=True)
    elif not target.is_dir():
        raise RuntimeError(f"Memory lifecycle target does not exist: {target}")

    native = detect_native(target)
    print(f"AI-Verse Memory {VERSION}")
    print(f"Target: {target}")
    print(f"Mode: {'ai-verse-os-v2' if native else 'standalone'}")
    print(f"Action: {args.action}")

    if args.action != "install":
        if not native:
            raise RuntimeError(
                "enable/disable/detach are native AI-Verse OS attachment actions; "
                "standalone Memory state is preserved and never guessed or deleted"
            )
        if args.action == "enable":
            enable_native(target)
        elif args.action == "disable":
            disable_native(target)
        else:
            detach_native(target)
        return 0

    if native:
        install_native(target, source_dir)
    else:
        install_standalone(target, source_dir)

    hermes = install_hermes(source_dir)
    if hermes:
        print(f"Hermes skill: {hermes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
