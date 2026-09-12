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
import urllib.request
from pathlib import Path
from typing import Optional

VERSION = "0.2.0"
BASE_URL = "https://raw.githubusercontent.com/aiverse-filmmakers/AI-Verse-Memory/main"
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


def source_copy(relative: str, destination: Path, source_dir: Optional[Path]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source_dir:
        src = source_dir / relative
        if not src.exists():
            raise FileNotFoundError(f"Installer source missing: {src}")
        shutil.copy2(src, destination)
        return
    url = f"{BASE_URL}/{relative}"
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed trusted project URL
        destination.write_bytes(response.read())


def replace_marker_block(path: Path, block: Optional[str]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.S)
    if pattern.search(text):
        replacement = block or ""
        text = pattern.sub(replacement, text)
        text = re.sub(r"\n{3,}", "\n\n", text).rstrip() + "\n"
    elif block:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + block + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ensure_gitignore(target: Path, entry: str, comment: str) -> None:
    path = target / ".gitignore"
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    lines = text.splitlines()
    if entry in lines:
        return
    addition = f"\n# {comment}\n{entry}\n"
    path.write_text(text.rstrip() + addition, encoding="utf-8")


def _ensure_extension_dir(target: Path) -> Path:
    base = target.resolve()
    meta = base / ".aiverse"
    extensions = meta / "extensions"
    for path in (meta, extensions):
        if path.exists() and path.is_symlink():
            raise RuntimeError(f"Unsafe symlink in extension registry path: {path}")
        if path.exists() and not path.is_dir():
            raise RuntimeError(f"Extension registry path is not a directory: {path}")
        if not path.exists():
            path.mkdir(mode=0o700)
    return extensions


@contextmanager
def _registry_lock(target: Path):
    extensions = _ensure_extension_dir(target)
    lock = extensions / "registry.json.lock"
    try:
        fd = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(f"Local extension registry is busy: {lock}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not acquire local extension registry lock: {exc}") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"extension_id": "ai-verse-memory"}, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _read_local_registry(target: Path) -> tuple[dict, Optional[str]]:
    registry = target / LOCAL_REGISTRY
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
    registry = extensions / "registry.json"
    current_raw = registry.read_text(encoding="utf-8") if registry.exists() else None
    if current_raw != expected_raw:
        raise RuntimeError("Local extension registry changed during Memory lifecycle operation")
    fd, temp_name = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=str(extensions))
    try:
        try:
            os.chmod(temp_name, 0o600)
        except OSError:
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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
        except FileNotFoundError:
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


def _migrate_exact_legacy_marker(path: Path, label: str) -> str:
    if not path.exists():
        return f"{label}: not present"
    text = path.read_text(encoding="utf-8", errors="replace")
    if MARKER_START not in text and MARKER_END not in text:
        return f"{label}: no legacy marker"

    expected_suffix = "\n\n" + NATIVE_BLOCK + "\n"
    if text.endswith(expected_suffix):
        restored = text[: -len(expected_suffix)] + "\n"
        path.write_text(restored, encoding="utf-8")
        return f"{label}: migrated exact legacy Memory marker"

    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.S)
    match = pattern.search(text)
    if match and match.group(0) == NATIVE_BLOCK:
        return f"warning: {label} legacy Memory marker is in an unexpected position; left unchanged"
    return f"warning: {label} contains a modified or ambiguous Memory marker; left unchanged"


def _migrate_exact_legacy_registry(target: Path) -> str:
    registry = target / "skills" / "registry.yaml"
    if not registry.exists():
        return "skills/registry.yaml: not present"
    text = registry.read_text(encoding="utf-8", errors="replace")
    if not re.search(r"(?m)^\s*-\s+id:\s+ai-verse-memory\s*$", text):
        return "skills/registry.yaml: no legacy Memory entry"

    exact = LEGACY_REGISTRY_BLOCK + "\n"
    if exact in text:
        registry.write_text(text.replace(exact, "", 1), encoding="utf-8")
        return "skills/registry.yaml: migrated exact legacy Memory entry"
    return "warning: skills/registry.yaml contains a modified or ambiguous ai-verse-memory entry; left unchanged"


def migrate_legacy_native_integration(target: Path) -> list[str]:
    results = [
        _migrate_exact_legacy_marker(target / "AGENTS.md", "AGENTS.md"),
        _migrate_exact_legacy_marker(target / "CLAUDE.md", "CLAUDE.md"),
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
    for runtime_root in (target / ".claude" / "skills", target / ".agents" / "skills"):
        skill_root = runtime_root / "ai-verse-memory"
        source_copy("SKILL.md", skill_root / "SKILL.md", source_dir)


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
    )
    if result.returncode != 0:
        raise RuntimeError(f"Memory engine command failed: {command} (exit {result.returncode})")


def install_native(target: Path, source_dir: Optional[Path]) -> None:
    engine_root = target / "scripts" / "ai-verse-memory"
    source_copy("scripts/memory.py", engine_root / "memory.py", source_dir)
    source_copy("protocol/MEMORY-PROTOCOL.md", engine_root / "MEMORY-PROTOCOL.md", source_dir)
    source_copy("migration/MIGRATION.md", engine_root / "MIGRATION.md", source_dir)
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
    source_copy("scripts/memory.py", runtime / "memory.py", source_dir)
    source_copy("protocol/MEMORY-PROTOCOL.md", runtime / "MEMORY-PROTOCOL.md", source_dir)
    source_copy("migration/MIGRATION.md", runtime / "MIGRATION.md", source_dir)
    source_copy("templates/scenario.md", runtime / "SCENARIO-TEMPLATE.md", source_dir)
    profile = runtime / "profile.md"
    if not profile.exists():
        source_copy("templates/profile.md", profile, source_dir)
    install_skills(target, source_dir)
    replace_marker_block(target / "AGENTS.md", STANDALONE_BLOCK)
    replace_marker_block(target / "CLAUDE.md", STANDALONE_BLOCK)
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
