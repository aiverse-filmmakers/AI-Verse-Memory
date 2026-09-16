#!/usr/bin/env python3
"""Standard public lifecycle for AI-Verse Memory.

Public vocabulary follows the AI-Verse component install/setup contract:
install, setup, status, doctor, enable, disable, update, uninstall.

Expert recovery/adoption commands remain explicit: reconcile, detach, migrate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
COMPONENT_ID = "ai-verse-memory"


def _load(name: str, filename: str):
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load required lifecycle module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installer = _load("_aiverse_memory_component_installer", "install.py")
memory = _load("_aiverse_memory_component_engine", "memory.py")
compat = _load("_aiverse_memory_component_compat", "os_compat.py")

VERSION = memory.VERSION


def _compatibility(target: Path):
    return installer.detect_os_compatibility(target)


def _mode_from_compat(target: Path, result=None) -> str:
    result = result or _compatibility(target)
    if result.status == compat.OS_COMPATIBLE:
        return memory.MODE_NATIVE
    if result.status == compat.OS_NONE:
        return memory.MODE_STANDALONE
    return "incompatible"


def _runtime_path(target: Path, mode: str) -> Path:
    if mode == memory.MODE_NATIVE:
        return target / "scripts" / "ai-verse-memory" / "memory.py"
    return target / ".ai-verse-memory" / "memory.py"


def _runtime_dir(target: Path, mode: str) -> Path:
    return _runtime_path(target, mode).parent


def _component_state_path_readonly(target: Path, mode: str) -> Path:
    if mode == memory.MODE_NATIVE:
        return target / "operator" / "memory" / ".ai-verse-memory-state" / "component.json"
    return target / ".ai-verse-memory" / "state" / "component.json"


def _read_json_file(path: Path) -> tuple[Optional[dict], Optional[str]]:
    if not path.exists():
        return None, None
    if path.is_symlink() or not path.is_file():
        return None, f"unsafe non-regular file: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, str(exc)
    if not isinstance(payload, dict):
        return None, "expected JSON object"
    return payload, None


def _component_receipt(target: Path, mode: str) -> dict:
    payload, _ = _read_json_file(_component_state_path_readonly(target, mode))
    return payload or {}


def _registry_state(target: Path) -> tuple[Optional[dict], Optional[str]]:
    path = target / ".aiverse" / "extensions" / "registry.json"
    payload, error = _read_json_file(path)
    if error:
        return None, error
    if payload is None:
        return None, None
    if payload.get("schema_version") != "1.0" or not isinstance(payload.get("extensions"), dict):
        return None, "unsupported or malformed local extension registry"
    entry = payload["extensions"].get(COMPONENT_ID)
    if entry is None:
        return None, None
    if not isinstance(entry, dict):
        return None, "ai-verse-memory registry entry is not an object"
    return entry, None


def _authority_state(target: Path, mode: str) -> tuple[str, Optional[dict], Optional[str]]:
    if mode == memory.MODE_NATIVE:
        path = target / "operator" / "memory" / ".ai-verse-memory-state" / "authority-handoff.json"
    else:
        path = target / ".ai-verse-memory" / "AUTHORITY.json"
    payload, error = _read_json_file(path)
    if error:
        return "invalid", None, error
    if payload is None:
        return "active", None, None
    status = str(payload.get("status") or "active")
    return status, payload, None


def _migration_required(target: Path, mode: str) -> tuple[bool, str]:
    if mode != memory.MODE_NATIVE:
        return False, ""
    handoff_status, handoff, handoff_error = _authority_state(target, mode)
    if handoff_error:
        return True, f"invalid authority handoff: {handoff_error}"

    plan = target / "operator" / "memory" / "migrations" / "legacy-ai-verse-memory-plan.json"
    if plan.exists() and handoff_status != "complete":
        return True, "reviewed legacy migration plan has not completed authority handoff"

    legacy = target / ".ai-verse-memory"
    if legacy.exists():
        source_authority, error = _read_json_file(legacy / "AUTHORITY.json")
        if error:
            return True, f"legacy authority marker invalid: {error}"
        retired = bool(
            source_authority
            and source_authority.get("status") == "retired"
            and handoff
            and source_authority.get("handoff_id") == handoff.get("handoff_id")
        )
        if not retired:
            return True, "legacy standalone Memory is still an active writable canonical route"
    return False, ""


def _preserved_state(target: Path, mode: str) -> bool:
    if mode == memory.MODE_NATIVE:
        receipt = _component_state_path_readonly(target, mode)
        if receipt.exists():
            return True
        operator_atomic = target / "operator" / "memory" / "atomic"
        if operator_atomic.exists() and any(operator_atomic.rglob("*.md")):
            return True
        workspaces = target / "workspaces"
        if workspaces.exists():
            for path in workspaces.glob("*/memory/atomic"):
                if path.exists() and any(path.rglob("*.md")):
                    return True
        return False
    home = target / ".ai-verse-memory"
    if not home.exists():
        return False
    for candidate in (home / "profile.md", home / "memories", home / "state" / "component.json"):
        if candidate.exists():
            return True
    return False


def status_payload(target: Path) -> dict:
    target = target.expanduser().resolve()
    compatibility = _compatibility(target)
    mode = _mode_from_compat(target, compatibility)
    base: Dict[str, Any] = {
        "schema_version": 1,
        "component": COMPONENT_ID,
        "version": VERSION,
        "target": str(target),
        "compatibility": {
            "status": compatibility.status,
            "reason": compatibility.reason,
        },
        "mode": mode,
        "installed": False,
        "setup_completed": False,
        "enabled": None,
        "attached": False,
        "preserved_state": False,
        "migration_required": False,
        "authority": "unknown",
        "state": "absent",
        "health": "unknown",
        "readiness": False,
        "supported_commands": [
            "install",
            "setup",
            "status",
            "doctor",
            "enable",
            "disable",
            "update",
            "uninstall",
            "reconcile",
            "detach",
            "migrate",
        ],
        "setup_requirements": [
            "attach/register only in native AI-Verse OS mode",
            "initialize or rebuild Memory derived state",
            "detect legacy migration needs without transferring authority",
        ],
        "authority_transfer_separate": True,
        "uninstall_preserves_state": True,
    }

    if mode == "incompatible":
        base.update({"state": "unhealthy", "health": "fail"})
        return base

    runtime = _runtime_path(target, mode)
    installed = runtime.is_file() and not runtime.is_symlink()
    base["installed"] = installed
    base["runtime"] = str(runtime)
    base["preserved_state"] = _preserved_state(target, mode)

    receipt, receipt_error = _read_json_file(_component_state_path_readonly(target, mode))
    if receipt_error:
        base.update({"state": "unhealthy", "health": "fail", "error": receipt_error})
        return base
    receipt = receipt or {}
    base["setup_completed"] = bool(receipt.get("setup_completed"))

    authority, authority_payload, authority_error = _authority_state(target, mode)
    base["authority"] = authority
    if authority_payload:
        base["authority_receipt"] = {
            "handoff_id": authority_payload.get("handoff_id"),
            "status": authority_payload.get("status"),
        }
    if authority_error:
        base.update({"state": "unhealthy", "health": "fail", "error": authority_error})
        return base

    if mode == memory.MODE_NATIVE:
        entry, registry_error = _registry_state(target)
        if registry_error:
            base.update({"state": "unhealthy", "health": "fail", "error": registry_error})
            return base
        base["attached"] = entry is not None
        if entry is not None:
            enabled = entry.get("enabled")
            if not isinstance(enabled, bool):
                base.update({"state": "unhealthy", "health": "fail", "error": "registry enabled field is not boolean"})
                return base
            base["enabled"] = enabled
        migration_required, migration_reason = _migration_required(target, mode)
        base["migration_required"] = migration_required
        if migration_reason:
            base["migration_reason"] = migration_reason

        if not installed:
            base["state"] = "absent"
            base["health"] = "ok" if base["preserved_state"] else "unknown"
        elif not entry or not base["setup_completed"]:
            base["state"] = "setup-required"
            base["health"] = "ok"
        elif base["enabled"] is False:
            base["state"] = "disabled"
            base["health"] = "ok"
        elif migration_required:
            base["state"] = "migration-required"
            base["health"] = "ok"
        else:
            base["state"] = "ready"
            base["health"] = "ok"
            base["readiness"] = True
    else:
        base["enabled"] = authority != "retired"
        base["attached"] = bool(receipt.get("setup_completed"))
        if authority == "retired":
            base["state"] = "disabled"
            base["health"] = "ok"
        elif not installed:
            base["state"] = "absent"
            base["health"] = "ok" if base["preserved_state"] else "unknown"
        elif not base["setup_completed"]:
            base["state"] = "setup-required"
            base["health"] = "ok"
        else:
            base["state"] = "ready"
            base["health"] = "ok"
            base["readiness"] = True
    return base


def _emit(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"AI-Verse Memory {payload.get('version', VERSION)}")
    print(f"State: {payload.get('state', 'unknown')}")
    if "target" in payload:
        print(f"Target: {payload['target']}")
    if "mode" in payload:
        print(f"Mode: {payload['mode']}")
    print(f"Ready: {'yes' if payload.get('readiness') else 'no'}")
    if payload.get("migration_reason"):
        print(f"Migration: {payload['migration_reason']}")
    if payload.get("message"):
        print(payload["message"])


def _copy_runtime(target: Path, mode: str, source_dir: Optional[Path]) -> None:
    if mode == memory.MODE_NATIVE:
        runtime = target / "scripts" / "ai-verse-memory"
    else:
        runtime = target / ".ai-verse-memory"
    installer.source_copy("scripts/memory.py", runtime / "memory.py", source_dir, target_root=target)
    installer.source_copy("scripts/component.py", runtime / "component.py", source_dir, target_root=target)
    installer.source_copy("protocol/MEMORY-PROTOCOL.md", runtime / "MEMORY-PROTOCOL.md", source_dir, target_root=target)
    installer.source_copy("migration/MIGRATION.md", runtime / "MIGRATION.md", source_dir, target_root=target)
    if mode == memory.MODE_STANDALONE:
        installer.source_copy("templates/scenario.md", runtime / "SCENARIO-TEMPLATE.md", source_dir, target_root=target)


def _install_package(target: Path, source_dir: Optional[Path]) -> dict:
    target.mkdir(parents=True, exist_ok=True)
    compatibility = _compatibility(target)
    mode = _mode_from_compat(target, compatibility)
    if mode == "incompatible":
        raise RuntimeError(f"Incompatible AI-Verse OS: {compatibility.reason}")
    if mode == memory.MODE_STANDALONE:
        authority, _, error = _authority_state(target, mode)
        if error:
            raise RuntimeError(error)
        if authority == "retired":
            raise RuntimeError("This standalone Memory route was retired by a canonical authority handoff and cannot be reinstalled as active.")
    _copy_runtime(target, mode, source_dir)
    payload = status_payload(target)
    payload["message"] = "Package/runtime installed. Run setup to make Memory usable."
    return payload


def _setup(target: Path, source_dir: Optional[Path]) -> dict:
    compatibility = _compatibility(target)
    mode = _mode_from_compat(target, compatibility)
    if mode == "incompatible":
        raise RuntimeError(f"Incompatible AI-Verse OS: {compatibility.reason}")
    if not _runtime_path(target, mode).exists():
        _copy_runtime(target, mode, source_dir)

    if mode == memory.MODE_NATIVE:
        installer.install_skills(target, source_dir)
        for result in installer.migrate_legacy_native_integration(target):
            if result.startswith("warning:"):
                print(result, file=sys.stderr)
        installer.register_local_extension(target)
        memory.ensure_layout(target, mode)
        memory.rebuild(silent=True, root=target, mode=mode)
        memory.public_beta_write_component_state(
            target,
            mode,
            installed=True,
            setup_completed=True,
            enabled=True,
            last_action="setup",
        )
    else:
        memory.public_beta_assert_writable_authority(target, mode)
        memory.ensure_layout(target, mode)
        if not (target / ".ai-verse-memory" / "profile.md").exists():
            installer.source_copy("templates/profile.md", target / ".ai-verse-memory" / "profile.md", source_dir, target_root=target)
        installer.install_skills(target, source_dir)
        installer.replace_marker_block(target / "AGENTS.md", installer.STANDALONE_BLOCK, target_root=target)
        installer.replace_marker_block(target / "CLAUDE.md", installer.STANDALONE_BLOCK, target_root=target)
        installer.ensure_gitignore(target, ".ai-verse-memory/", "AI-Verse Memory local runtime and personal memory")
        memory.rebuild(silent=True, root=target, mode=mode)
        memory.public_beta_write_component_state(
            target,
            mode,
            installed=True,
            setup_completed=True,
            enabled=True,
            last_action="setup",
        )

    payload = status_payload(target)
    if payload["migration_required"]:
        payload["message"] = (
            "Setup completed without transferring canonical authority. "
            "Review migrate --source-root <old-memory-root>, then apply explicitly."
        )
    else:
        payload["message"] = "Setup completed."
    return payload


def _set_enabled(target: Path, enabled: bool) -> dict:
    payload = status_payload(target)
    if payload["mode"] != memory.MODE_NATIVE:
        raise RuntimeError("enable/disable are native AI-Verse OS attachment actions")
    if not payload["installed"]:
        raise RuntimeError("AI-Verse Memory is not installed")
    installer.set_local_extension_enabled(target, enabled)
    memory.public_beta_write_component_state(
        target,
        memory.MODE_NATIVE,
        installed=True,
        setup_completed=True,
        enabled=enabled,
        last_action="enable" if enabled else "disable",
    )
    payload = status_payload(target)
    payload["message"] = "Memory enabled." if enabled else "Memory disabled. Canonical state was preserved."
    return payload


def _update(target: Path, source_dir: Optional[Path]) -> dict:
    before = status_payload(target)
    mode = before["mode"]
    if mode == "incompatible":
        raise RuntimeError(f"Incompatible AI-Verse OS: {before['compatibility']['reason']}")
    if not before["installed"]:
        payload = _install_package(target, source_dir)
        payload["message"] = "Runtime installed as update target. Setup was not implied."
        return payload
    _copy_runtime(target, mode, source_dir)
    if before["setup_completed"]:
        installer.install_skills(target, source_dir)
    # Registry state is intentionally untouched so update cannot reactivate disabled Memory.
    payload = status_payload(target)
    payload["message"] = "Runtime updated without changing authority, attachment enablement, or user state."
    return payload


def _adapter_dirs(target: Path) -> tuple[Path, Path]:
    return (
        target / ".claude" / "skills" / COMPONENT_ID,
        target / ".agents" / "skills" / COMPONENT_ID,
    )


def _preflight_uninstall_paths(target: Path, mode: str) -> None:
    candidates = [*_adapter_dirs(target), _runtime_dir(target, mode)]
    if mode == memory.MODE_STANDALONE:
        candidates.extend([target / "AGENTS.md", target / "CLAUDE.md"])
        candidates.extend(
            _runtime_dir(target, mode) / name
            for name in (
                "memory.py",
                "memory_engine.py",
                "os_compat.py",
                "public_beta.py",
                "MEMORY-PROTOCOL.md",
                "MIGRATION.md",
                "SCENARIO-TEMPLATE.md",
            )
        )
    for candidate in candidates:
        installer.assert_safe_lifecycle_path(target, candidate)


def _remove_adapter_dirs(target: Path) -> None:
    for path in _adapter_dirs(target):
        path = installer.assert_safe_lifecycle_path(target, path)
        if path.exists():
            if not path.is_dir():
                raise RuntimeError(f"Memory adapter path is not a directory: {path}")
            shutil.rmtree(path)


def _uninstall(target: Path) -> dict:
    before = status_payload(target)
    mode = before["mode"]
    if mode == "incompatible":
        raise RuntimeError("Cannot safely uninstall from an incompatible AI-Verse OS host")
    previous_enabled = before.get("enabled")
    _preflight_uninstall_paths(target, mode)

    if mode == memory.MODE_NATIVE:
        if before.get("attached"):
            installer.unregister_local_extension(target)
        _remove_adapter_dirs(target)
        runtime = installer.assert_safe_lifecycle_path(target, _runtime_dir(target, mode))
        if runtime.exists():
            if not runtime.is_dir():
                raise RuntimeError(f"Memory runtime path is not a directory: {runtime}")
            shutil.rmtree(runtime)
        memory.public_beta_write_component_state(
            target,
            mode,
            installed=False,
            setup_completed=bool(before.get("setup_completed")),
            enabled=previous_enabled,
            last_action="uninstall",
        )
    else:
        _remove_adapter_dirs(target)
        for contract in (target / "AGENTS.md", target / "CLAUDE.md"):
            if contract.exists():
                installer.replace_marker_block(contract, None, target_root=target)
        runtime = _runtime_dir(target, mode)
        for name in (
            "memory.py",
            "memory_engine.py",
            "os_compat.py",
            "public_beta.py",
            "MEMORY-PROTOCOL.md",
            "MIGRATION.md",
            "SCENARIO-TEMPLATE.md",
        ):
            path = installer.assert_safe_lifecycle_path(target, runtime / name)
            if path.exists() and path.is_file():
                path.unlink()
        memory.public_beta_write_component_state(
            target,
            mode,
            installed=False,
            setup_completed=bool(before.get("setup_completed")),
            enabled=previous_enabled,
            last_action="uninstall",
        )

    payload = status_payload(target)
    payload["message"] = "Integration/runtime removed. Canonical Memory state was preserved."
    return payload


def _detach(target: Path) -> dict:
    before = status_payload(target)
    if before["mode"] != memory.MODE_NATIVE:
        raise RuntimeError("detach is a native AI-Verse OS attachment action")
    if before.get("attached"):
        installer.unregister_local_extension(target)
    memory.public_beta_write_component_state(
        target,
        memory.MODE_NATIVE,
        installed=before.get("installed", False),
        setup_completed=before.get("setup_completed", False),
        enabled=before.get("enabled"),
        attached=False,
        last_action="detach",
    )
    payload = status_payload(target)
    payload["message"] = "Local registry attachment removed. Runtime/adapters and canonical Memory were preserved."
    return payload


def _reconcile(target: Path, source_dir: Optional[Path]) -> dict:
    before = status_payload(target)
    mode = before["mode"]
    if mode == "incompatible":
        raise RuntimeError(f"Incompatible AI-Verse OS: {before['compatibility']['reason']}")
    receipt = _component_receipt(target, mode)
    wanted_setup = bool(receipt.get("setup_completed"))
    wanted_enabled = receipt.get("enabled", True)

    if not before["installed"]:
        _copy_runtime(target, mode, source_dir)

    if wanted_setup:
        if mode == memory.MODE_NATIVE:
            installer.install_skills(target, source_dir)
            installer.register_local_extension(target)
            if wanted_enabled is False:
                installer.set_local_extension_enabled(target, False)
            memory.ensure_layout(target, mode)
            memory.rebuild(silent=True, root=target, mode=mode)
        else:
            authority, _, _ = _authority_state(target, mode)
            if authority == "retired":
                raise RuntimeError("Retired standalone Memory cannot be reconciled into an active writer")
            installer.install_skills(target, source_dir)
            installer.replace_marker_block(target / "AGENTS.md", installer.STANDALONE_BLOCK, target_root=target)
            installer.replace_marker_block(target / "CLAUDE.md", installer.STANDALONE_BLOCK, target_root=target)
            memory.ensure_layout(target, mode)
            memory.rebuild(silent=True, root=target, mode=mode)
        memory.public_beta_write_component_state(
            target,
            mode,
            installed=True,
            setup_completed=True,
            enabled=wanted_enabled,
            last_action="reconcile",
        )

    payload = status_payload(target)
    payload["message"] = (
        "Preserved setup state rediscovered and reconciled."
        if wanted_setup
        else "Runtime rediscovered. Setup is still required and was not implied."
    )
    return payload


def doctor_payload(target: Path) -> dict:
    status = status_payload(target)
    checks: List[dict] = []

    def add(depth: str, name: str, ok: bool, detail: str, required: bool = True):
        checks.append({"depth": depth, "name": name, "ok": bool(ok), "required": required, "detail": detail})

    add("structural", "compatible host or standalone root", status["mode"] != "incompatible", status["compatibility"]["reason"])
    runtime = Path(status.get("runtime") or _runtime_path(target, status["mode"] if status["mode"] != "incompatible" else memory.MODE_STANDALONE))
    add("structural", "runtime path", runtime.is_file() and not runtime.is_symlink(), str(runtime), required=status["installed"])

    if status["mode"] == memory.MODE_NATIVE:
        for name, path in (
            ("operator root", target / "operator"),
            ("workspace root", target / "workspaces"),
        ):
            ok = path.is_dir() and not path.is_symlink()
            add("structural", name, ok, str(path))
        entry, registry_error = _registry_state(target)
        add(
            "attachment",
            "local extension registry",
            registry_error is None,
            registry_error or ("attached" if entry else "not attached"),
            required=status["setup_completed"],
        )
        add(
            "attachment",
            "component attached",
            entry is not None,
            "ai-verse-memory registry entry",
            required=status["setup_completed"] and status["state"] != "absent",
        )

    add("dependency", "Python >= 3.9", sys.version_info >= (3, 9), sys.version.split()[0])
    add("runtime", "sqlite3 import", True, sqlite3.sqlite_version)

    if status["mode"] != "incompatible":
        if status["mode"] == memory.MODE_NATIVE:
            db = target / "runtime" / "indexes" / COMPONENT_ID / "memory.db"
        else:
            db = target / ".ai-verse-memory" / "state" / "memory.db"
        if db.exists():
            if db.is_symlink() or not db.is_file():
                add("operational", "derived index readable", False, str(db))
            else:
                try:
                    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
                    conn.execute("SELECT 1").fetchone()
                    conn.close()
                    add("operational", "derived index readable", True, str(db))
                except sqlite3.Error as exc:
                    add("operational", "derived index readable", False, str(exc))
        else:
            add("operational", "derived index present", False, "setup/rebuild required", required=status["setup_completed"])

    migration_ok = not status.get("migration_required", False)
    add("operational", "canonical authority singular", migration_ok, status.get("migration_reason", "no competing legacy writer"))
    add("system-composed", "whole-system readiness", True, "not evaluated by Memory doctor", required=False)

    failures = [item for item in checks if item["required"] and not item["ok"]]
    result = dict(status)
    result["checks"] = checks
    result["doctor"] = "PASS" if not failures else "FAIL"
    result["health"] = "ok" if not failures else "fail"
    result["readiness"] = bool(status.get("readiness")) and not failures
    result["health_depth"] = {
        "structural": "checked",
        "attachment": "checked" if status["mode"] == memory.MODE_NATIVE else "not-applicable",
        "runtime": "checked",
        "dependency": "checked",
        "operational": "checked-read-only",
        "system_composed": "not-checked",
    }
    return result


def _migrate(target: Path, source_root: Path, apply: bool) -> dict:
    status = status_payload(target)
    if status["mode"] != memory.MODE_NATIVE:
        raise RuntimeError("Legacy adoption into AI-Verse OS requires native mode")
    if not status["installed"]:
        raise RuntimeError("Install and setup Memory before migration")
    counts = memory.migrate_legacy(target, apply=apply, source_root=source_root)
    payload = status_payload(target)
    payload["migration"] = counts
    payload["message"] = (
        "Migration applied and canonical authority handoff completed."
        if counts.get("handoff_complete")
        else "Migration plan generated for review." if not apply
        else "Migration copied safe records but authority handoff is pending because blockers remain."
    )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-Verse Memory component lifecycle")
    parser.add_argument("--target", default=os.getenv("AI_VERSE_MEMORY_TARGET", "."))
    parser.add_argument("--source-dir", default=os.getenv("AI_VERSE_MEMORY_SOURCE_DIR"))
    parser.add_argument("--json", action="store_true", help="Emit structured machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("install", "setup", "status", "doctor", "enable", "disable", "update", "uninstall", "reconcile", "detach"):
        sub.add_parser(name)
    migrate = sub.add_parser("migrate", help="Expert: plan/apply explicit legacy Memory adoption")
    migrate.add_argument("--source-root", required=True)
    migrate.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    target = Path(args.target).expanduser().resolve()
    if args.source_dir:
        source_dir = Path(args.source_dir).expanduser().resolve()
    elif (HERE.parent / "manifest.json").exists():
        source_dir = HERE.parent
    else:
        source_dir = None
    try:
        if args.command == "install":
            payload = _install_package(target, source_dir)
        elif args.command == "setup":
            payload = _setup(target, source_dir)
        elif args.command == "status":
            payload = status_payload(target)
        elif args.command == "doctor":
            payload = doctor_payload(target)
        elif args.command == "enable":
            payload = _set_enabled(target, True)
        elif args.command == "disable":
            payload = _set_enabled(target, False)
        elif args.command == "update":
            payload = _update(target, source_dir)
        elif args.command == "uninstall":
            payload = _uninstall(target)
        elif args.command == "reconcile":
            payload = _reconcile(target, source_dir)
        elif args.command == "detach":
            payload = _detach(target)
        elif args.command == "migrate":
            payload = _migrate(target, Path(args.source_root).expanduser(), args.apply)
        else:
            raise RuntimeError(f"Unsupported command: {args.command}")
        _emit(payload, args.json)
        if args.command == "doctor" and payload.get("doctor") == "FAIL":
            return 1
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        error = {
            "schema_version": 1,
            "component": COMPONENT_ID,
            "version": VERSION,
            "state": "unhealthy",
            "readiness": False,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(error, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
