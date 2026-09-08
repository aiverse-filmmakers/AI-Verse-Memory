#!/usr/bin/env python3
"""Cross-platform installer for AI-Verse Memory."""

from __future__ import annotations

import argparse
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

NATIVE_BLOCK = """<!-- AI-VERSE-MEMORY:START -->
## Persistent memory engine

AI-Verse Memory is installed as an optional memory engine. Follow `scripts/ai-verse-memory/MEMORY-PROTOCOL.md` and use `scripts/ai-verse-memory/memory.py` for scoped recall and atomic historical memory.

AI-Verse OS remains the authority for storage and routing: current context, profile, decisions, knowledge, and workspace boundaries stay canonical in the locations defined by `AI-VERSE.yaml`. Memory must never override newer current context, duplicate canonical decisions, or cross workspace boundaries unless the task explicitly requires it.
<!-- AI-VERSE-MEMORY:END -->"""

STANDALONE_BLOCK = """<!-- AI-VERSE-MEMORY:START -->
## Persistent memory

This repository uses AI-Verse Memory. Read `.ai-verse-memory/MEMORY-PROTOCOL.md` and follow it as standing guidance. Before substantial work, recall relevant prior context when it could materially change the task. After meaningful work, persist only durable facts, preferences, constraints, decisions, state transitions, entity details, experiences, or proven workflows. Supersede outdated memories rather than silently rewriting history.
<!-- AI-VERSE-MEMORY:END -->"""


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


def register_capability(target: Path) -> str:
    registry = target / "skills" / "registry.yaml"
    if not registry.exists():
        return "warning: skills/registry.yaml not found; runtime skill adapters were still installed"
    text = registry.read_text(encoding="utf-8", errors="replace")
    if re.search(r"(?m)^\s*-\s+id:\s+ai-verse-memory\s*$", text):
        return "already registered"

    block = (
        "  - id: ai-verse-memory\n"
        "    scope: universal-extension\n"
        "    purpose: \"Provide scoped persistent historical memory, provenance, supersession, and rebuildable local recall without creating a second source of truth.\"\n"
    )
    marker = re.search(r"(?m)^promotion_rule:", text)
    if marker:
        text = text[: marker.start()] + block + "\n" + text[marker.start() :]
    elif re.search(r"(?m)^capabilities:\s*$", text):
        text = text.rstrip() + "\n" + block
    else:
        return "warning: registry format not recognized; left unchanged"
    registry.write_text(text, encoding="utf-8")
    return "registered"


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

    agents = target / "AGENTS.md"
    if agents.exists():
        replace_marker_block(agents, NATIVE_BLOCK)
    else:
        print("warning: AGENTS.md not found; native standing integration was not added")

    # AI-Verse OS v2 defines CLAUDE.md as an adapter, not a second runtime contract.
    claude = target / "CLAUDE.md"
    if claude.exists():
        replace_marker_block(claude, None)

    print(f"Capability registry: {register_capability(target)}")
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
    parser = argparse.ArgumentParser(description="Install AI-Verse Memory")
    parser.add_argument("--target", default=os.getenv("AI_VERSE_MEMORY_TARGET", "."))
    parser.add_argument("--source-dir", default=os.getenv("AI_VERSE_MEMORY_SOURCE_DIR"))
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    source_dir = Path(args.source_dir).expanduser().resolve() if args.source_dir else None
    target.mkdir(parents=True, exist_ok=True)

    native = detect_native(target)
    print(f"AI-Verse Memory {VERSION}")
    print(f"Target: {target}")
    print(f"Mode: {'ai-verse-os-v2' if native else 'standalone'}")

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
