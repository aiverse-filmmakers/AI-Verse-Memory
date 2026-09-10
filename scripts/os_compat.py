#!/usr/bin/env python3
"""Shared AI-Verse OS compatibility detection for installer and memory engine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

OS_NONE = "no-os"
OS_COMPATIBLE = "compatible"
OS_INCOMPATIBLE = "incompatible"
SUPPORTED_SCHEMA_MAJOR = 2
SUPPORTED_ARCHITECTURE = "unified-workspace"


@dataclass(frozen=True)
class OSCompatibility:
    status: str
    reason: str
    schema_version: Optional[str] = None
    architecture: Optional[str] = None

    @property
    def compatible(self) -> bool:
        return self.status == OS_COMPATIBLE

    @property
    def has_os(self) -> bool:
        return self.status != OS_NONE


def _top_level_scalar(text: str, key: str) -> tuple[Optional[str], Optional[str]]:
    """Return a unique top-level scalar, or a validation error."""
    matches = re.findall(rf"(?m)^{re.escape(key)}:\s*([^#\r\n]+?)\s*$", text)
    if not matches:
        return None, f"AI-VERSE.yaml is missing required top-level key {key!r}"
    if len(matches) != 1:
        return None, f"AI-VERSE.yaml contains duplicate top-level key {key!r}"
    value = matches[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    if not value:
        return None, f"AI-VERSE.yaml has an empty {key!r} value"
    return value, None


def detect_os_compatibility(root: Path) -> OSCompatibility:
    """Classify a target as no OS, compatible AI-Verse OS, or incompatible OS.

    Standalone mode is allowed only when AI-VERSE.yaml is genuinely absent.
    Once an AI-Verse manifest exists, malformed or unsupported hosts fail closed.
    """
    root = Path(root).expanduser().resolve()
    manifest = root / "AI-VERSE.yaml"

    if not manifest.exists():
        return OSCompatibility(OS_NONE, "AI-VERSE.yaml is absent")
    if manifest.is_symlink():
        return OSCompatibility(OS_INCOMPATIBLE, "AI-VERSE.yaml must not be a symlink")
    if not manifest.is_file():
        return OSCompatibility(OS_INCOMPATIBLE, "AI-VERSE.yaml is not a regular file")

    try:
        text = manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return OSCompatibility(OS_INCOMPATIBLE, f"AI-VERSE.yaml is unreadable: {exc}")

    schema, error = _top_level_scalar(text, "schema_version")
    if error:
        return OSCompatibility(OS_INCOMPATIBLE, error)
    architecture, error = _top_level_scalar(text, "architecture")
    if error:
        return OSCompatibility(OS_INCOMPATIBLE, error, schema_version=schema)

    version_match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", schema or "")
    if not version_match:
        return OSCompatibility(
            OS_INCOMPATIBLE,
            f"Unsupported or malformed AI-Verse OS schema_version {schema!r}",
            schema_version=schema,
            architecture=architecture,
        )
    major = int(version_match.group(1))
    if major != SUPPORTED_SCHEMA_MAJOR:
        return OSCompatibility(
            OS_INCOMPATIBLE,
            f"AI-Verse Memory supports AI-Verse OS schema major {SUPPORTED_SCHEMA_MAJOR}; found {schema}",
            schema_version=schema,
            architecture=architecture,
        )
    if architecture != SUPPORTED_ARCHITECTURE:
        return OSCompatibility(
            OS_INCOMPATIBLE,
            f"Unsupported AI-Verse OS architecture {architecture!r}; expected {SUPPORTED_ARCHITECTURE!r}",
            schema_version=schema,
            architecture=architecture,
        )

    missing = []
    for relative in ("operator", "workspaces"):
        candidate = root / relative
        if not candidate.exists() or not candidate.is_dir():
            missing.append(relative + "/")
    if missing:
        return OSCompatibility(
            OS_INCOMPATIBLE,
            "AI-Verse OS v2 layout is incomplete; missing " + ", ".join(missing),
            schema_version=schema,
            architecture=architecture,
        )

    return OSCompatibility(
        OS_COMPATIBLE,
        "compatible AI-Verse OS v2 unified-workspace host",
        schema_version=schema,
        architecture=architecture,
    )


def require_supported_os_or_none(root: Path) -> OSCompatibility:
    result = detect_os_compatibility(root)
    if result.status == OS_INCOMPATIBLE:
        raise RuntimeError(f"Incompatible AI-Verse OS: {result.reason}")
    return result
