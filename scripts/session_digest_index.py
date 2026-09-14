"""Disposable SQLite projection and targeted recall for session digests.

Canonical digest Markdown remains the source of truth. This module owns only a
rebuildable projection inside the existing Memory database. It intentionally
does not add session digests to legacy atomic Memory recall.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_RECALL_LIMIT = 50
MAX_QUERY_TERMS = 64


def _file_version(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _connect(engine, root: Path, mode: str, *, reset: bool = False):
    root = Path(root).resolve()
    p = engine.ensure_layout(root, mode)
    if not p["db"].exists():
        # Preserve legacy semantics: if the shared derived DB is gone, rebuild
        # the established atomic/current-source projection before adding digest
        # tables. Creating only digest tables would make legacy recall see an
        # existing but empty DB.
        engine.rebuild(silent=True, root=root, mode=mode)

    conn = sqlite3.connect(p["db"])
    conn.row_factory = sqlite3.Row
    if reset:
        try:
            conn.execute("DROP TABLE IF EXISTS session_digest_fts")
        except sqlite3.OperationalError:
            pass
        conn.execute("DROP TABLE IF EXISTS session_digest_items")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS session_digest_items (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            scope TEXT NOT NULL,
            session_id TEXT NOT NULL,
            run_id TEXT,
            topic TEXT NOT NULL,
            summary TEXT NOT NULL,
            significant_outcomes TEXT NOT NULL,
            unresolved_items TEXT NOT NULL,
            source_refs TEXT NOT NULL,
            source_coverage TEXT NOT NULL,
            provenance TEXT NOT NULL,
            source_fingerprint TEXT,
            source_version TEXT,
            digest_fingerprint TEXT NOT NULL,
            created_at TEXT,
            completed_at TEXT,
            canonical_version TEXT NOT NULL,
            indexed_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_digest_scope_time "
        "ON session_digest_items(scope, completed_at DESC, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_digest_session "
        "ON session_digest_items(session_id, run_id)"
    )

    fts = True
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS session_digest_fts "
            "USING fts5(id UNINDEXED, topic, summary, outcomes, unresolved, "
            "session_id, run_id, scope)"
        )
    except sqlite3.OperationalError:
        fts = False
    conn.commit()
    return conn, fts


def _safe_scope_records(engine, digest_module, root: Path, mode: str, scope: str):
    normalized = engine.normalize_scope(scope, root, mode)
    base = digest_module._digest_root(engine, root, mode, normalized, create=False)
    if not base.exists():
        return
    if base.is_symlink() or not base.is_dir():
        return

    try:
        base_real = base.resolve(strict=True)
    except OSError:
        return

    for shard in sorted(base.iterdir()):
        if shard.is_symlink() or not shard.is_dir():
            continue
        try:
            shard.resolve(strict=True).relative_to(base_real)
        except (ValueError, OSError):
            continue
        for path in sorted(shard.glob("sdg-*.md")):
            if path.is_symlink() or not path.is_file():
                continue
            digest_id = path.stem
            if not digest_module._DIGEST_ID_RE.fullmatch(digest_id):
                continue
            try:
                record = digest_module._read_path(
                    engine, path, root, mode, normalized, digest_id
                )
                version = _file_version(path)
            except (FileNotFoundError, RuntimeError, ValueError, OSError):
                continue
            yield record, path, version


def _standalone_records(engine, digest_module, root: Path, mode: str):
    home = engine.public_beta_standalone_home(root)
    top = home / "session-digests"
    if not top.exists():
        return
    if top.is_symlink() or not top.is_dir():
        return

    try:
        top_real = top.resolve(strict=True)
    except OSError:
        return

    for bucket in sorted(top.iterdir()):
        if bucket.is_symlink() or not bucket.is_dir():
            continue
        try:
            bucket.resolve(strict=True).relative_to(top_real)
        except (ValueError, OSError):
            continue
        for shard in sorted(bucket.iterdir()):
            if shard.is_symlink() or not shard.is_dir():
                continue
            try:
                shard.resolve(strict=True).relative_to(bucket.resolve(strict=True))
            except (ValueError, OSError):
                continue
            for path in sorted(shard.glob("sdg-*.md")):
                if path.is_symlink() or not path.is_file():
                    continue
                digest_id = path.stem
                if not digest_module._DIGEST_ID_RE.fullmatch(digest_id):
                    continue
                try:
                    meta, _ = engine.parse_markdown(path)
                    raw_scope = meta.get("scope") or "global"
                    scope = engine.normalize_scope(raw_scope, root, mode)
                    expected = digest_module._digest_root(
                        engine, root, mode, scope, create=False
                    )
                    if not expected.exists():
                        continue
                    if bucket.resolve(strict=True) != expected.resolve(strict=True):
                        continue
                    record = digest_module._read_path(
                        engine, path, root, mode, scope, digest_id
                    )
                    version = _file_version(path)
                except (FileNotFoundError, RuntimeError, ValueError, OSError):
                    continue
                yield record, path, version


def _canonical_records(engine, digest_module, root: Path, mode: str):
    root = Path(root).resolve()
    if mode == engine.MODE_NATIVE:
        scopes = ["operator"] + [
            f"workspace:{wid}" for wid in engine.workspace_ids(root)
        ]
        for scope in scopes:
            yield from _safe_scope_records(
                engine, digest_module, root, mode, scope
            )
        return

    yield from _standalone_records(engine, digest_module, root, mode)


def _row_for(engine, record: Dict[str, Any], path: Path, version: str, root: Path, mode: str):
    stored_path = (
        engine.relpath(path, root) if mode == engine.MODE_NATIVE else str(path)
    )
    return (
        record["id"],
        stored_path,
        record["scope"],
        record["session_id"],
        record.get("run_id") or "",
        record["topic"],
        record["summary"],
        json.dumps(record["significant_outcomes"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(record["unresolved_items"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(record["source_refs"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(record["source_coverage"], ensure_ascii=False, separators=(",", ":")),
        json.dumps(record["provenance"], ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        record.get("source_fingerprint") or "",
        record.get("source_version") or "",
        record.get("digest_fingerprint") or "",
        record.get("created_at") or "",
        record.get("completed_at") or "",
        version,
        engine.now_iso(),
    )


def _fts_row(row: Tuple[Any, ...]):
    outcomes = " ".join(json.loads(row[7] or "[]"))
    unresolved = " ".join(json.loads(row[8] or "[]"))
    return (
        row[0],
        row[5],
        row[6],
        outcomes,
        unresolved,
        row[3],
        row[4],
        row[2],
    )


def _delete_ids(conn: sqlite3.Connection, fts: bool, ids: Sequence[str]) -> int:
    unique = sorted({str(item) for item in ids if item})
    if not unique:
        return 0
    conn.executemany(
        "DELETE FROM session_digest_items WHERE id=?",
        [(item,) for item in unique],
    )
    if fts:
        conn.executemany(
            "DELETE FROM session_digest_fts WHERE id=?",
            [(item,) for item in unique],
        )
    return len(unique)


def _insert_rows(conn: sqlite3.Connection, fts: bool, rows: Sequence[Tuple[Any, ...]]):
    if not rows:
        return
    conn.executemany(
        """
        INSERT OR REPLACE INTO session_digest_items
        (id, path, scope, session_id, run_id, topic, summary,
         significant_outcomes, unresolved_items, source_refs, source_coverage,
         provenance, source_fingerprint, source_version, digest_fingerprint,
         created_at, completed_at, canonical_version, indexed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    if fts:
        conn.executemany(
            "INSERT INTO session_digest_fts "
            "(id, topic, summary, outcomes, unresolved, session_id, run_id, scope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [_fts_row(row) for row in rows],
        )


def _sync(engine, digest_module, conn: sqlite3.Connection, fts: bool, root: Path, mode: str) -> int:
    current: Dict[str, Tuple[Any, ...]] = {}
    for record, path, version in _canonical_records(
        engine, digest_module, root, mode
    ):
        row = _row_for(engine, record, path, version, root, mode)
        current[str(row[0])] = row

    existing = conn.execute(
        "SELECT id, path, scope, digest_fingerprint, canonical_version "
        "FROM session_digest_items"
    ).fetchall()
    existing_by_id = {str(row["id"]): row for row in existing}

    remove_ids: List[str] = []
    insert_rows: List[Tuple[Any, ...]] = []

    for digest_id, previous in existing_by_id.items():
        if digest_id not in current:
            remove_ids.append(digest_id)

    for digest_id, row in current.items():
        previous = existing_by_id.get(digest_id)
        unchanged = bool(
            previous
            and str(previous["path"] or "") == str(row[1])
            and str(previous["scope"] or "") == str(row[2])
            and str(previous["digest_fingerprint"] or "") == str(row[14])
            and str(previous["canonical_version"] or "") == str(row[17])
        )
        if unchanged:
            continue
        remove_ids.append(digest_id)
        insert_rows.append(row)

    removed = _delete_ids(conn, fts, remove_ids)
    _insert_rows(conn, fts, insert_rows)
    if removed or insert_rows:
        conn.commit()
    return removed + len(insert_rows)


def _decode_row(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "type": "session_digest",
        "path": row["path"],
        "scope": row["scope"],
        "session_id": row["session_id"],
        "run_id": row["run_id"] or "",
        "topic": row["topic"],
        "summary": row["summary"],
        "significant_outcomes": json.loads(row["significant_outcomes"] or "[]"),
        "unresolved_items": json.loads(row["unresolved_items"] or "[]"),
        "source_refs": json.loads(row["source_refs"] or "[]"),
        "source_coverage": json.loads(row["source_coverage"] or "[]"),
        "provenance": json.loads(row["provenance"] or "{}"),
        "source_fingerprint": row["source_fingerprint"] or "",
        "source_version": row["source_version"] or "",
        "digest_fingerprint": row["digest_fingerprint"] or "",
        "created_at": row["created_at"] or "",
        "completed_at": row["completed_at"] or "",
        "canonical_version": row["canonical_version"],
        "indexed_at": row["indexed_at"],
    }


def _unique_terms(engine, query: str) -> List[str]:
    seen = set()
    result = []
    for token in engine.tokenize(query):
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
        if len(result) >= MAX_QUERY_TERMS:
            break
    return result


def _haystack(row: sqlite3.Row) -> str:
    return " ".join(
        [
            str(row["topic"] or ""),
            str(row["summary"] or ""),
            str(row["significant_outcomes"] or ""),
            str(row["unresolved_items"] or ""),
            str(row["session_id"] or ""),
            str(row["run_id"] or ""),
        ]
    ).lower()


def _matches(engine, row: sqlite3.Row, query: str) -> bool:
    query = query.strip()
    if not query:
        return True
    terms = set(token.casefold() for token in _unique_terms(engine, query))
    if not terms:
        return False
    words = set(token.casefold() for token in engine.tokenize(_haystack(row)))
    return bool(terms & words) or query.casefold() in _haystack(row)


def _parse_time(engine, raw: str):
    if not raw:
        return None
    try:
        parsed = engine.parse_dt(raw)
        if parsed is not None:
            return parsed.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _score(engine, row: sqlite3.Row, query: str, primary_scope: Optional[str]) -> float:
    query = query.strip()
    terms = set(token.casefold() for token in _unique_terms(engine, query))
    topic_words = set(token.casefold() for token in engine.tokenize(str(row["topic"] or "")))
    summary_words = set(token.casefold() for token in engine.tokenize(str(row["summary"] or "")))
    other_words = set(
        token.casefold()
        for token in engine.tokenize(
            " ".join(
                [
                    str(row["significant_outcomes"] or ""),
                    str(row["unresolved_items"] or ""),
                ]
            )
        )
    )

    score = 0.0
    if terms:
        score += len(terms & topic_words) * 3.0
        score += len(terms & summary_words) * 2.0
        score += len(terms & other_words) * 1.25
        if query.casefold() in _haystack(row):
            score += 4.0
        if query.casefold() == str(row["session_id"] or "").casefold():
            score += 8.0
        if query.casefold() == str(row["run_id"] or "").casefold():
            score += 8.0

    if primary_scope:
        if row["scope"] == primary_scope:
            score += 3.0
        elif row["scope"] in {"operator", "global"}:
            score += 0.6

    completed = _parse_time(engine, row["completed_at"] or row["created_at"] or "")
    if completed:
        age_days = max(0, (datetime.now(timezone.utc) - completed).days)
        score += max(0.0, 1.0 - min(age_days, 3650) / 3650.0)
    return score


def _validate_candidate(engine, digest_module, row: sqlite3.Row, root: Path, mode: str):
    try:
        canonical = engine.read_session_digest(
            str(row["id"]),
            scope=str(row["scope"]),
            root=root,
            mode=mode,
        )
    except (FileNotFoundError, RuntimeError, ValueError, OSError):
        return None
    if canonical.get("digest_fingerprint") != row["digest_fingerprint"]:
        return None
    path = Path(row["path"])
    if mode == engine.MODE_NATIVE:
        if path.is_absolute():
            return None
        path = root / path
    try:
        if _file_version(path) != row["canonical_version"]:
            return None
    except OSError:
        return None
    return canonical


def _install_rebuild(engine, digest_module):
    def rebuild_session_digest_index(
        *,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> int:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        conn, fts = _connect(engine, root, mode, reset=True)
        try:
            _sync(engine, digest_module, conn, fts, root, mode)
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM session_digest_items"
            ).fetchone()
            return int(row["count"] if row else 0)
        finally:
            conn.close()

    return rebuild_session_digest_index


def _install_refresh(engine, digest_module):
    def refresh_session_digest_index(
        *,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> int:
        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        conn, fts = _connect(engine, root, mode)
        try:
            return _sync(engine, digest_module, conn, fts, root, mode)
        finally:
            conn.close()

    return refresh_session_digest_index


def _install_recall(engine, digest_module):
    def recall_session_digests(
        query: str = "",
        *,
        scope: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 8,
        all_workspaces: bool = False,
        root: Optional[Path] = None,
        mode: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RECALL_LIMIT:
            raise ValueError(
                f"limit must be an integer between 1 and {MAX_RECALL_LIMIT}"
            )

        root = Path(root or engine.repository_root()).resolve()
        mode = mode or engine.detect_mode(root)
        scopes, primary_scope = engine.allowed_scopes(
            root, mode, scope, workspace, all_workspaces
        )
        conn, fts = _connect(engine, root, mode)
        try:
            _sync(engine, digest_module, conn, fts, root, mode)

            scope_clause = ""
            params: List[Any] = []
            if scopes:
                placeholders = ",".join("?" for _ in scopes)
                scope_clause = f"AND d.scope IN ({placeholders})"
                params.extend(scopes)

            terms = _unique_terms(engine, query)
            candidates: List[sqlite3.Row] = []
            used_fts = False
            if fts and terms:
                fts_query = " OR ".join(
                    f'"{term.replace(chr(34), "")}"' for term in terms
                )
                try:
                    candidates = conn.execute(
                        f"""
                        SELECT d.*
                        FROM session_digest_fts f
                        JOIN session_digest_items d ON d.id=f.id
                        WHERE session_digest_fts MATCH ? {scope_clause}
                        LIMIT 300
                        """,
                        [fts_query] + params,
                    ).fetchall()
                    used_fts = True
                except sqlite3.OperationalError:
                    used_fts = False

            if not used_fts:
                candidates = conn.execute(
                    f"""
                    SELECT d.*
                    FROM session_digest_items d
                    WHERE 1=1 {scope_clause}
                    ORDER BY d.completed_at DESC, d.created_at DESC
                    LIMIT 1000
                    """,
                    params,
                ).fetchall()

            candidates = [
                row for row in candidates if _matches(engine, row, query)
            ]
            ranked = sorted(
                candidates,
                key=lambda row: (
                    _score(engine, row, query, primary_scope),
                    str(row["completed_at"] or row["created_at"] or ""),
                    str(row["id"]),
                ),
                reverse=True,
            )

            results: List[Dict[str, Any]] = []
            invalid_ids: List[str] = []
            for row in ranked:
                canonical = _validate_candidate(
                    engine, digest_module, row, root, mode
                )
                if canonical is None:
                    invalid_ids.append(str(row["id"]))
                    continue
                results.append(_decode_row(row))
                if len(results) >= limit:
                    break

            if invalid_ids:
                _delete_ids(conn, fts, invalid_ids)
                conn.commit()
            return results
        finally:
            conn.close()

    return recall_session_digests


def apply(engine, digest_module) -> None:
    """Attach the rebuildable digest projection without touching legacy recall."""

    engine.rebuild_session_digest_index = _install_rebuild(engine, digest_module)
    engine.refresh_session_digest_index = _install_refresh(engine, digest_module)
    engine.recall_session_digests = _install_recall(engine, digest_module)
