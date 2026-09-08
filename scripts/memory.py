#!/usr/bin/env python3
"""AI-Verse Memory: dependency-free Markdown + SQLite memory helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

VERSION = "0.1.0"
MEMORY_TYPES = {
    "fact",
    "preference",
    "constraint",
    "decision",
    "project_state",
    "entity",
    "event",
    "experience",
    "workflow",
}
SKIP_DIRS = {
    ".git",
    ".ai-verse-memory",
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


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return value or "global"


def memory_home() -> Path:
    explicit = os.getenv("AI_VERSE_MEMORY_HOME")
    if explicit:
        return Path(explicit).expanduser().resolve()
    script_parent = Path(__file__).resolve().parent
    if script_parent.name == ".ai-verse-memory":
        return script_parent
    return (Path.cwd() / ".ai-verse-memory").resolve()


def paths() -> Dict[str, Path]:
    home = memory_home()
    return {
        "home": home,
        "memories": home / "memories",
        "scenarios": home / "scenarios",
        "evidence": home / "evidence",
        "state": home / "state",
        "profile": home / "profile.md",
        "db": home / "state" / "memory.db",
        "migration": home / "state" / "migration.json",
    }


def ensure_layout() -> Dict[str, Path]:
    p = paths()
    for key in ("home", "memories", "scenarios", "evidence", "state"):
        p[key].mkdir(parents=True, exist_ok=True)
    if not p["profile"].exists():
        p["profile"].write_text(
            "# Memory Profile\n\n"
            "> Stable, broadly useful context only. Keep volatile project details in atomic memories or scenarios.\n\n"
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


def memory_id(text: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"mem-{stamp}-{digest}"


def atomic_path(mem_id: str, created_at: str) -> Path:
    p = ensure_layout()
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.now(timezone.utc)
    folder = p["memories"] / f"{dt.year:04d}" / f"{dt.month:02d}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{mem_id}.md"


def write_atomic(
    text: str,
    mem_type: str,
    scope: str = "global",
    importance: int = 3,
    confidence: float = 1.0,
    source: str = "",
    why: str = "",
    tags: str = "",
    valid_from: str = "",
    supersedes: str = "",
    force: bool = False,
) -> Tuple[str, Path, bool]:
    ensure_layout()
    if mem_type not in MEMORY_TYPES:
        raise ValueError(f"Unsupported memory type: {mem_type}")
    text = text.strip()
    if not text:
        raise ValueError("Memory text cannot be empty")

    duplicate = find_exact_active(text, scope)
    if duplicate and not force:
        return duplicate[0], Path(duplicate[1]), False

    created = now_iso()
    mem_id = memory_id(text)
    path = atomic_path(mem_id, created)
    meta = {
        "id": mem_id,
        "type": mem_type,
        "scope": scope or "global",
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
    rebuild(silent=True)
    return mem_id, path, True


def connect_db() -> Tuple[sqlite3.Connection, bool]:
    p = ensure_layout()
    conn = sqlite3.connect(p["db"])
    conn.row_factory = sqlite3.Row
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
            why TEXT
        )
        """
    )
    fts = True
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS item_fts USING fts5(id UNINDEXED, text, why, tags, scope, type)"
        )
    except sqlite3.OperationalError:
        fts = False
    return conn, fts


def relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path.resolve())


def index_atomic(path: Path) -> Optional[Tuple]:
    meta, body = parse_markdown(path)
    if not meta.get("id"):
        return None
    text, why = extract_sections(body)
    return (
        meta.get("id", path.stem),
        "memory",
        relpath(path),
        meta.get("type", "fact"),
        meta.get("scope", "global"),
        meta.get("status", "active"),
        float(meta.get("importance", "3") or 3),
        float(meta.get("confidence", "1") or 1),
        meta.get("created_at", ""),
        meta.get("updated_at", ""),
        meta.get("source", ""),
        meta.get("tags", ""),
        text,
        why,
    )


def index_document(path: Path, kind: str) -> Tuple:
    meta, body = parse_markdown(path)
    title_match = re.search(r"(?m)^#\s+(.+)$", body)
    title = title_match.group(1).strip() if title_match else path.stem
    doc_id = meta.get("id") or f"{kind}:{slugify(title)}"
    return (
        doc_id,
        kind,
        relpath(path),
        meta.get("type", kind),
        meta.get("scope", "global"),
        meta.get("status", "active"),
        float(meta.get("importance", "5" if kind == "profile" else "4") or 4),
        float(meta.get("confidence", "1") or 1),
        meta.get("created_at", ""),
        meta.get("updated_at", ""),
        meta.get("source", ""),
        meta.get("tags", ""),
        body,
        "",
    )


def rebuild(silent: bool = False) -> int:
    p = ensure_layout()
    conn, fts = connect_db()
    conn.execute("DELETE FROM items")
    if fts:
        conn.execute("DELETE FROM item_fts")

    rows: List[Tuple] = []
    for file in sorted(p["memories"].rglob("*.md")):
        row = index_atomic(file)
        if row:
            rows.append(row)
    if p["profile"].exists():
        rows.append(index_document(p["profile"], "profile"))
    for file in sorted(p["scenarios"].glob("*.md")):
        rows.append(index_document(file, "scenario"))

    conn.executemany(
        """
        INSERT OR REPLACE INTO items
        (id, kind, path, type, scope, status, importance, confidence, created_at, updated_at, source, tags, text, why)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    if fts:
        conn.executemany(
            "INSERT INTO item_fts (id, text, why, tags, scope, type) VALUES (?, ?, ?, ?, ?, ?)",
            [(r[0], r[12], r[13], r[11], r[4], r[3]) for r in rows],
        )
    conn.commit()
    conn.close()
    if not silent:
        print(f"Rebuilt index: {len(rows)} item(s). FTS5={'yes' if fts else 'no; lexical fallback active'}")
    return len(rows)


def find_exact_active(text: str, scope: str) -> Optional[Tuple[str, str]]:
    p = ensure_layout()
    if not p["db"].exists():
        rebuild(silent=True)
    conn, _ = connect_db()
    row = conn.execute(
        "SELECT id, path FROM items WHERE kind='memory' AND status='active' AND lower(trim(text))=lower(trim(?)) AND scope=? LIMIT 1",
        (text, scope or "global"),
    ).fetchone()
    conn.close()
    if row:
        return row["id"], row["path"]
    return None


def tokenize(value: str) -> List[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]{2,}", value)]


def parse_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def custom_score(row: sqlite3.Row, query: str, scope: Optional[str]) -> float:
    q = set(tokenize(query))
    hay = " ".join(
        [row["text"] or "", row["why"] or "", row["tags"] or "", row["type"] or "", row["scope"] or ""]
    ).lower()
    words = set(tokenize(hay))
    overlap = len(q & words)
    score = overlap * 2.0
    if query.strip().lower() in hay:
        score += 4.0
    if scope:
        if row["scope"] == scope:
            score += 3.0
        elif row["scope"] == "global":
            score += 0.5
    score += min(5.0, float(row["importance"] or 3)) * 0.35
    score += max(0.0, min(1.0, float(row["confidence"] or 1))) * 0.4
    updated = parse_dt(row["updated_at"] or row["created_at"] or "")
    if updated:
        age_days = max(0, (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).days)
        score += max(0.0, 1.0 - min(age_days, 3650) / 3650.0)
    if row["kind"] == "scenario":
        score += 0.4
    if row["kind"] == "profile":
        score += 0.2
    return score


def recall(query: str, scope: Optional[str], limit: int, include_history: bool) -> List[sqlite3.Row]:
    p = ensure_layout()
    if not p["db"].exists():
        rebuild(silent=True)
    conn, fts = connect_db()
    status_clause = "" if include_history else "AND i.status='active'"
    scope_clause = ""
    params: List[str] = []
    if scope:
        scope_clause = "AND (i.scope=? OR i.scope='global')"
        params.append(scope)

    candidates: List[sqlite3.Row] = []
    terms = tokenize(query)
    if fts and terms:
        fts_query = " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms[:12])
        try:
            sql = f"""
                SELECT i.* FROM item_fts f
                JOIN items i ON i.id=f.id
                WHERE item_fts MATCH ? {status_clause} {scope_clause}
                LIMIT 100
            """
            candidates = conn.execute(sql, [fts_query] + params).fetchall()
        except sqlite3.OperationalError:
            candidates = []

    if not candidates:
        sql = f"SELECT i.* FROM items i WHERE 1=1 {status_clause} {scope_clause} LIMIT 500"
        candidates = conn.execute(sql, params).fetchall()

    ranked = sorted(candidates, key=lambda r: custom_score(r, query, scope), reverse=True)
    conn.close()
    return ranked[: max(1, min(50, limit))]


def update_meta(path: Path, changes: Dict[str, str]) -> None:
    meta, body = parse_markdown(path)
    if not meta:
        raise ValueError(f"Not an AI-Verse atomic memory: {path}")
    meta.update(changes)
    meta["updated_at"] = now_iso()
    path.write_text(render_frontmatter(meta) + "\n\n" + body.strip() + "\n", encoding="utf-8")


def locate_memory(mem_id: str) -> Optional[Path]:
    p = ensure_layout()
    matches = list(p["memories"].rglob(f"{mem_id}.md"))
    return matches[0] if matches else None


def supersede(args: argparse.Namespace) -> None:
    old_path = locate_memory(args.id)
    if not old_path:
        raise SystemExit(f"Memory not found: {args.id}")
    old_meta, _ = parse_markdown(old_path)
    new_type = args.type or old_meta.get("type", "fact")
    new_scope = args.scope or old_meta.get("scope", "global")
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
    )
    if created:
        update_meta(
            old_path,
            {
                "status": "superseded",
                "valid_to": now_iso(),
                "superseded_by": new_id,
            },
        )
        rebuild(silent=True)
    print(f"Superseded {args.id} -> {new_id}")
    print(relpath(new_path))


def discovery_score(path: Path) -> Tuple[int, str]:
    s = str(path).lower()
    clues = []
    score = 0
    for token, weight in [
        ("context", 6),
        ("memory", 6),
        ("decision", 6),
        ("preference", 5),
        ("profile", 5),
        ("project", 4),
        ("notes", 4),
        ("brainstorm", 3),
        ("archive", 3),
        ("transcript", 5),
        ("conversation", 5),
        ("agents.md", 5),
        ("claude.md", 5),
        ("readme", 2),
        ("reference", 3),
        ("skill", 2),
    ]:
        if token in s:
            score += weight
            clues.append(token)
    return score, ", ".join(clues[:5]) or "general text source"


def discover(root: Path, output: Optional[Path], max_files: int) -> List[Tuple[Path, int, str]]:
    root = root.resolve()
    found: List[Tuple[Path, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
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
        "This is a candidate list, not an instruction to import everything. The agent should inspect high-value sources and distill only durable memory.",
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


def doctor() -> int:
    p = ensure_layout()
    checks: List[Tuple[str, bool, str]] = []
    checks.append(("Memory home exists", p["home"].is_dir(), str(p["home"])))
    checks.append(("Canonical store writable", os.access(p["home"], os.W_OK), str(p["home"])))
    try:
        conn, fts = connect_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        checks.append(("SQLite available", True, sqlite3.sqlite_version))
        checks.append(("FTS5 available", fts, "fallback search works without it" if not fts else "enabled"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("SQLite available", False, str(exc)))
        fts = False
    try:
        count = rebuild(silent=True)
        checks.append(("Index rebuild", True, f"{count} indexed item(s)"))
    except Exception as exc:  # noqa: BLE001
        checks.append(("Index rebuild", False, str(exc)))
    checks.append(("Migration completed", p["migration"].exists(), "optional on fresh repositories"))

    print(f"AI-Verse Memory {VERSION}")
    failures = 0
    for label, ok, detail in checks:
        mark = "[x]" if ok else "[ ]"
        print(f"{mark} {label}: {detail}")
        if not ok and label not in {"FTS5 available", "Migration completed"}:
            failures += 1
    return 1 if failures else 0


def status() -> None:
    p = ensure_layout()
    if not p["db"].exists():
        rebuild(silent=True)
    conn, fts = connect_db()
    total = conn.execute("SELECT count(*) FROM items WHERE kind='memory'").fetchone()[0]
    active = conn.execute("SELECT count(*) FROM items WHERE kind='memory' AND status='active'").fetchone()[0]
    scenarios = conn.execute("SELECT count(*) FROM items WHERE kind='scenario'").fetchone()[0]
    by_type = conn.execute(
        "SELECT type, count(*) c FROM items WHERE kind='memory' AND status='active' GROUP BY type ORDER BY c DESC, type"
    ).fetchall()
    conn.close()
    print(f"Memory home: {p['home']}")
    print(f"Atomic memories: {active} active / {total} total")
    print(f"Scenarios: {scenarios}")
    print(f"FTS5: {'enabled' if fts else 'fallback lexical search'}")
    print(f"Migration: {'complete' if p['migration'].exists() else 'not marked complete'}")
    if by_type:
        print("Active by type: " + ", ".join(f"{r['type']}={r['c']}" for r in by_type))


def migration_complete(summary: str) -> None:
    p = ensure_layout()
    payload = {
        "completed_at": now_iso(),
        "version": VERSION,
        "summary": summary.strip() or "Initial historical-memory migration completed.",
    }
    p["migration"].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Migration marked complete: {p['migration']}")


def print_recall(rows: Iterable[sqlite3.Row], query: str, scope: Optional[str]) -> None:
    rows = list(rows)
    print(f"# Memory recall\n\nQuery: {query}")
    if scope:
        print(f"Scope: {scope}")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI-Verse Memory local helper")
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Create the local memory layout")
    sub.add_parser("rebuild", help="Rebuild SQLite from canonical Markdown")
    sub.add_parser("doctor", help="Validate the installation")
    sub.add_parser("status", help="Show memory statistics")

    remember_p = sub.add_parser("remember", help="Create one atomic memory")
    remember_p.add_argument("--type", required=True, choices=sorted(MEMORY_TYPES))
    remember_p.add_argument("--text", required=True)
    remember_p.add_argument("--scope", default="global")
    remember_p.add_argument("--importance", type=int, default=3)
    remember_p.add_argument("--confidence", type=float, default=1.0)
    remember_p.add_argument("--source", default="")
    remember_p.add_argument("--why", default="")
    remember_p.add_argument("--tags", default="")
    remember_p.add_argument("--valid-from", default="")
    remember_p.add_argument("--force", action="store_true")

    recall_p = sub.add_parser("recall", help="Retrieve a small relevant memory set")
    recall_p.add_argument("query")
    recall_p.add_argument("--scope", default=None)
    recall_p.add_argument("--limit", type=int, default=8)
    recall_p.add_argument("--include-history", action="store_true")

    supersede_p = sub.add_parser("supersede", help="Replace an old memory while preserving history")
    supersede_p.add_argument("id")
    supersede_p.add_argument("--text", required=True)
    supersede_p.add_argument("--type", choices=sorted(MEMORY_TYPES), default=None)
    supersede_p.add_argument("--scope", default=None)
    supersede_p.add_argument("--importance", type=int, default=None)
    supersede_p.add_argument("--confidence", type=float, default=None)
    supersede_p.add_argument("--source", default="")
    supersede_p.add_argument("--why", default="")
    supersede_p.add_argument("--tags", default="")
    supersede_p.add_argument("--valid-from", default="")

    discover_p = sub.add_parser("discover", help="Find likely historical context sources for migration")
    discover_p.add_argument("root", nargs="?", default=".")
    discover_p.add_argument("--output", default=None)
    discover_p.add_argument("--max-files", type=int, default=250)

    migrate_p = sub.add_parser("migration-complete", help="Mark the initial migration pass complete")
    migrate_p.add_argument("--summary", default="")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "init":
            p = ensure_layout()
            rebuild(silent=True)
            print(f"Initialized AI-Verse Memory at {p['home']}")
        elif args.command == "rebuild":
            rebuild()
        elif args.command == "doctor":
            return doctor()
        elif args.command == "status":
            status()
        elif args.command == "remember":
            mem_id, path, created = write_atomic(
                text=args.text,
                mem_type=args.type,
                scope=args.scope,
                importance=args.importance,
                confidence=args.confidence,
                source=args.source,
                why=args.why,
                tags=args.tags,
                valid_from=args.valid_from,
                force=args.force,
            )
            if created:
                print(f"Remembered: {mem_id}")
            else:
                print(f"Duplicate active memory already exists: {mem_id}")
            print(relpath(path))
        elif args.command == "recall":
            rows = recall(args.query, args.scope, args.limit, args.include_history)
            print_recall(rows, args.query, args.scope)
        elif args.command == "supersede":
            supersede(args)
        elif args.command == "discover":
            output = Path(args.output).resolve() if args.output else None
            discover(Path(args.root), output, max(1, min(5000, args.max_files)))
        elif args.command == "migration-complete":
            migration_complete(args.summary)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
