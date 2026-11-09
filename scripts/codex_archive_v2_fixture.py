"""Isolated Memory decoder for the nonadmitted Codex received-wire v2 fixture.

This is NOT connected to progressive_recall, Memory's installed package,
live local files, the v1 archive reader or any real host. Only an
in-memory bytes argument is accepted. An archive header claiming scope,
consent or provider origin is untrusted. No host origin/source
authorization, v1 source byte offsets, or complete chat coverage is
established, and all production read admission remains hard-blocked.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Mapping

SCHEMA = "ai-verse.chat-archive-codex-received/v2"
MAX_FRAMES = 128
MAX_FRAME_BYTES = 65_536
MAX_ROW_BYTES = 100_000
MAX_ARCHIVE_BYTES = 6_000_000
MAX_TOTAL_WIRE_BYTES = 2_000_000
MAX_TEXT_BYTES = 200_000
IDENTITY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SCOPE = re.compile(r"^(operator|workspace:[a-z0-9][a-z0-9-]{0,127})$")
SHA = re.compile(r"^[0-9a-f]{64}$")
NON_CHAT = frozenset((
    "plan", "reasoning", "commandExecution", "fileChange", "mcpToolCall",
    "dynamicToolCall", "collabToolCall", "webSearch", "imageView",
    "enteredReviewMode", "exitedReviewMode", "contextCompaction",
    "functionCallOutput",
))
DELTA = frozenset((
    "item/agentMessage/delta", "item/plan/delta",
    "item/reasoning/summaryTextDelta", "item/reasoning/textDelta",
    "item/commandExecution/outputDelta",
))
HEADER = frozenset((
    "kind", "schema", "archive_id", "scope", "origin", "thread_id",
    "turn_id", "mode", "source_class", "host_origin_authenticated",
    "scope_authenticated", "consent_verified", "complete_ui_coverage",
    "write_admitted",
))
FRAME = frozenset((
    "kind", "schema", "index", "wire_b64", "wire_byte_length",
    "wire_sha256", "chain_sha256",
))
SEAL = frozenset((
    "kind", "schema", "frame_count", "total_received_bytes",
    "received_stream_sha256", "last_chain_sha256", "messages",
    "original_source_offsets", "host_origin_authenticated",
    "scope_authenticated", "consent_verified",
    "complete_ui_coverage", "write_admitted",
))


class V2MemoryBlocked(ValueError):
    """Error never includes path, source text, user identity or JSON wire."""


@dataclass(frozen=True)
class FixtureMessage:
    role: str
    item_id: str
    text_sha256: str
    frame_index: int
    text: str = field(repr=False)


@dataclass(frozen=True)
class FixtureRead:
    scope: str
    archive_id: str
    thread_id: str
    turn_id: str
    messages: tuple[FixtureMessage, FixtureMessage] = field(repr=False)
    schema: str = SCHEMA
    verdict: str = "untrusted_synthetic_v2_fixture_not_discoverable"
    live_recall_admitted: bool = False
    host_origin_authenticated: bool = False
    scope_authenticated: bool = False
    consent_verified: bool = False
    complete_ui_coverage: bool = False


def _deny():
    raise V2MemoryBlocked("untrusted v2 Memory fixture refused")


def _id(value, *, scope=False):
    if not isinstance(value, str) or not (SCOPE if scope else IDENTITY).fullmatch(value):
        _deny()
    return value


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(parts):
    result = {}
    for key, value in parts:
        if key in result:
            _deny()
        result[key] = value
    return result


def _constant(_value):
    _deny()


def _json(line: bytes, *, source=False) -> dict:
    if (type(line) is not bytes or not 3 <= len(line)
            or not line.endswith(b"\n")
            or b"\n" in line[:-1] or b"\r" in line
            or len(line) > (MAX_FRAME_BYTES if source else MAX_ROW_BYTES)):
        _deny()
    try:
        result = json.loads(
            line[:-1].decode("utf-8", "strict"),
            object_pairs_hook=_pairs, parse_constant=_constant,
        )
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        _deny()
    if not isinstance(result, dict):
        _deny()
    return result


def _canonical(row: Mapping) -> bytes:
    try:
        return (json.dumps(
            row, ensure_ascii=False, sort_keys=True, allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8", "strict") + b"\n")
    except (TypeError, ValueError, UnicodeError, RecursionError, OverflowError):
        _deny()


def _require_false(row: Mapping):
    for key in ("host_origin_authenticated", "scope_authenticated",
                "consent_verified", "complete_ui_coverage", "write_admitted"):
        if row.get(key) is not False:
            _deny()


def _parse_text(value) -> tuple[str, str]:
    if not isinstance(value, str):
        _deny()
    try:
        encoded = value.encode("utf-8", "strict")
    except UnicodeError:
        _deny()
    if not 1 <= len(encoded) <= MAX_TEXT_BYTES:
        _deny()
    return value, _sha(encoded)


def parse_synthetic_v2_bytes(
    raw: bytes, *, expected_scope: str, expected_archive_id: str,
) -> FixtureRead:
    """Independently validate exact sealed fixture bytes, never a file path.

    Caller-supplied expected scope is a match guard, NOT OS authorization.
    No real Memory catalog, detail or exact-source route invokes this.
    """
    if (type(raw) is not bytes or not 1 <= len(raw) <= MAX_ARCHIVE_BYTES
            or b"\r" in raw or not raw.endswith(b"\n")):
        _deny()
    _id(expected_scope, scope=True)
    _id(expected_archive_id)
    rows = raw.splitlines(keepends=True)
    if not 6 <= len(rows) <= MAX_FRAMES + 2:
        _deny()
    header = _json(rows[0])
    seal = _json(rows[-1])
    if (set(header) != HEADER or set(seal) != SEAL
            or _canonical(header) != rows[0]
            or _canonical(seal) != rows[-1]
            or header.get("kind") != "header"
            or seal.get("kind") != "seal"
            or header.get("schema") != SCHEMA or seal.get("schema") != SCHEMA
            or header.get("mode") != "synthetic_fixture_only"
            or header.get("source_class") != "exact_received_jsonl_unverified"
            or header.get("origin") != "codex-app-server-received"
            or _id(header.get("archive_id")) != expected_archive_id
            or _id(header.get("scope"), scope=True) != expected_scope):
        _deny()
    _require_false(header)
    _require_false(seal)
    thread = _id(header.get("thread_id"))
    turn = _id(header.get("turn_id"))
    if (seal.get("original_source_offsets") is not None
            or type(seal.get("frame_count")) is not int
            or seal["frame_count"] != len(rows) - 2
            or not isinstance(seal.get("messages"), list)
            or type(seal.get("total_received_bytes")) is not int):
        _deny()
    chain = hashlib.sha256(rows[0]).digest()
    stream = hashlib.sha256()
    wire_total = 0
    finished = {}
    started = {}
    messages = []
    phase = "before_start"
    for index, line in enumerate(rows[1:-1]):
        record = _json(line)
        if (set(record) != FRAME or _canonical(record) != line
                or record.get("kind") != "frame"
                or record.get("schema") != SCHEMA
                or type(record.get("index")) is not int
                or record["index"] != index
                or type(record.get("wire_byte_length")) is not int
                or not isinstance(record.get("wire_b64"), str)
                or not isinstance(record.get("wire_sha256"), str)
                or not SHA.fullmatch(record["wire_sha256"])):
            _deny()
        try:
            wire = base64.b64decode(record["wire_b64"], validate=True)
            if base64.b64encode(wire).decode("ascii") != record["wire_b64"]:
                _deny()
        except (ValueError, UnicodeError):
            _deny()
        except Exception:
            _deny()
        if (not 3 <= len(wire) <= MAX_FRAME_BYTES
                or len(wire) != record["wire_byte_length"]
                or _sha(wire) != record["wire_sha256"]):
            _deny()
        chain = hashlib.sha256(chain + wire).digest()
        if record.get("chain_sha256") != chain.hex():
            _deny()
        wire_total += len(wire)
        if wire_total > MAX_TOTAL_WIRE_BYTES:
            _deny()
        stream.update(wire)
        event = _json(wire, source=True)
        if ("id" in event or "error" in event
                or ("jsonrpc" in event and event["jsonrpc"] != "2.0")
                or not isinstance(event.get("method"), str)
                or not isinstance(event.get("params"), dict)):
            _deny()
        method, params = event["method"], event["params"]
        if phase == "before_start":
            t = params.get("turn")
            if (method != "turn/started" or not isinstance(t, dict)
                    or _id(params.get("threadId")) != thread
                    or _id(t.get("id")) != turn
                    or params.get("turnId", turn) != turn
                    or t.get("status") != "inProgress"
                    or t.get("items") != []):
                _deny()
            phase = "streaming"
            continue
        if phase != "streaming":
            _deny()
        if method == "turn/completed":
            t = params.get("turn")
            if (not isinstance(t, dict) or index != len(rows)-3
                    or _id(params.get("threadId")) != thread
                    or _id(t.get("id")) != turn
                    or params.get("turnId", turn) != turn
                    or t.get("status") != "completed"
                    or started.keys() - finished.keys()
                    or len(messages) != 2
                    or [m.role for m in messages] != ["user", "assistant"]):
                _deny()
            phase = "closed"
            continue
        if (_id(params.get("threadId")) != thread
                or _id(params.get("turnId")) != turn):
            _deny()
        if method in DELTA:
            continue
        if method == "item/started":
            item = params.get("item")
            if not isinstance(item, dict):
                _deny()
            iid = _id(item.get("id"))
            if (iid in started or iid in finished
                    or item.get("type") not in (
                        "userMessage", "agentMessage", *NON_CHAT)):
                _deny()
            started[iid] = item["type"]
            continue
        if method != "item/completed":
            _deny()
        item = params.get("item")
        if not isinstance(item, dict):
            _deny()
        iid = _id(item.get("id"))
        kind = item.get("type")
        # Unknown JSON kinds may be lists or dictionaries; membership in
        # a frozenset would otherwise raise TypeError rather than returning
        # the required static fail-closed diagnostic.
        if not isinstance(kind, str):
            _deny()
        if (iid in finished or iid in started and started[iid] != kind):
            _deny()
        finished[iid] = kind
        if kind in NON_CHAT:
            continue
        if kind == "userMessage":
            content = item.get("content")
            if (messages or not isinstance(content, list) or len(content) != 1
                    or not isinstance(content[0], dict)
                    or content[0].get("type") != "text"):
                _deny()
            text, digest = _parse_text(content[0].get("text"))
            role = "user"
        elif kind == "agentMessage":
            if (len(messages) != 1 or messages[0].role != "user"
                    or item.get("phase") != "final_answer"):
                _deny()
            text, digest = _parse_text(item.get("text"))
            role = "assistant"
        else:
            _deny()
        messages.append(FixtureMessage(
            role=role, item_id=iid, text_sha256=digest,
            frame_index=index, text=text,
        ))
    if (phase != "closed" or wire_total != seal["total_received_bytes"]
            or stream.hexdigest() != seal.get("received_stream_sha256")
            or chain.hex() != seal.get("last_chain_sha256")):
        _deny()
    summary = [
        {"role": m.role, "item_id": m.item_id, "frame_index": m.frame_index,
         "text_sha256": m.text_sha256}
        for m in messages
    ]
    if seal["messages"] != summary:
        _deny()
    return FixtureRead(
        scope=expected_scope, archive_id=expected_archive_id,
        thread_id=thread, turn_id=turn, messages=(messages[0], messages[1]),
    )


def discover_real_v2(_root=None) -> dict:
    """No filesystem scan or user-facing Memory discovery in this slice."""
    return {"status": "blocked", "reason": "v2 fixture reader not admitted"}


def expose_real_v2_source(_fixture=None) -> dict:
    """A valid synthetic witness still carries no OS disclosure grant."""
    return {"status": "blocked", "reason": "v2 fixture source not admitted"}
