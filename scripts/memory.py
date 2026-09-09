#!/usr/bin/env python3
"""AI-Verse Memory Engine: local-first Markdown memory with a rebuildable SQLite index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

VERSION = "0.2.0"
MODE_NATIVE = "ai-verse-os-v2"
MODE_STANDALONE = "standalone"

MEMORY_TYPES = {
    "fact",
    "preference",
    "constraint",
    "decision",
    "state",
    "project_state",  # legacy alias retained for existing memories
    "entity",
    "event",
    "experience",
    "workflow",
}

SKIP_DIRS = {
    ".git",
    ".ai-verse-memory",
    ".claude",
    ".agents",
    "runtime",
    "system",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "venv",
    "__pycache__",
    ".cache",
}
DISCOVERY_EXTS = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv"}

KIND_AUTHORITY = {
    "context": 5.0,
    "workspace_manifest": 4.8,
    "decision": 4.6,
    "profile": 4.3,
    "memory_summary": 3.4,
    "scenario": 3.0,
    "memory": 2.5,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return value or "operator"


def repository_root(explicit: Optional[str] = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env_root = os.getenv("AI_VERSE_MEMORY_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    script = Path(__file__).resolve()
    if script.parent.name == ".ai-verse-memory":
        return script.parent.parent
    if script.parent.name == "ai-verse-memory" and script.parent.parent.name == "scripts":
        return script.parent.parent.parent
    return Path.cwd().resolve()


def detect_mode(root: Optional[Path] = None) -> str:
    root = (root or repository_root()).resolve()
    manifest = root / "AI-VERSE.yaml"
    if not manifest.exists():
        return MODE_STANDALONE
    text = manifest.read_text(encoding="utf-8", errors="replace")
    schema_v2 = bool(re.search(r"(?m)^schema_version:\s*[\"']?2(?:\.\d+)?[\"']?\s*$", text))
    unified = bool(re.search(r"(?m)^architecture:\s*[\"']?unified-workspace[\"']?\s*$", text))
    if schema_v2 and unified and (root / "operator").exists() and (root / "workspaces").exists():
        return MODE_NATIVE
    return MODE_STANDALONE


def workspace_ids(root: Optional[Path] = None) -> List[str]:
    root = root or repository_root()
    base = root / "workspaces"
    if not base.exists():
        return []
    result = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        if (child / "WORKSPACE.yaml").exists():
            result.append(child.name)
    return result


def normalize_scope(scope: Optional[str], root: Optional[Path] = None, mode: Optional[str] = None) -> str:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    raw = (scope or ("operator" if mode == MODE_NATIVE else "global")).strip()
    if mode == MODE_STANDALONE:
        return raw or "global"

    if raw in {"", "global", "operator"}:
        return "operator"
    if raw.startswith("workspace:"):
        wid = raw.split(":", 1)[1].strip()
        if not wid:
            raise ValueError("Workspace scope requires an id, for example workspace:example")
        if wid not in workspace_ids(root):
            raise ValueError(f"Unknown workspace: {wid}. Create it through AI-Verse OS before storing workspace memory.")
        return f"workspace:{wid}"
    for legacy_prefix in ("project:", "client:"):
        if raw.startswith(legacy_prefix):
            wid = raw.split(":", 1)[1].strip()
            if wid in workspace_ids(root):
                return f"workspace:{wid}"
            raise ValueError(
                f"Legacy scope {raw} has no matching AI-Verse workspace. Use /workspace first or migrate it deliberately."
            )
    raise ValueError(
        f"Unsupported native scope: {raw}. AI-Verse OS v2 memory uses operator or workspace:<id>."
    )


def paths(root: Optional[Path] = None, mode: Optional[str] = None) -> Dict[str, Path]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    if mode == MODE_NATIVE:
        state = root / "operator" / "memory" / ".ai-verse-memory-state"
        return {
            "root": root,
            "operator_memory": root / "operator" / "memory",
            "operator_atomic": root / "operator" / "memory" / "atomic",
            "state": state,
            "db": root / "runtime" / "indexes" / "ai-verse-memory" / "memory.db",
            "migration": state / "migration.json",
            "legacy_home": root / ".ai-verse-memory",
        }

    home = Path(os.getenv("AI_VERSE_MEMORY_HOME", root / ".ai-verse-memory")).expanduser().resolve()
    return {
        "root": root,
        "home": home,
        "memories": home / "memories",
        "scenarios": home / "scenarios",
        "evidence": home / "evidence",
        "state": home / "state",
        "profile": home / "profile.md",
        "db": home / "state" / "memory.db",
        "migration": home / "state" / "migration.json",
        "legacy_home": home,
    }


def ensure_layout(root: Optional[Path] = None, mode: Optional[str] = None) -> Dict[str, Path]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = paths(root, mode)

    if mode == MODE_NATIVE:
        p["operator_memory"].mkdir(parents=True, exist_ok=True)
        p["operator_atomic"].mkdir(parents=True, exist_ok=True)
        p["state"].mkdir(parents=True, exist_ok=True)
        p["db"].parent.mkdir(parents=True, exist_ok=True)
        return p

    for key in ("home", "memories", "scenarios", "evidence", "state"):
        p[key].mkdir(parents=True, exist_ok=True)
    if not p["profile"].exists():
        p["profile"].write_text(
            "# Memory Profile\n\n"
            "> Stable, broadly useful context only. Keep volatile state in atomic memories or scenarios.\n\n"
            "## Identity and role\n\n"
            "## Stable preferences\n\n"
            "## Durable constraints\n\n"
            "## Long-term priorities\n",
            encoding="utf-8",
        )
    return p


def clean_scalar(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ").strip()


def render_frontmatter(meta: Dict[str, str]) -> str:
    order = [
        "id",
        "type",
        "scope",
        "status",
        "importance",
        "confidence",
        "created_at",
        "updated_at",
        "valid_from",
        "valid_to",
        "supersedes",
        "superseded_by",
        "source",
        "tags",
        "legacy_scope",
    ]
    lines = ["---"]
    emitted = set()
    for key in order:
        if key in meta:
            lines.append(f"{key}: {clean_scalar(str(meta.get(key, '')))}")
            emitted.add(key)
    for key in sorted(k for k in meta if k not in emitted):
        lines.append(f"{key}: {clean_scalar(str(meta[key]))}")
    lines.append("---")
    return "\n".join(lines)


def parse_markdown(path: Path) -> Tuple[Dict[str, str], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return {}, text.strip()
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text.strip()
    raw = text[4:end]
    body = text[end + 5 :].strip()
    meta: Dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def extract_sections(body: str) -> Tuple[str, str]:
    memory_text = body
    why = ""
    m = re.search(r"(?ms)^# Memory\s*\n(.*?)(?=^# Why it matters\s*$|\Z)", body)
    if m:
        memory_text = m.group(1).strip()
    w = re.search(r"(?ms)^# Why it matters\s*\n(.*?)(?=^# |\Z)", body)
    if w:
        why = w.group(1).strip()
    return memory_text, why


def memory_id(text: str, scope: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    digest = hashlib.sha1(f"{scope}\n{text}".encode("utf-8")).hexdigest()[:8]
    return f"mem-{stamp}-{digest}"


def atomic_dir_for_scope(scope: str, root: Optional[Path] = None, mode: Optional[str] = None) -> Path:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    scope = normalize_scope(scope, root, mode)
    p = ensure_layout(root, mode)
    if mode == MODE_STANDALONE:
        return p["memories"]
    if scope == "operator":
        return p["operator_atomic"]
    wid = scope.split(":", 1)[1]
    folder = root / "workspaces" / wid / "memory" / "atomic"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def atomic_path(mem_id: str, created_at: str, scope: str, root: Optional[Path] = None, mode: Optional[str] = None) -> Path:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    base = atomic_dir_for_scope(scope, root, mode)
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    folder = base / f"{dt.year:04d}" / f"{dt.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{mem_id}.md"



def _atomic_scope_from_relative_parts(parts: Tuple[str, ...], root: Path) -> str:
    if len(parts) >= 3 and parts[:3] == ("operator", "memory", "atomic"):
        return "operator"
    if len(parts) >= 4 and parts[0] == "workspaces" and parts[2:4] == ("memory", "atomic"):
        wid = parts[1]
        if wid not in workspace_ids(root):
            raise ValueError(f"Atomic memory belongs to unknown workspace: {wid}")
        return f"workspace:{wid}"
    raise ValueError("Atomic memory path is outside authorized native memory roots")


def _iter_atomic_candidates(root: Path, mode: str) -> Iterable[Path]:
    p = ensure_layout(root, mode)
    if mode == MODE_STANDALONE:
        yield from sorted(p["memories"].rglob("*.md"))
        return

    yield from sorted(p["operator_atomic"].rglob("*.md"))
    for wid in workspace_ids(root):
        base = root / "workspaces" / wid / "memory" / "atomic"
        if base.exists():
            yield from sorted(base.rglob("*.md"))


def infer_scope_from_path(path: Path, root: Path, mode: str) -> str:
    if mode == MODE_STANDALONE:
        return "global"

    root_lexical = Path(os.path.abspath(root))
    path_lexical = Path(os.path.abspath(path))
    try:
        lexical_rel = path_lexical.relative_to(root_lexical)
    except ValueError as exc:
        raise ValueError(f"Atomic memory path escapes repository root: {path}") from exc
    lexical_scope = _atomic_scope_from_relative_parts(lexical_rel.parts, root)

    try:
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"Atomic memory path cannot be resolved safely: {path}") from exc
    if not resolved_path.is_file():
        raise ValueError(f"Atomic memory path is not a regular file: {path}")
    try:
        resolved_rel = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Atomic memory path resolves outside repository root: {path}") from exc

    physical_scope = _atomic_scope_from_relative_parts(resolved_rel.parts, root)
    if physical_scope != lexical_scope:
        raise ValueError(
            f"Atomic memory path crosses scope boundary: lexical {lexical_scope}, resolved {physical_scope}"
        )
    return physical_scope


def _validated_atomic_scope(path: Path, root: Path, mode: str, meta: Dict[str, str]) -> str:
    physical = infer_scope_from_path(path, root, mode)
    if mode == MODE_STANDALONE:
        return meta.get("scope") or physical
    raw_declared = (meta.get("scope") or "").strip()
    if not raw_declared:
        return physical
    declared = normalize_scope(raw_declared, root, mode)
    if declared != physical:
        raise ValueError(f"Declared scope {declared} disagrees with physical scope {physical}")
    return physical


def iter_atomic_files(root: Optional[Path] = None, mode: Optional[str] = None) -> Iterable[Path]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    if mode == MODE_STANDALONE:
        yield from _iter_atomic_candidates(root, mode)
        return

    for path in _iter_atomic_candidates(root, mode):
        try:
            infer_scope_from_path(path, root, mode)
            meta, _ = parse_markdown(path)
            _validated_atomic_scope(path, root, mode, meta)
        except (ValueError, OSError):
            continue
        yield path


def relpath(path: Path, root: Optional[Path] = None) -> str:
    root = root or repository_root()
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def connect_db(root: Optional[Path] = None, mode: Optional[str] = None, reset: bool = False) -> Tuple[sqlite3.Connection, bool]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = ensure_layout(root, mode)
    conn = sqlite3.connect(p["db"])
    conn.row_factory = sqlite3.Row
    if reset:
        conn.execute("DROP TABLE IF EXISTS items")
        try:
            conn.execute("DROP TABLE IF EXISTS item_fts")
        except sqlite3.OperationalError:
            pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            type TEXT,
            scope TEXT,
            status TEXT,
            importance REAL,
            confidence REAL,
            created_at TEXT,
            updated_at TEXT,
            source TEXT,
            tags TEXT,
            text TEXT NOT NULL,
            why TEXT,
            authority REAL
        )
        """
    )
    fts = True
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS item_fts USING fts5(id UNINDEXED, text, why, tags, scope, type, kind)"
        )
    except sqlite3.OperationalError:
        fts = False
    return conn, fts



def index_atomic(path: Path, root: Path, mode: str) -> Optional[Tuple]:
    if mode == MODE_NATIVE:
        try:
            infer_scope_from_path(path, root, mode)
        except (ValueError, OSError):
            return None
    try:
        meta, body = parse_markdown(path)
    except OSError:
        return None
    if not meta.get("id"):
        return None
    text, why = extract_sections(body)
    try:
        scope = _validated_atomic_scope(path, root, mode, meta)
    except (ValueError, OSError):
        return None
    return (
        meta.get("id", path.stem),
        "memory",
        relpath(path, root),
        meta.get("type", "fact"),
        scope,
        meta.get("status", "active"),
        float(meta.get("importance", "3") or 3),
        float(meta.get("confidence", "1") or 1),
        meta.get("created_at", ""),
        meta.get("updated_at", ""),
        meta.get("source", ""),
        meta.get("tags", ""),
        text,
        why,
        KIND_AUTHORITY["memory"],
    )


def index_document(path: Path, root: Path, kind: str, scope: str, importance: float) -> Tuple:
    if path.suffix.lower() == ".md":
        meta, body = parse_markdown(path)
    else:
        meta = {}
        body = path.read_text(encoding="utf-8", errors="replace").strip()
    doc_hash = hashlib.sha1(relpath(path, root).encode("utf-8")).hexdigest()[:12]
    doc_id = meta.get("id") or f"{kind}:{doc_hash}"
    return (
        doc_id,
        kind,
        relpath(path, root),
        meta.get("type", kind),
        scope,
        meta.get("status", "active"),
        float(meta.get("importance", importance) or importance),
        float(meta.get("confidence", "1") or 1),
        meta.get("created_at", ""),
        meta.get("updated_at", ""),
        meta.get("source", ""),
        meta.get("tags", ""),
        body,
        "",
        KIND_AUTHORITY.get(kind, 2.0),
    )


def _iter_non_readme_md(base: Path, recursive: bool = True) -> Iterable[Path]:
    if not base.exists():
        return []
    iterator = base.rglob("*.md") if recursive else base.glob("*.md")
    return [p for p in iterator if p.name.lower() != "readme.md" and not any(part.startswith(".") for part in p.relative_to(base).parts)]


def native_documents(root: Path) -> Iterable[Tuple[Path, str, str, float]]:
    for path in _iter_non_readme_md(root / "operator" / "profile"):
        yield path, "profile", "operator", 5.0
    for path in _iter_non_readme_md(root / "operator" / "context"):
        yield path, "context", "operator", 5.0
    for path in _iter_non_readme_md(root / "operator" / "decisions"):
        yield path, "decision", "operator", 5.0
    for path in _iter_non_readme_md(root / "operator" / "memory", recursive=False):
        yield path, "memory_summary", "operator", 4.0

    for wid in workspace_ids(root):
        scope = f"workspace:{wid}"
        workspace = root / "workspaces" / wid
        manifest = workspace / "WORKSPACE.yaml"
        if manifest.exists():
            yield manifest, "workspace_manifest", scope, 5.0
        for path in _iter_non_readme_md(workspace / "context"):
            yield path, "context", scope, 5.0
        for path in _iter_non_readme_md(workspace / "decisions"):
            yield path, "decision", scope, 5.0
        for path in _iter_non_readme_md(workspace / "memory", recursive=False):
            yield path, "memory_summary", scope, 4.0


def rebuild(silent: bool = False, root: Optional[Path] = None, mode: Optional[str] = None) -> int:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    ensure_layout(root, mode)
    conn, fts = connect_db(root, mode, reset=True)

    rows: List[Tuple] = []
    for file in iter_atomic_files(root, mode):
        row = index_atomic(file, root, mode)
        if row:
            rows.append(row)

    if mode == MODE_NATIVE:
        for path, kind, scope, importance in native_documents(root):
            rows.append(index_document(path, root, kind, scope, importance))
    else:
        p = paths(root, mode)
        if p["profile"].exists():
            rows.append(index_document(p["profile"], root, "profile", "global", 5.0))
        for file in sorted(p["scenarios"].glob("*.md")):
            meta, _ = parse_markdown(file)
            scope = meta.get("scope", "global")
            rows.append(index_document(file, root, "scenario", scope, 4.0))

    conn.executemany(
        """
        INSERT OR REPLACE INTO items
        (id, kind, path, type, scope, status, importance, confidence, created_at, updated_at, source, tags, text, why, authority)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    if fts:
        conn.executemany(
            "INSERT INTO item_fts (id, text, why, tags, scope, type, kind) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(r[0], r[12], r[13], r[11], r[4], r[3], r[1]) for r in rows],
        )
    conn.commit()
    conn.close()
    if not silent:
        print(f"Rebuilt index: {len(rows)} item(s). Mode={mode}. FTS5={'yes' if fts else 'no; lexical fallback active'}")
    return len(rows)


def find_exact_active(text: str, scope: str, root: Path, mode: str) -> Optional[Tuple[str, str]]:
    p = ensure_layout(root, mode)
    if not p["db"].exists():
        rebuild(silent=True, root=root, mode=mode)
    conn, _ = connect_db(root, mode)
    row = conn.execute(
        "SELECT id, path FROM items WHERE kind='memory' AND status='active' AND lower(trim(text))=lower(trim(?)) AND scope=? LIMIT 1",
        (text, scope),
    ).fetchone()
    conn.close()
    if row:
        return row["id"], row["path"]
    return None


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
) -> Tuple[str, Path, bool]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    ensure_layout(root, mode)
    if mem_type not in MEMORY_TYPES:
        raise ValueError(f"Unsupported memory type: {mem_type}")
    text = text.strip()
    if not text:
        raise ValueError("Memory text cannot be empty")
    normalized_scope = normalize_scope(scope, root, mode)

    duplicate = find_exact_active(text, normalized_scope, root, mode)
    if duplicate and not force:
        return duplicate[0], root / duplicate[1], False

    created = now_iso()
    mem_id = memory_id(text, normalized_scope)
    path = atomic_path(mem_id, created, normalized_scope, root, mode)
    normalized_type = "state" if mem_type == "project_state" and mode == MODE_NATIVE else mem_type
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
    body = f"# Memory\n\n{text}\n"
    if why.strip():
        body += f"\n# Why it matters\n\n{why.strip()}\n"
    path.write_text(render_frontmatter(meta) + "\n\n" + body, encoding="utf-8")
    rebuild(silent=True, root=root, mode=mode)
    return mem_id, path, True


def tokenize(value: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]{2,}", value)]


def parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def row_haystack(row: sqlite3.Row) -> str:
    return " ".join(
        [
            row["text"] or "",
            row["why"] or "",
            row["tags"] or "",
            row["type"] or "",
            row["scope"] or "",
            row["kind"] or "",
        ]
    ).lower()


def row_matches_query(row: sqlite3.Row, query: str) -> bool:
    terms = set(tokenize(query))
    if not terms:
        return False
    hay = row_haystack(row)
    words = set(tokenize(hay))
    return bool(terms & words) or query.strip().lower() in hay


def allowed_scopes(
    root: Path,
    mode: str,
    scope: Optional[str] = None,
    workspace: Optional[str] = None,
    all_workspaces: bool = False,
) -> Tuple[Optional[List[str]], Optional[str]]:
    if mode == MODE_STANDALONE:
        if scope:
            normalized = normalize_scope(scope, root, mode)
            return [normalized, "global"] if normalized != "global" else ["global"], normalized
        return None, None

    if all_workspaces:
        return None, None
    if workspace:
        normalized = normalize_scope(f"workspace:{workspace}", root, mode)
        return [normalized, "operator"], normalized
    if scope:
        normalized = normalize_scope(scope, root, mode)
        if normalized.startswith("workspace:"):
            return [normalized, "operator"], normalized
        return ["operator"], "operator"
    return ["operator"], "operator"


def custom_score(row: sqlite3.Row, query: str, primary_scope: Optional[str]) -> float:
    q = set(tokenize(query))
    hay = row_haystack(row)
    words = set(tokenize(hay))
    overlap = len(q & words)
    score = overlap * 2.0
    if query.strip().lower() in hay:
        score += 4.0
    if primary_scope:
        if row["scope"] == primary_scope:
            score += 3.0
        elif row["scope"] in {"operator", "global"}:
            score += 0.6
    score += min(5.0, float(row["importance"] or 3)) * 0.35
    score += max(0.0, min(1.0, float(row["confidence"] or 1))) * 0.4
    score += float(row["authority"] or 0.0) * 0.22
    updated = parse_dt(row["updated_at"] or row["created_at"] or "")
    if updated:
        age_days = max(0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).days)
        score += max(0.0, 1.0 - min(age_days, 3650) / 3650.0)
    return score



def _indexed_memory_source_is_valid(row: sqlite3.Row, root: Path, mode: str) -> bool:
    if mode != MODE_NATIVE or row["kind"] != "memory":
        return True
    stored = Path(row["path"] or "")
    if stored.is_absolute() or not stored.parts:
        return False
    source = root / stored
    try:
        physical = infer_scope_from_path(source, root, mode)
        meta, _ = parse_markdown(source)
        if meta.get("id") != row["id"]:
            return False
        validated = _validated_atomic_scope(source, root, mode, meta)
    except (ValueError, OSError):
        return False
    return validated == physical == row["scope"]


def recall(
    query: str,
    scope: Optional[str] = None,
    limit: int = 8,
    include_history: bool = False,
    root: Optional[Path] = None,
    mode: Optional[str] = None,
    workspace: Optional[str] = None,
    all_workspaces: bool = False,
) -> List[sqlite3.Row]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = ensure_layout(root, mode)
    if not p["db"].exists():
        rebuild(silent=True, root=root, mode=mode)
    conn, fts = connect_db(root, mode)
    scopes, primary_scope = allowed_scopes(root, mode, scope, workspace, all_workspaces)

    status_clause = "" if include_history else "AND i.status='active'"
    scope_clause = ""
    params: List[str] = []
    if scopes:
        placeholders = ",".join("?" for _ in scopes)
        scope_clause = f"AND i.scope IN ({placeholders})"
        params.extend(scopes)

    candidates: List[sqlite3.Row] = []
    terms = tokenize(query)
    used_fts = False
    if fts and terms:
        fts_query = " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms[:12])
        try:
            sql = f"""
                SELECT i.* FROM item_fts f
                JOIN items i ON i.id=f.id
                WHERE item_fts MATCH ? {status_clause} {scope_clause}
                LIMIT 200
            """
            candidates = conn.execute(sql, [fts_query] + params).fetchall()
            used_fts = True
        except sqlite3.OperationalError:
            used_fts = False

    if not used_fts:
        sql = f"""
            SELECT i.* FROM items i
            WHERE 1=1 {status_clause} {scope_clause}
            ORDER BY i.importance DESC, i.updated_at DESC
            LIMIT 2000
        """
        candidates = conn.execute(sql, params).fetchall()

    candidates = [
        row
        for row in candidates
        if _indexed_memory_source_is_valid(row, root, mode) and row_matches_query(row, query)
    ]
    ranked = sorted(candidates, key=lambda r: custom_score(r, query, primary_scope), reverse=True)
    conn.close()
    return ranked[: max(1, min(50, limit))]


def update_meta(path: Path, changes: Dict[str, str]) -> None:
    meta, body = parse_markdown(path)
    if not meta:
        raise ValueError(f"Not an AI-Verse atomic memory: {path}")
    meta.update(changes)
    meta["updated_at"] = now_iso()
    path.write_text(render_frontmatter(meta) + "\n\n" + body.strip() + "\n", encoding="utf-8")


def locate_memory(mem_id: str, root: Optional[Path] = None, mode: Optional[str] = None) -> Optional[Path]:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    for path in iter_atomic_files(root, mode):
        if path.name == f"{mem_id}.md":
            return path
    return None


def show_memory(mem_id: str, root: Optional[Path] = None, mode: Optional[str] = None) -> None:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    path = locate_memory(mem_id, root, mode)
    if not path:
        raise SystemExit(f"Memory not found: {mem_id}")
    print(path.read_text(encoding="utf-8", errors="replace"))
    print(f"\nPath: {relpath(path, root)}")


def forget_memory(mem_id: str, confirmed: bool, root: Optional[Path] = None, mode: Optional[str] = None) -> None:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    path = locate_memory(mem_id, root, mode)
    if not path:
        raise SystemExit(f"Memory not found: {mem_id}")
    if not confirmed:
        raise SystemExit(f"Refusing to delete {mem_id} without --yes. This removes canonical Markdown memory.")
    path.unlink()
    rebuild(silent=True, root=root, mode=mode)
    print(f"Forgot: {mem_id}")


def supersede(args: argparse.Namespace, root: Path, mode: str) -> None:
    old_path = locate_memory(args.id, root, mode)
    if not old_path:
        raise SystemExit(f"Memory not found: {args.id}")
    old_meta, _ = parse_markdown(old_path)
    new_type = args.type or old_meta.get("type", "fact")
    new_scope = args.scope or old_meta.get("scope") or infer_scope_from_path(old_path, root, mode)
    if args.workspace:
        new_scope = f"workspace:{args.workspace}"
    new_id, new_path, created = write_atomic(
        text=args.text,
        mem_type=new_type,
        scope=new_scope,
        importance=args.importance if args.importance is not None else int(old_meta.get("importance", "3") or 3),
        confidence=args.confidence if args.confidence is not None else float(old_meta.get("confidence", "1") or 1),
        source=args.source,
        why=args.why,
        tags=args.tags or old_meta.get("tags", ""),
        valid_from=args.valid_from,
        supersedes=args.id,
        force=True,
        root=root,
        mode=mode,
    )
    if created:
        update_meta(
            old_path,
            {"status": "superseded", "valid_to": now_iso(), "superseded_by": new_id},
        )
        rebuild(silent=True, root=root, mode=mode)
    print(f"Superseded {args.id} -> {new_id}")
    print(relpath(new_path, root))


def discovery_score(path: Path) -> Tuple[int, str]:
    s = str(path).lower()
    clues = []
    score = 0
    for token, weight in [
        ("current", 7),
        ("context", 6),
        ("memory", 6),
        ("decision", 6),
        ("preference", 5),
        ("profile", 5),
        ("workspace", 5),
        ("notes", 4),
        ("transcript", 5),
        ("conversation", 5),
        ("archive", 3),
        ("project", 3),
        ("readme", 2),
        ("reference", 3),
    ]:
        if token in s:
            score += weight
            clues.append(token)
    return score, ", ".join(clues[:5]) or "general text source"


def discover(root: Path, output: Optional[Path], max_files: int) -> List[Tuple[Path, int, str]]:
    root = root.resolve()
    found: List[Tuple[Path, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() not in DISCOVERY_EXTS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size == 0 or size > 20 * 1024 * 1024:
                continue
            score, reason = discovery_score(path)
            found.append((path, score, reason))
    found.sort(key=lambda x: (x[1], -x[0].stat().st_size), reverse=True)
    found = found[:max_files]

    lines = [
        "# AI-Verse Memory Discovery Report",
        "",
        f"Generated: {now_iso()}",
        f"Root: `{root}`",
        "",
        "This is a candidate list, not an instruction to import everything. Distill only durable historical memory and keep current canonical sources authoritative.",
        "",
        "| Priority | File | Size | Why inspect |",
        "|---:|---|---:|---|",
    ]
    for path, score, reason in found:
        try:
            display = path.relative_to(root)
        except ValueError:
            display = path
        size = path.stat().st_size
        lines.append(f"| {score} | `{display}` | {size:,} B | {reason} |")
    report = "\n".join(lines) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        print(f"Discovery report: {output}")
    else:
        print(report)
    return found


def map_legacy_scope(raw_scope: str, root: Path) -> Optional[str]:
    raw_scope = (raw_scope or "global").strip()
    if raw_scope in {"global", "operator"}:
        return "operator"
    if raw_scope.startswith("workspace:"):
        wid = raw_scope.split(":", 1)[1]
        return f"workspace:{wid}" if wid in workspace_ids(root) else None
    for prefix in ("project:", "client:"):
        if raw_scope.startswith(prefix):
            wid = raw_scope.split(":", 1)[1]
            return f"workspace:{wid}" if wid in workspace_ids(root) else None
    return None


def migrate_legacy(root: Path, apply: bool = False) -> Dict[str, int]:
    mode = detect_mode(root)
    if mode != MODE_NATIVE:
        raise ValueError("migrate-legacy is only for AI-Verse OS v2 native mode")
    legacy = root / ".ai-verse-memory"
    old_memories = legacy / "memories"
    if not old_memories.exists():
        raise ValueError("No legacy .ai-verse-memory/memories store found")

    counts = {"migratable": 0, "copied": 0, "duplicate": 0, "unresolved": 0, "invalid": 0}
    report_rows = []
    for old_path in sorted(old_memories.rglob("*.md")):
        meta, body = parse_markdown(old_path)
        mem_id = meta.get("id")
        if not mem_id:
            counts["invalid"] += 1
            report_rows.append((str(old_path.relative_to(root)), "invalid", "missing id"))
            continue
        mapped = map_legacy_scope(meta.get("scope", "global"), root)
        if not mapped:
            counts["unresolved"] += 1
            report_rows.append((str(old_path.relative_to(root)), "unresolved", meta.get("scope", "")))
            continue
        counts["migratable"] += 1
        if locate_memory(mem_id, root, mode):
            counts["duplicate"] += 1
            report_rows.append((str(old_path.relative_to(root)), "duplicate", mapped))
            continue
        if apply:
            new_meta = dict(meta)
            old_scope = new_meta.get("scope", "global")
            new_meta["scope"] = mapped
            if old_scope != mapped:
                new_meta["legacy_scope"] = old_scope
            if not new_meta.get("source"):
                new_meta["source"] = f"legacy:{old_path.relative_to(root)}"
            created = new_meta.get("created_at") or now_iso()
            target = atomic_path(mem_id, created, mapped, root, mode)
            target.write_text(render_frontmatter(new_meta) + "\n\n" + body.strip() + "\n", encoding="utf-8")
            counts["copied"] += 1
            report_rows.append((str(old_path.relative_to(root)), "copied", relpath(target, root)))
        else:
            report_rows.append((str(old_path.relative_to(root)), "planned", mapped))

    if apply:
        rebuild(silent=True, root=root, mode=mode)

    report_dir = root / "operator" / "memory" / "migrations"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "legacy-ai-verse-memory-migration.md"
    lines = [
        "# Legacy AI-Verse Memory Migration",
        "",
        f"Generated: {now_iso()}",
        f"Applied: {'yes' if apply else 'no'}",
        "",
        "The legacy `.ai-verse-memory/` store is never deleted by this migration.",
        "Profiles and scenario summaries are not blindly promoted into AI-Verse OS canonical profile/context. Review and distill them separately if still useful.",
        "",
        "| Source | Result | Destination / note |",
        "|---|---|---|",
    ]
    lines.extend(f"| `{src}` | {result} | `{note}` |" for src, result, note in report_rows)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Legacy migration report: {relpath(report_path, root)}")
    print(json.dumps(counts, indent=2))
    return counts


def integration_checks(root: Path, mode: str) -> List[Tuple[str, bool, str, bool]]:
    checks: List[Tuple[str, bool, str, bool]] = []
    if mode != MODE_NATIVE:
        return checks

    manifest = root / "AI-VERSE.yaml"
    checks.append(("AI-Verse OS v2 manifest", manifest.exists(), str(manifest), True))
    checks.append(("Operator memory layer", (root / "operator" / "memory").exists(), "operator/memory", True))
    checks.append(("Workspace layer", (root / "workspaces").exists(), "workspaces/", True))
    checks.append(("Derived runtime index path", (root / "runtime" / "indexes" / "ai-verse-memory").exists(), "runtime/indexes/ai-verse-memory", True))

    claude_skill = root / ".claude" / "skills" / "ai-verse-memory" / "SKILL.md"
    codex_skill = root / ".agents" / "skills" / "ai-verse-memory" / "SKILL.md"
    checks.append(("Claude skill adapter", claude_skill.exists(), relpath(claude_skill, root), False))
    checks.append(("Codex skill adapter", codex_skill.exists(), relpath(codex_skill, root), False))
    if claude_skill.exists() and codex_skill.exists():
        same = claude_skill.read_bytes() == codex_skill.read_bytes()
        checks.append(("Runtime skill parity", same, "Claude and Codex SKILL.md match", False))

    registry = root / "skills" / "registry.yaml"
    registered = registry.exists() and "id: ai-verse-memory" in registry.read_text(encoding="utf-8", errors="replace")
    checks.append(("Capability registry", registered, "skills/registry.yaml", False))

    agents = root / "AGENTS.md"
    agents_has = agents.exists() and "AI-VERSE-MEMORY:START" in agents.read_text(encoding="utf-8", errors="replace")
    checks.append(("Canonical runtime instruction", agents_has, "AGENTS.md", False))

    claude = root / "CLAUDE.md"
    claude_has = claude.exists() and "AI-VERSE-MEMORY:START" in claude.read_text(encoding="utf-8", errors="replace")
    checks.append(("Claude adapter remains clean", not claude_has, "No duplicate standing memory block in CLAUDE.md", False))

    if (root / ".ai-verse-memory").exists():
        checks.append(("Legacy store detected", False, "Run migrate-legacy --apply after reviewing the dry run", False))
    return checks



def doctor(root: Optional[Path] = None, mode: Optional[str] = None) -> int:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = ensure_layout(root, mode)
    checks: List[Tuple[str, bool, str, bool]] = []
    checks.append(("Detected mode", True, mode, True))

    if mode == MODE_NATIVE:
        checks.append(("Canonical operator memory writable", os.access(p["operator_memory"], os.W_OK), relpath(p["operator_memory"], root), True))
        checks.append(("Derived index directory writable", os.access(p["db"].parent, os.W_OK), relpath(p["db"].parent, root), True))
    else:
        checks.append(("Memory home exists", p["home"].is_dir(), str(p["home"]), True))
        checks.append(("Canonical store writable", os.access(p["home"], os.W_OK), str(p["home"]), True))

    try:
        conn, fts = connect_db(root, mode)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks.append(("SQLite available", True, sqlite3.sqlite_version, True))
        checks.append(("FTS5 available", fts, "fallback search works without it" if not fts else "enabled", False))
    except Exception as exc:  # noqa: BLE001
        checks.append(("SQLite available", False, str(exc), True))
        fts = False

    try:
        count = rebuild(silent=True, root=root, mode=mode)
        checks.append(("Index rebuild", True, f"{count} indexed item(s)", True))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Index rebuild", False, str(exc), True))

    if mode == MODE_NATIVE:
        for path in _iter_atomic_candidates(root, mode):
            try:
                infer_scope_from_path(path, root, mode)
                meta, _ = parse_markdown(path)
                _validated_atomic_scope(path, root, mode, meta)
            except (ValueError, OSError) as exc:
                checks.append(("Workspace isolation", False, f"{path}: {exc}", True))
        checks.extend(integration_checks(root, mode))

    checks.append(("Migration completed", p["migration"].exists(), "optional on fresh repositories", False))

    print(f"AI-Verse Memory {VERSION}")
    failures = 0
    warnings = 0
    for label, ok, detail, required in checks:
        if ok:
            mark = "[x]"
        elif required:
            mark = "[!]"
            failures += 1
        else:
            mark = "[~]"
            warnings += 1
        print(f"{mark} {label}: {detail}")
    print(f"Doctor: {'PASS' if failures == 0 else 'FAIL'} ({warnings} warning(s))")
    return 1 if failures else 0


def status(root: Optional[Path] = None, mode: Optional[str] = None) -> None:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = ensure_layout(root, mode)
    if not p["db"].exists():
        rebuild(silent=True, root=root, mode=mode)
    conn, fts = connect_db(root, mode)
    total = conn.execute("SELECT count(*) FROM items WHERE kind='memory'").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM items WHERE kind='memory' AND status='active'").fetchone()[0]
    documents = conn.execute("SELECT count(*) FROM items WHERE kind!='memory'").fetchone()[0]
    by_scope = conn.execute(
        "SELECT scope, count(*) c FROM items WHERE kind='memory' AND status='active' GROUP BY scope ORDER BY c DESC, scope"
    ).fetchall()
    by_type = conn.execute(
        "SELECT type, count(*) c FROM items WHERE kind='memory' AND status='active' GROUP BY type ORDER BY c DESC, type"
    ).fetchall()
    conn.close()
    print(f"Mode: {mode}")
    print(f"Root: {root}")
    print(f"Atomic memories: {active} active / {total} total")
    print(f"Canonical context documents indexed: {documents}")
    print(f"FTS5: {'enabled' if fts else 'fallback lexical search'}")
    print(f"Migration: {'complete' if p['migration'].exists() else 'not marked complete'}")
    if by_scope:
        print("Active by scope: " + ", ".join(f"{r['scope']}={r['c']}" for r in by_scope))
    if by_type:
        print("Active by type: " + ", ".join(f"{r['type']}={r['c']}" for r in by_type))


def migration_complete(summary: str, root: Optional[Path] = None, mode: Optional[str] = None) -> None:
    root = root or repository_root()
    mode = mode or detect_mode(root)
    p = ensure_layout(root, mode)
    payload = {
        "completed_at": now_iso(),
        "version": VERSION,
        "mode": mode,
        "summary": summary.strip() or "Initial historical-memory migration completed.",
    }
    p["migration"].parent.mkdir(parents=True, exist_ok=True)
    p["migration"].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Migration marked complete: {relpath(p['migration'], root)}")


def print_recall(rows: Iterable[sqlite3.Row], query: str, scope_label: Optional[str]) -> None:
    rows = list(rows)
    print(f"# Memory recall\n\nQuery: {query}")
    if scope_label:
        print(f"Scope: {scope_label}")
    if not rows:
        print("\nNo relevant memory found.")
        return
    for row in rows:
        print(f"\n## {row['id']} [{row['kind']}/{row['type']}] ({row['scope']})")
        print(row["text"].strip())
        if row["why"]:
            print(f"Why: {row['why'].strip()}")
        details = []
        if row["source"]:
            details.append(f"source={row['source']}")
        if row["updated_at"]:
            details.append(f"updated={row['updated_at']}")
        details.append(f"path={row['path']}")
        print("; ".join(details))


def mode_report(root: Path) -> None:
    mode = detect_mode(root)
    p = paths(root, mode)
    print(f"Mode: {mode}")
    print(f"Root: {root}")
    if mode == MODE_NATIVE:
        print(f"Operator atomic memory: {relpath(p['operator_atomic'], root)}")
        print("Workspace atomic memory: workspaces/<id>/memory/atomic/")
        print(f"Derived index: {relpath(p['db'], root)}")
        print("Current context, profile, decisions, and workspace manifests are indexed in place and remain canonical where they live.")
    else:
        print(f"Memory home: {p['home']}")
        print(f"Derived index: {p['db']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-Verse Memory Engine")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--root", default=None, help="Repository root. Defaults to AI_VERSE_MEMORY_ROOT or auto-detection.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("mode", help="Show detected integration mode and canonical paths")
    sub.add_parser("init", help="Create the memory/index layout for the detected mode")
    sub.add_parser("rebuild", help="Rebuild SQLite from canonical Markdown and scoped OS sources")
    sub.add_parser("doctor", help="Validate storage, index, isolation, and native OS integration")
    sub.add_parser("status", help="Show memory statistics")

    remember_p = sub.add_parser("remember", help="Create one atomic historical memory")
    remember_p.add_argument("--type", required=True, choices=sorted(MEMORY_TYPES))
    remember_p.add_argument("--text", required=True)
    remember_p.add_argument("--scope", default=None)
    remember_p.add_argument("--workspace", default=None, help="AI-Verse OS v2 workspace id")
    remember_p.add_argument("--importance", type=int, default=3)
    remember_p.add_argument("--confidence", type=float, default=1.0)
    remember_p.add_argument("--source", default="")
    remember_p.add_argument("--why", default="")
    remember_p.add_argument("--tags", default="")
    remember_p.add_argument("--valid-from", default="")
    remember_p.add_argument("--force", action="store_true")

    recall_p = sub.add_parser("recall", help="Retrieve a small relevant set without crossing workspace boundaries")
    recall_p.add_argument("query")
    recall_p.add_argument("--scope", default=None)
    recall_p.add_argument("--workspace", default=None, help="AI-Verse OS v2 workspace id; also includes operator context")
    recall_p.add_argument("--all-workspaces", action="store_true", help="Explicitly allow cross-workspace recall")
    recall_p.add_argument("--limit", type=int, default=8)
    recall_p.add_argument("--include-history", action="store_true")

    show_p = sub.add_parser("show", help="Show one canonical atomic memory")
    show_p.add_argument("id")

    forget_p = sub.add_parser("forget", help="Permanently delete one canonical atomic memory")
    forget_p.add_argument("id")
    forget_p.add_argument("--yes", action="store_true", help="Confirm permanent deletion")

    supersede_p = sub.add_parser("supersede", help="Replace an old atomic memory while preserving history")
    supersede_p.add_argument("id")
    supersede_p.add_argument("--text", required=True)
    supersede_p.add_argument("--type", choices=sorted(MEMORY_TYPES), default=None)
    supersede_p.add_argument("--scope", default=None)
    supersede_p.add_argument("--workspace", default=None)
    supersede_p.add_argument("--importance", type=int, default=None)
    supersede_p.add_argument("--confidence", type=float, default=None)
    supersede_p.add_argument("--source", default="")
    supersede_p.add_argument("--why", default="")
    supersede_p.add_argument("--tags", default="")
    supersede_p.add_argument("--valid-from", default="")

    discover_p = sub.add_parser("discover", help="Find likely historical sources for one-time migration")
    discover_p.add_argument("source_root", nargs="?", default=".")
    discover_p.add_argument("--output", default=None)
    discover_p.add_argument("--max-files", type=int, default=250)

    legacy_p = sub.add_parser("migrate-legacy", help="Plan or apply migration from a v0.1 .ai-verse-memory store into AI-Verse OS v2")
    legacy_p.add_argument("--apply", action="store_true", help="Copy migratable atomic memories; old store remains untouched")

    migrate_p = sub.add_parser("migration-complete", help="Mark the initial migration pass complete")
    migrate_p.add_argument("--summary", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    root = repository_root(args.root)
    mode = detect_mode(root)
    try:
        if args.command == "mode":
            mode_report(root)
        elif args.command == "init":
            ensure_layout(root, mode)
            rebuild(silent=True, root=root, mode=mode)
            print(f"Initialized AI-Verse Memory {VERSION} in {mode} mode at {root}")
        elif args.command == "rebuild":
            rebuild(root=root, mode=mode)
        elif args.command == "doctor":
            return doctor(root, mode)
        elif args.command == "status":
            status(root, mode)
        elif args.command == "remember":
            scope = args.scope
            if args.workspace:
                if scope and scope not in {f"workspace:{args.workspace}", "global", "operator"}:
                    raise ValueError("Use either --workspace or a matching workspace:<id> --scope, not conflicting scopes")
                scope = f"workspace:{args.workspace}"
            mem_id, path, created = write_atomic(
                text=args.text,
                mem_type=args.type,
                scope=scope,
                importance=args.importance,
                confidence=args.confidence,
                source=args.source,
                why=args.why,
                tags=args.tags,
                valid_from=args.valid_from,
                force=args.force,
                root=root,
                mode=mode,
            )
            print(f"{'Remembered' if created else 'Duplicate active memory already exists'}: {mem_id}")
            print(relpath(path, root))
        elif args.command == "recall":
            rows = recall(
                args.query,
                scope=args.scope,
                limit=args.limit,
                include_history=args.include_history,
                root=root,
                mode=mode,
                workspace=args.workspace,
                all_workspaces=args.all_workspaces,
            )
            label = f"workspace:{args.workspace}" if args.workspace else args.scope
            print_recall(rows, args.query, label)
        elif args.command == "show":
            show_memory(args.id, root, mode)
        elif args.command == "forget":
            forget_memory(args.id, args.yes, root, mode)
        elif args.command == "supersede":
            supersede(args, root, mode)
        elif args.command == "discover":
            output = Path(args.output).resolve() if args.output else None
            discover(Path(args.source_root), output, max(1, min(5000, args.max_files)))
        elif args.command == "migrate-legacy":
            migrate_legacy(root, apply=args.apply)
        elif args.command == "migration-complete":
            migration_complete(args.summary, root, mode)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
