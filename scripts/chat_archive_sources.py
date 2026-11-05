"""Read-only AI-Verse OS private chat archives as typed Memory sources.

Slice 2 consumes synthetic instances of ai-verse.chat-archive/v1 only.
OS owns archive writes and authorization; Memory resolves current scoped
visibility on EACH read. No archive copies, hooks, provider reads or new
persistent indexes. Per-message checksums remain stable when JSONL is appended.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping

ARCHIVE_SCHEMA = "ai-verse.chat-archive/v1"
TYPE = "portable_chat_message"
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
WORKSPACE = re.compile(r"^[a-z0-9][a-z0-9-]{0,127}$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_ARCHIVES = 128
MAX_RECORDS_PER_ARCHIVE = 20000
MAX_ARCHIVE_BYTES = 8_000_000
MAX_TOTAL_MESSAGES = 40000
MAX_DIAGNOSTIC_COUNT = 128
# Fixed, count-only categories. Never report filenames, paths, IDs or content.
_DIAGNOSTIC_KINDS = ("invalid", "oversized", "raced", "unavailable")
FIELDS = {
    "kind", "schema", "archive_id", "scope", "origin", "session_id",
    "source_event_id", "source_byte_offset", "source_end_offset",
    "source_record_sha256", "block_index", "message_id", "sequence",
    "role", "text", "attachment_availability", "text_sha256",
    "archive_record_sha256", "timestamp", "revision", "branch",
}


class ArchiveSourceBlocked(ValueError):
    """Source was absent, unauthorized, malformed, or changed."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _decode(line: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ArchiveSourceBlocked("duplicate JSON member")
            result[key] = value
        return result
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               ArchiveSourceBlocked("nonfinite archive field")))
    except (UnicodeError, ValueError):
        raise ArchiveSourceBlocked("malformed UTF-8 JSONL record") from None
    if not isinstance(value, dict):
        raise ArchiveSourceBlocked("non-object archive record")
    return value


def _safe_components(root: Path, path: Path) -> None:
    """Check lexical containment and reject symlinks in every component."""
    if not root.is_absolute() or not path.is_absolute():
        raise ArchiveSourceBlocked("source paths must be absolute")
    try:
        rel = path.relative_to(root)
    except ValueError:
        raise ArchiveSourceBlocked("archive escapes selected OS root") from None
    if ".." in rel.parts:
        raise ArchiveSourceBlocked("archive traversal refused")
    current = root
    for part in ("", *rel.parts):
        if part:
            current = current / part
        try:
            info = current.lstat()
        except OSError:
            raise ArchiveSourceBlocked("archive path is missing") from None
        if stat.S_ISLNK(info.st_mode):
            raise ArchiveSourceBlocked("symlink archive component refused")
        if current != path and not stat.S_ISDIR(info.st_mode):
            raise ArchiveSourceBlocked("non-directory archive component")
        if current == path and not stat.S_ISREG(info.st_mode):
            raise ArchiveSourceBlocked("archive is not a regular file")
        if (os.name != "nt" and
                (current == path or "private-chat-history" in current.parts) and
                stat.S_IMODE(info.st_mode) & 0o077):
            raise ArchiveSourceBlocked("archive source permissions are not private")


def _stat_identity(info) -> tuple:
    # Windows creation/change-time metadata is not stable across a copied or
    # reopened file. Device/inode, length and modification time are checked
    # on every read; the per-message SHA-256 remains the content authority.
    common = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    return common if os.name == "nt" else common + (info.st_ctime_ns,)


def _read_bytes(root: Path, path: Path) -> bytes:
    _safe_components(root, path)
    before = path.lstat()
    if before.st_size > MAX_ARCHIVE_BYTES:
        raise ArchiveSourceBlocked("archive source exceeds read budget")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise ArchiveSourceBlocked("archive cannot be opened") from None
    try:
        initial = os.fstat(fd)
        if (not stat.S_ISREG(initial.st_mode)
                or _stat_identity(initial) != _stat_identity(before)):
            raise ArchiveSourceBlocked("archive file changed during open")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_ARCHIVE_BYTES + 1)
        after = os.fstat(fd)
        if (len(data) > MAX_ARCHIVE_BYTES or len(data) != initial.st_size
                or _stat_identity(after) != _stat_identity(initial)):
            raise ArchiveSourceBlocked("archive changed during read")
        try:
            final = path.lstat()
        except OSError:
            raise ArchiveSourceBlocked("archive was deleted during read") from None
        if _stat_identity(final) != _stat_identity(initial):
            raise ArchiveSourceBlocked("archive was replaced during read")
        _safe_components(root, path)
        return data
    finally:
        os.close(fd)


def _parse_archive(raw: bytes, scope: str, archive_id: str) -> list[dict]:
    # Partial tails are explicitly not committed; ignore them only after all
    # newline-terminated records have passed validation. Do not return a
    # provisional final JSON object even when it parses successfully.
    boundary = raw.rfind(b"\n") + 1
    complete = raw[:boundary]
    if not complete:
        raise ArchiveSourceBlocked("archive header uncommitted")
    rows = complete.split(b"\n")[:-1]
    if not rows or any(not row for row in rows):
        raise ArchiveSourceBlocked("archive contains empty committed record")
    header = _decode(rows[0])
    if (set(header) != {"kind", "schema", "archive_id", "chat_id",
                        "scope", "origin", "session_id"}
            or header.get("kind") != "header"
            or header.get("schema") != ARCHIVE_SCHEMA
            or header.get("archive_id") != archive_id
            or header.get("scope") != scope
            or any(not isinstance(header.get(k), str) or not ID.fullmatch(header[k])
                   for k in ("archive_id", "chat_id", "origin", "session_id"))):
        raise ArchiveSourceBlocked("archive header binding mismatch")
    if len(rows) - 1 > MAX_RECORDS_PER_ARCHIVE:
        raise ArchiveSourceBlocked("too many archive records")
    seen = set()
    by_offset = {}
    result = []
    for position, line in enumerate(rows[1:], 1):
        item = _decode(line)
        if set(item) != FIELDS:
            raise ArchiveSourceBlocked("archive record shape mismatch")
        if any(item.get(k) != header[k]
               for k in ("schema", "archive_id", "scope", "origin", "session_id")):
            raise ArchiveSourceBlocked("archive record scope/header mismatch")
        if item.get("kind") != "message":
            raise ArchiveSourceBlocked("unrecognized archive record type")
        if (type(item.get("sequence")) is not int or item["sequence"] != position
                or type(item.get("block_index")) is not int or item["block_index"] < 0
                or type(item.get("source_byte_offset")) is not int or item["source_byte_offset"] < 0
                or type(item.get("source_end_offset")) is not int
                or item["source_end_offset"] <= item["source_byte_offset"]):
            raise ArchiveSourceBlocked("archive source sequence or offsets invalid")
        if (not isinstance(item.get("text"), str)
                or item.get("role") not in {"user", "assistant"}
                or item.get("attachment_availability") not in
                    {"none", "not_embedded", "unknown"}):
            raise ArchiveSourceBlocked("archive includes unsupported non-visible record")
        for k in ("source_event_id", "message_id"):
            if not isinstance(item.get(k), str) or not ID.fullmatch(item[k]):
                raise ArchiveSourceBlocked("archive event/message ID invalid")
        for k in ("timestamp", "revision", "branch"):
            if item[k] is not None and (not isinstance(item[k], str) or len(item[k]) > 256):
                raise ArchiveSourceBlocked("archive metadata invalid")
        if (not isinstance(item.get("source_record_sha256"), str)
                or not SHA.fullmatch(item["source_record_sha256"])
                or item.get("text_sha256") != _sha(item["text"].encode("utf-8"))):
            raise ArchiveSourceBlocked("archive source/text integrity failed")
        without_hash = {k: v for k, v in item.items() if k != "archive_record_sha256"}
        if item.get("archive_record_sha256") != _sha(_json_bytes(without_hash)):
            raise ArchiveSourceBlocked("archive message integrity failed")
        event_id = item["source_event_id"]
        block_key = (item["source_byte_offset"], item["block_index"])
        if event_id in seen or block_key in seen:
            raise ArchiveSourceBlocked("duplicate immutable source event/block")
        seen.update((event_id, block_key))
        offset = item["source_byte_offset"]
        if offset in by_offset and by_offset[offset] != item["source_record_sha256"]:
            raise ArchiveSourceBlocked("source record changed at identical offset")
        by_offset[offset] = item["source_record_sha256"]
        if result and offset < result[-1]["source_byte_offset"]:
            raise ArchiveSourceBlocked("source offsets out of order")
        result.append(item)
    return result


def _source_scope(engine, root: Path, mode: str, scope: str,
                  *, requested_scope=None, workspace=None) -> None:
    if mode != engine.MODE_NATIVE:
        raise ArchiveSourceBlocked("portable chat archives require native OS v2")
    visible, _ = engine.allowed_scopes(
        root, mode, scope=requested_scope, workspace=workspace, all_workspaces=False)
    if visible is None or scope not in visible:
        raise ArchiveSourceBlocked("archive scope currently unauthorized")
    if scope.startswith("workspace:"):
        workspace_id = scope.partition(":")[2]
        if not WORKSPACE.fullmatch(workspace_id):
            raise ArchiveSourceBlocked("invalid scoped workspace")
        base = root / "workspaces" / workspace_id
        manifest = base / "WORKSPACE.yaml"
        _safe_components_manifest(root, manifest)
        try:
            content = manifest.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            raise ArchiveSourceBlocked("workspace manifest unavailable") from None
        fields = {}
        for line in content.splitlines():
            match = re.fullmatch(r"(id|status|schema_version):\s*['\"]?([a-z0-9][a-z0-9.-]*)['\"]?\s*", line)
            if match:
                if match.group(1) in fields:
                    raise ArchiveSourceBlocked("duplicate workspace manifest field")
                fields[match.group(1)] = match.group(2)
        if (fields.get("id") != workspace_id or fields.get("status") != "active"
                or not fields.get("schema_version", "").startswith("2.")):
            raise ArchiveSourceBlocked("workspace authorization no longer active")


def _safe_components_manifest(root: Path, manifest: Path) -> None:
    path = root
    for part in manifest.relative_to(root).parts:
        path = path / part
        try:
            info = path.lstat()
        except OSError:
            raise ArchiveSourceBlocked("workspace manifest is missing") from None
        if stat.S_ISLNK(info.st_mode):
            raise ArchiveSourceBlocked("symlink workspace binding")
        if path == manifest and not stat.S_ISREG(info.st_mode):
            raise ArchiveSourceBlocked("invalid workspace manifest")


def _scoped_folder(root: Path, scope: str) -> Path:
    suffix = ("operator",) if scope == "operator" else (
        "workspaces", scope.split(":", 1)[1])
    return root.joinpath("archives", "private-chat-history", "v1", *suffix)


def _folder_safe(root: Path, folder: Path) -> bool:
    path = root
    for part in folder.relative_to(root).parts:
        path = path / part
        if not path.exists() and not path.is_symlink():
            return False
        try:
            info = path.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ArchiveSourceBlocked("unsafe chat archive folder")
        if (os.name != "nt" and "private-chat-history" in path.parts
                and stat.S_IMODE(info.st_mode) & 0o077):
            raise ArchiveSourceBlocked("archive folder permissions are not private")
    return True


def _archive_failure_kind(exc: BaseException) -> str:
    """Only static category labels leave the isolated archive read."""
    if isinstance(exc, OSError):
        return "raced"
    description = str(exc)
    if description in {"archive source exceeds read budget",
                       "too many archive records"}:
        return "oversized"
    if description in {"archive file changed during open",
                       "archive changed during read",
                       "archive was deleted during read",
                       "archive was replaced during read"}:
        return "raced"
    if description in {"archive cannot be opened", "archive path is missing",
                       "archive is not a regular file",
                       "symlink archive component refused",
                       "archive source permissions are not private"}:
        return "unavailable"
    return "invalid"


def _note_archive_failure(diagnostics: dict | None, exc: BaseException) -> None:
    """Saturating counters only; never paths, exception messages or data."""
    if diagnostics is None:
        return
    kind = _archive_failure_kind(exc)
    for key in ("skipped", kind):
        count = diagnostics.get(key, 0)
        if count >= MAX_DIAGNOSTIC_COUNT:
            diagnostics["saturated"] = True
        else:
            diagnostics[key] = count + 1


def _archives(engine, root: Path, mode: str, *, scope=None, workspace=None,
              diagnostics: dict | None = None):
    if mode != engine.MODE_NATIVE:
        return []
    visible, _ = engine.allowed_scopes(
        root, mode, scope=scope, workspace=workspace, all_workspaces=False)
    if not visible:
        return []
    result = []
    for selected in visible:
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        folder = _scoped_folder(root, selected)
        if not _folder_safe(root, folder):
            continue
        try:
            # Do not eagerly list an unbounded directory. Retain the old
            # MAX_ARCHIVES limit even when most entries are lock files.
            files = list(itertools.islice(folder.iterdir(), MAX_ARCHIVES + 1))
        except OSError:
            raise ArchiveSourceBlocked("private archive folder cannot be listed") from None
        if len(files) > MAX_ARCHIVES:
            raise ArchiveSourceBlocked("archive source count exceeds budget")
        for path in sorted(files, key=lambda p: p.name):
            if not ID.fullmatch(path.stem) or path.suffix != ".jsonl":
                # Lock files and other extension-owned private files are not sources.
                continue
            try:
                records = _parse_archive(_read_bytes(root, path), selected, path.stem)
            except (ArchiveSourceBlocked, OSError) as exc:
                # Only ONE file may be skipped. Re-check the authoritative
                # scope and containing folder before suppressing a local error.
                # Scope denial or a directory race is never an archive-local
                # failure and must terminate the whole request.
                _source_scope(engine, root, mode, selected,
                              requested_scope=scope, workspace=workspace)
                if not _folder_safe(root, folder):
                    raise ArchiveSourceBlocked("archive scope folder disappeared")
                _note_archive_failure(diagnostics, exc)
                continue
            _source_scope(engine, root, mode, selected,
                          requested_scope=scope, workspace=workspace)
            if not _folder_safe(root, folder):
                raise ArchiveSourceBlocked("archive scope folder disappeared")
            if len(result) + len(records) > MAX_TOTAL_MESSAGES:
                raise ArchiveSourceBlocked("chat source scan budget exceeded")
            rel = path.relative_to(root).as_posix()
            for record in records:
                result.append({"scope": selected, "path": rel,
                               "archive_id": path.stem, **record})
        # Authorization changes during enumeration cannot release old results.
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        if not _folder_safe(root, folder):
            raise ArchiveSourceBlocked("archive scope folder disappeared")
    return result


def discover(engine, root: Path, mode: str, *, scope=None, workspace=None,
             query: str = "", limit: int = 20,
             diagnostics: dict | None = None) -> tuple[list[dict], int]:
    """Rebuildable, read-only discovery: no persistent chat index."""
    rows = _archives(engine, root, mode, scope=scope, workspace=workspace,
                     diagnostics=diagnostics)
    if not query:
        return rows[:max(0, limit)], len(rows)
    terms = [part.casefold() for part in re.findall(r"\w+", query, re.UNICODE)]
    if not terms:
        return [], 0
    matches = []
    for row in rows:
        text = row["text"].casefold()
        score = sum(term in text for term in terms)
        if score:
            matches.append((score, row))
    matches.sort(key=lambda item: (-item[0], item[1]["scope"],
                                    item[1]["path"], item[1]["sequence"]))
    return [row for _, row in matches[:max(0, limit)]], len(matches)


def _pointer(row: Mapping[str, Any]) -> dict:
    return {
        "path": row["path"], "archive_id": row["archive_id"],
        "source_event_id": row["source_event_id"], "message_id": row["message_id"],
        "archive_record_sha256": row["archive_record_sha256"],
        "source_record_sha256": row["source_record_sha256"],
        "source_byte_offset": row["source_byte_offset"],
        "block_index": row["block_index"],
    }


def as_item(row: Mapping[str, Any], depth: str) -> dict:
    text = row["text"]
    boundary = 480 if depth == "summary" else 2800
    clipped = len(text) > boundary
    identity = _sha((row["scope"] + "\0" + row["archive_id"] + "\0"
                     + row["source_event_id"]).encode("utf-8"))
    item = {
        "record_type": TYPE,
        "id": "chat-" + identity[:40],
        "kind": "visible_chat_text",
        "scope": row["scope"],
        "role": row["role"], "message_id": row["message_id"],
        "session_id": row["session_id"], "sequence": row["sequence"],
        "evidence": _pointer(row),
        "deeper_evidence_available": True,
    }
    item["excerpt" if depth == "summary" else "text"] = (
        text[:boundary] if clipped else text
    )
    if clipped:
        item["content_truncated"] = True
    return item


def exact(engine, root: Path, mode: str, ref: Mapping[str, Any], *,
          scope=None, workspace=None) -> tuple[str, dict | None, str]:
    """Resolve fresh authority and source bytes for each pointer dereference.

    Returns ('ok', item, reason) or ('stale'/'unavailable', None, reason).
    Never trust a caller-supplied path to select another archive.
    """
    evidence = ref.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("portable chat source requires an evidence pointer")
    selected = str(ref.get("scope") or "")
    _source_scope(engine, root, mode, selected,
                  requested_scope=scope, workspace=workspace)
    aid = evidence.get("archive_id")
    eid = evidence.get("source_event_id")
    message_id = evidence.get("message_id")
    if (not isinstance(aid, str) or not ID.fullmatch(aid)
            or not isinstance(eid, str) or not ID.fullmatch(eid)
            or not isinstance(message_id, str) or not ID.fullmatch(message_id)):
        raise ValueError("invalid portable chat source identity")
    stored = _scoped_folder(root, selected) / (aid + ".jsonl")
    if evidence.get("path") != stored.relative_to(root).as_posix():
        raise ValueError("portable chat source path disagrees with scoped identity")
    rid = "chat-" + _sha((selected + "\0" + aid + "\0" + eid).encode("utf-8"))[:40]
    if ref.get("id") != rid:
        raise ValueError("portable chat message identity does not match pointer")
    if not _folder_safe(root, stored.parent):
        return "unavailable", None, "archive_directory_missing"
    try:
        records = _parse_archive(_read_bytes(root, stored), selected, aid)
    except ArchiveSourceBlocked:
        return "unavailable", None, "archive_unavailable_or_invalid"
    match = next((row for row in records if row["source_event_id"] == eid), None)
    if match is None:
        return "unavailable", None, "message_deleted_from_archive"
    expected = (str(evidence.get("archive_record_sha256") or ""),
                str(evidence.get("source_record_sha256") or ""),
                evidence.get("source_byte_offset"),
                evidence.get("block_index"), message_id)
    current = (match["archive_record_sha256"], match["source_record_sha256"],
               match["source_byte_offset"], match["block_index"], match["message_id"])
    if expected != current:
        return "stale", None, "immutable_message_source_changed"
    # Do not return bytes after scope was revoked while the source was opened.
    _source_scope(engine, root, mode, selected,
                  requested_scope=scope, workspace=workspace)
    return "ok", {"scope": selected, "path": evidence["path"],
                  "message_id": message_id, "archive_id": aid,
                  "source_event_id": eid, "text": match["text"],
                  "role": match["role"], "sequence": match["sequence"],
                  "evidence": _pointer({"path": evidence["path"],
                                         "archive_id": aid, **match})}, ""
