#!/usr/bin/env python3
"""Compatibility-gated entrypoint for the AI-Verse Memory engine."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent


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
