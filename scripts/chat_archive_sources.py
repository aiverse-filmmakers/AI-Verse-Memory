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
# Bounded work when listing a private archive directory. A valid OS writer
# creates one .jsonl plus one .lock per chat, so the entry budget must not
# count lock files against MAX_ARCHIVES. An excessive junk/lockfile flood
# still fails closed rather than iterating an unbounded directory.
MAX_DIRECTORY_ENTRIES = MAX_ARCHIVES * 4
# Shared v1 capacity contract, enforced by OS ChatArchive on both writer
# entry points. Keep this aligned with OS MAX_ARCHIVE_MESSAGES/BYTES.
# The total-message budget remains a separate global request-wide bound.
MAX_RECORDS_PER_ARCHIVE = 40_000
MAX_ARCHIVE_BYTES = 64_000_000
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
                or not isinstance(item.get("role"), str)
                or item["role"] not in {"user", "assistant"}
                or not isinstance(item.get("attachment_availability"), str)
                or item["attachment_availability"] not in
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



PLACEMENT_SCHEMA = "ai-verse.chat-placement/v1"


def _placement_key(scope, archive_id):
    if not isinstance(scope, str) or not (scope == "operator" or
            (scope.startswith("workspace:") and WORKSPACE.fullmatch(scope.partition(":")[2]))):
        raise ArchiveSourceBlocked("invalid archive scope")
    return _sha((scope + "\0" + archive_id).encode("utf-8"))


def _placement(root, archive_id, scope):
    folder = root / "archives/private-chat-history/v1/placements"
    if not _folder_safe(root, folder):
        return None
    key = _placement_key(scope, archive_id)
    routes = folder / "routes"
    if _folder_safe(root, routes):
        route_path = routes / (key + ".json")
        if route_path.exists() or route_path.is_symlink():
            if route_path.lstat().st_size > 4096:
                raise ArchiveSourceBlocked("placement route exceeds budget")
            route = _decode(_read_bytes(root, route_path))
            if (set(route) != {"schema", "scope", "archive_id", "placement_id"}
                    or route["schema"] != "ai-verse.chat-route/v1" or route["scope"] != scope
                    or route["archive_id"] != archive_id or not isinstance(route["placement_id"], str)
                    or not SHA.fullmatch(route["placement_id"])):
                raise ArchiveSourceBlocked("invalid placement route")
            key = route["placement_id"]
    path = folder / (key + ".json")
    if not path.exists() and not path.is_symlink():
        return None
    if path.lstat().st_size > 64_000:
        raise ArchiveSourceBlocked("placement receipt exceeds budget")
    receipt = _decode(_read_bytes(root, path))
    fields = {"schema", "archive_id", "status", "from", "to", "previous_scopes",
              "source_sha256", "target_sha256", "fingerprint", "header", "home_scope", "placement_id"}
    def valid_scope(value):
        return isinstance(value, str) and (value == "operator" or (
            value.startswith("workspace:") and WORKSPACE.fullmatch(value.partition(":")[2])))
    if (set(receipt) != fields or receipt["schema"] != PLACEMENT_SCHEMA
            or receipt["archive_id"] != archive_id or receipt["status"] not in {"moving", "committed"}
            or not isinstance(receipt["previous_scopes"], list)
            or not all(valid_scope(v) for v in [receipt["home_scope"], receipt["from"], receipt["to"], *receipt["previous_scopes"]])
            or any(not isinstance(receipt[k], str) or not SHA.fullmatch(receipt[k])
                   for k in ("source_sha256", "target_sha256", "fingerprint"))
            or not isinstance(receipt["header"], dict)
            or receipt["placement_id"] != key or key != _placement_key(receipt["home_scope"], archive_id)
            or scope not in {receipt["home_scope"], receipt["from"], receipt["to"], *receipt["previous_scopes"]}):
        raise ArchiveSourceBlocked("invalid placement receipt")
    return receipt


def _placement_guard(root, scope, archive_id, data=None):
    receipt = _placement(root, archive_id, scope)
    if receipt and (receipt["status"] != "committed" or receipt["to"] != scope
                    or (data is not None and _sha(data) != receipt["target_sha256"])):
        raise ArchiveSourceBlocked("archive placement changed or is moving")
    return receipt

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


def revalidate(engine, root: Path, mode: str, *, scope=None, workspace=None,
               required_scopes=(), required_archives=()) -> None:
    """Final disclosure guard for every scope, including earlier scan results.

    A workspace+operator retrieval may scan its workspace first and operator
    last. The workspace may be paused while the operator scan runs. Never
    return previously gathered private text using the earlier authorization.
    Recheck all currently selected scopes AND any scopes already contributing
    results. This has no cached authorization and cannot mint provenance.
    """
    if mode != engine.MODE_NATIVE:
        return
    visible, _ = engine.allowed_scopes(
        root, mode, scope=scope, workspace=workspace, all_workspaces=False
    )
    expected = tuple(dict.fromkeys((*tuple(visible or ()), *tuple(required_scopes))))
    if not visible:
        raise ArchiveSourceBlocked("archive scopes currently unavailable")
    for selected in expected:
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        if (selected in required_scopes
                and not _folder_safe(root, _scoped_folder(root, selected))):
            raise ArchiveSourceBlocked("archive scope folder disappeared")
    for selected, archive_id in set(required_archives):
        _source_scope(engine, root, mode, selected, requested_scope=scope, workspace=workspace)
        _placement_guard(root, selected, archive_id)


def _archives(engine, root: Path, mode: str, *, scope=None, workspace=None,
              diagnostics: dict | None = None):
    if mode != engine.MODE_NATIVE:
        return []
    visible, _ = engine.allowed_scopes(
        root, mode, scope=scope, workspace=workspace, all_workspaces=False)
    if not visible:
        return []
    result = []
    scanned_folders = set()
    for selected in visible:
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        folder = _scoped_folder(root, selected)
        if not _folder_safe(root, folder):
            continue
        scanned_folders.add(selected)
        try:
            # The writer creates an archive .jsonl AND a sibling .lock file.
            # Bound total enumeration effort separately from actual archives,
            # so 128 legitimate chats with 128 locks do not exceed the count.
            entries = list(itertools.islice(
                folder.iterdir(), MAX_DIRECTORY_ENTRIES + 1
            ))
        except OSError:
            raise ArchiveSourceBlocked("private archive folder cannot be listed") from None
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            raise ArchiveSourceBlocked("archive directory scan budget exceeded")
        files = sorted(
            (path for path in entries
             if path.suffix == ".jsonl" and ID.fullmatch(path.stem)),
            key=lambda path: path.name,
        )
        if len(files) > MAX_ARCHIVES:
            raise ArchiveSourceBlocked("archive source count exceeds budget")
        for path in files:
            try:
                data = _read_bytes(root, path)
                receipt = _placement_guard(root, selected, path.stem, data)
                records = _parse_archive(data, selected, path.stem)
            except (ArchiveSourceBlocked, OSError, UnicodeError) as exc:
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
                               "_identity_scope": receipt["home_scope"] if receipt else selected,
                               "archive_id": path.stem, **record})
        # Authorization changes during enumeration cannot release old results.
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        if not _folder_safe(root, folder):
            raise ArchiveSourceBlocked("archive scope folder disappeared")
    # Critical: a scope checked at the end of its OWN scan can be revoked
    # while a later selected scope is scanned. Revalidate the entire set
    # after the last scan and BEFORE any previously collected rows escape.
    revalidate(engine, root, mode, scope=scope, workspace=workspace,
               required_scopes=scanned_folders,
               required_archives={(row["scope"], row["archive_id"]) for row in result})
    return result


def discover(engine, root: Path, mode: str, *, scope=None, workspace=None,
             query: str = "", limit: int = 20,
             diagnostics: dict | None = None) -> tuple[list[dict], int]:
    """Rebuildable, read-only discovery: no persistent chat index."""
    rows = _archives(engine, root, mode, scope=scope, workspace=workspace,
                     diagnostics=diagnostics)
    # Ranking and selecting may take time after the archive scan. Revalidate
    # all selected scopes once more immediately before each disclosure.
    def finish(items, count):
        revalidate(engine, root, mode, scope=scope, workspace=workspace,
                   required_scopes={row["scope"] for row in rows},
                   required_archives={(row["scope"], row["archive_id"]) for row in rows})
        return items, count

    if not query:
        return finish(rows[:max(0, limit)], len(rows))
    terms = engine.query_terms(query)
    if not terms:
        return finish([], 0)
    matches = []
    for row in rows:
        text = row["text"].casefold()
        score = sum(term in text for term in terms)
        if score:
            matches.append((score, row))
    matches.sort(key=lambda item: (-item[0], item[1]["scope"],
                                    item[1]["path"], item[1]["sequence"]))
    return finish([row for _, row in matches[:max(0, limit)]], len(matches))


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
    identity = _sha((row.get("_identity_scope", row["scope"]) + "\0" + row["archive_id"] + "\0"
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



def authorized_reference_scope(engine, root, mode, ref, *, scope=None, workspace=None):
    """Resolve current placement before the outer exact-source permission gate."""
    evidence = ref.get("evidence")
    aid = evidence.get("archive_id") if isinstance(evidence, Mapping) else None
    if not isinstance(aid, str) or not ID.fullmatch(aid):
        raise ValueError("invalid portable chat source identity")
    original = str(ref.get("scope") or "")
    receipt = _placement(root, aid, original)
    selected = original
    if receipt:
        if receipt["status"] != "committed" or original not in {*receipt["previous_scopes"], receipt["to"]}:
            raise ArchiveSourceBlocked("archive placement unavailable")
        selected = receipt["to"]
    # A denial never discloses the destination's name in the returned error.
    _source_scope(engine, root, mode, selected, requested_scope=scope, workspace=workspace)
    return selected

def exact(engine, root: Path, mode: str, ref: Mapping[str, Any], *,
          scope=None, workspace=None) -> tuple[str, dict | None, str]:
    """Resolve fresh authority and source bytes for each pointer dereference.

    Returns ('ok', item, reason) or ('stale'/'unavailable', None, reason).
    Never trust a caller-supplied path to select another archive.
    """
    evidence = ref.get("evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("portable chat source requires an evidence pointer")
    original_scope = str(ref.get("scope") or "")
    selected = original_scope
    aid = evidence.get("archive_id")
    eid = evidence.get("source_event_id")
    message_id = evidence.get("message_id")
    if (not isinstance(aid, str) or not ID.fullmatch(aid)
            or not isinstance(eid, str) or not ID.fullmatch(eid)
            or not isinstance(message_id, str) or not ID.fullmatch(message_id)):
        raise ValueError("invalid portable chat source identity")
    receipt = _placement(root, aid, original_scope)
    if receipt:
        if receipt["status"] != "committed" or original_scope not in {*receipt["previous_scopes"], receipt["to"]}:
            raise ArchiveSourceBlocked("archive placement unavailable")
        selected = receipt["to"]
    _source_scope(engine, root, mode, selected, requested_scope=scope, workspace=workspace)
    stored = _scoped_folder(root, selected) / (aid + ".jsonl")
    original_path = _scoped_folder(root, original_scope) / (aid + ".jsonl")
    if evidence.get("path") != original_path.relative_to(root).as_posix():
        raise ValueError("portable chat source path disagrees with scoped identity")
    rid = "chat-" + _sha(((receipt["home_scope"] if receipt else original_scope) + "\0" + aid + "\0" + eid).encode("utf-8"))[:40]
    legacy_id = "chat-" + _sha((original_scope + "\0" + aid + "\0" + eid).encode("utf-8"))[:40]
    if ref.get("id") not in {rid, legacy_id}:
        raise ValueError("portable chat message identity does not match pointer")
    if not _folder_safe(root, stored.parent):
        return "unavailable", None, "archive_directory_missing"
    try:
        data = _read_bytes(root, stored)
        _placement_guard(root, selected, aid, data)
        records = _parse_archive(data, selected, aid)
    except (ArchiveSourceBlocked, OSError, UnicodeError):
        # A file may disappear or change midway through a direct read.
        # Never substitute another archive or return cached visible text.
        # Revocation and unsafe scope-directory changes are NOT local errors.
        _source_scope(engine, root, mode, selected,
                      requested_scope=scope, workspace=workspace)
        if not _folder_safe(root, stored.parent):
            raise ArchiveSourceBlocked("archive scope folder disappeared")
        return "unavailable", None, "archive_unavailable_or_invalid"
    _source_scope(engine, root, mode, selected,
                  requested_scope=scope, workspace=workspace)
    if not _folder_safe(root, stored.parent):
        raise ArchiveSourceBlocked("archive scope folder disappeared")
    match = next((row for row in records if row["source_event_id"] == eid), None)
    if match is None:
        return "unavailable", None, "message_deleted_from_archive"
    expected = (str(evidence.get("archive_record_sha256") or ""),
                str(evidence.get("source_record_sha256") or ""),
                evidence.get("source_byte_offset"),
                evidence.get("block_index"), message_id)
    verified_hash = match["archive_record_sha256"]
    if selected != original_scope:
        original = {**match, "scope": original_scope}
        original.pop("archive_record_sha256")
        verified_hash = _sha(_json_bytes(original))
    current = (verified_hash, match["source_record_sha256"],
               match["source_byte_offset"], match["block_index"], match["message_id"])
    if expected != current:
        return "stale", None, "immutable_message_source_changed"
    # Do not return bytes after scope was revoked while the source was opened.
    _source_scope(engine, root, mode, selected,
                  requested_scope=scope, workspace=workspace)
    _placement_guard(root, selected, aid, data)
    current_path = stored.relative_to(root).as_posix()
    return "ok", {"scope": selected, "path": current_path,
                  "message_id": message_id, "archive_id": aid,
                  "source_event_id": eid, "text": match["text"],
                  "role": match["role"], "sequence": match["sequence"],
                  "evidence": _pointer({"path": current_path,
                                         "archive_id": aid, **match})}, ""
