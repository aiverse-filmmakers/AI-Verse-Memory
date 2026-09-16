#!/usr/bin/env python3
"""Compatibility-gated installer entrypoint for AI-Verse Memory."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load_sibling(module_name: str, filename: str):
    path = _HERE / filename
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load required Memory installer component: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_compat = _load_sibling("_aiverse_memory_installer_os_compat", "os_compat.py")
_installer = _load_sibling("_aiverse_memory_installer_engine", "install_engine.py")

for _name in dir(_installer):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_installer, _name)


def detect_os_compatibility(target: Path):
    return _compat.detect_os_compatibility(Path(target))


def detect_native(target: Path) -> bool:
    result = _compat.require_supported_os_or_none(Path(target))
    return result.status == _compat.OS_COMPATIBLE


_original_source_copy = _installer.source_copy


def source_copy(relative: str, destination: Path, source_dir, target_root=None):
    """Copy a requested file and keep the installed engine gate self-contained."""
    _original_source_copy(relative, destination, source_dir, target_root=target_root)
    if relative == "scripts/memory.py":
        _original_source_copy("scripts/memory_engine.py", destination.parent / "memory_engine.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/os_compat.py", destination.parent / "os_compat.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/public_beta.py", destination.parent / "public_beta.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/session_digest.py", destination.parent / "session_digest.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/session_digest_index.py", destination.parent / "session_digest_index.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/session_promotion.py", destination.parent / "session_promotion.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/orientation_map.py", destination.parent / "orientation_map.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/progressive_recall.py", destination.parent / "progressive_recall.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/relationship_projection.py", destination.parent / "relationship_projection.py", source_dir, target_root=target_root)
    elif relative == "scripts/component.py":
        _original_source_copy("scripts/install.py", destination.parent / "install.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/install_engine.py", destination.parent / "install_engine.py", source_dir, target_root=target_root)
        _original_source_copy("scripts/os_compat.py", destination.parent / "os_compat.py", source_dir, target_root=target_root)


_installer.detect_native = detect_native
_installer.source_copy = source_copy


def main() -> int:
    try:
        return _installer.main()
    except RuntimeError as exc:
        if str(exc).startswith("Incompatible AI-Verse OS:"):
            print(f"AI-Verse Memory install blocked: {exc}", file=sys.stderr)
            return 2
        raise


if __name__ == "__main__":
    raise SystemExit(main())
