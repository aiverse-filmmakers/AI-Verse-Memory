"""Synthetic OS v1 private archive contract for Memory progressive recall.

Tests do not use Claude, a personal OS installation, or a running Gateway.
Only the portable JSONL shape from OS slice 1B is constructed here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from tests.native_lifecycle_fixture import mark_native_ready
from tests.test_progressive_recall import mem

FORMAT = "ai-verse.chat-archive/v1"


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def archive_record(scope, archive_id, session, sequence, text, *, offset=0,
                   event_id=None, message_id=None):
    # Source record is a synthetic *complete* JSONL event; no real provider IO.
    source = packed({"role": "user" if sequence % 2 else "assistant",
                     "visible": text, "uuid": "source-" + str(sequence)}) + b"\n"
    row = {
        "kind": "message", "schema": FORMAT, "archive_id": archive_id,
        "scope": scope, "origin": "claude-code", "session_id": session,
        "source_event_id": event_id or f"fixture-event-{sequence}",
        "source_byte_offset": offset,
        "source_end_offset": offset + len(source),
        "source_record_sha256": sha(source),
        "block_index": 0,
        "message_id": message_id or f"fixture-message-{sequence}",
        "sequence": sequence, "role": "user" if sequence % 2 else "assistant",
        "text": text, "attachment_availability": "not_embedded",
        "text_sha256": sha(text.encode("utf-8")),
        "timestamp": None, "revision": None, "branch": None,
    }
    row["archive_record_sha256"] = sha(packed(row))
    return row


def write_archive(root, scope, archive_id="fixture-archive", texts=None):
    texts = texts or ["  Cosmic portable reference 🧪 中文\n  original text "]
    suffix = ["operator"] if scope == "operator" else [
        "workspaces", scope.split(":", 1)[1]]
    path = root.joinpath("archives", "private-chat-history", "v1",
                         *suffix, archive_id + ".jsonl")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Every directory beneath private-chat-history is explicitly private.
    path_cursor = root / "archives" / "private-chat-history"
    for part in ("v1", *suffix):
        path_cursor = path_cursor / part
        path_cursor.mkdir(mode=0o700, exist_ok=True)
        if os.name != "nt":
            path_cursor.chmod(0o700)
    if os.name != "nt":
        (root / "archives/private-chat-history").chmod(0o700)
    session = "session-" + archive_id
    header = {
        "kind": "header", "schema": FORMAT,
        "archive_id": archive_id, "chat_id": "chat-" + archive_id,
        "origin": "claude-code", "session_id": session, "scope": scope,
    }
    offset = 0
    rows = []
    for index, text in enumerate(texts, 1):
        row = archive_record(scope, archive_id, session, index, text, offset=offset)
        rows.append(row)
        offset = row["source_end_offset"]
    path.write_bytes(b"\n".join(packed(row) for row in [header, *rows]) + b"\n")
    if os.name != "nt":
        path.chmod(0o600)
    return path, rows


class ChatArchiveProgressiveTests(unittest.TestCase):
    def _root(self, parent):
        root = Path(parent) / "os"
        root.mkdir()
        (root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\n',
            encoding="utf-8")
        (root / "operator").mkdir()
        for name in ("alpha", "beta"):
            ws = root / "workspaces" / name
            ws.mkdir(parents=True)
            (ws / "WORKSPACE.yaml").write_text(
                f'schema_version: "2.0"\nid: "{name}"\n'
                f'name: "{name.title()}"\nstatus: active\n',
                encoding="utf-8")
        mark_native_ready(root, mem)
        return root

    def _call(self, root, depth, query="", **more):
        return mem.progressive_recall(
            query, depth=depth, workspace="alpha", root=root,
            mode=mem.MODE_NATIVE, max_bytes=10000, **more)

    def _detail(self, root, query="portable"):
        result = self._call(root, "detail", query)
        return next(row for row in result["items"]
                    if row["record_type"] == "portable_chat_message")

    def _source(self, root, detail, query="portable", **more):
        return mem.progressive_recall(
            query, depth="source", workspace="alpha", root=root,
            mode=mem.MODE_NATIVE, evidence_ref=detail, max_bytes=10000, **more)

    def test_catalog_summary_detail_source_verbatim_and_query_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            text = "  Cosmic portable reference 🧪 中文\n  original text "
            write_archive(root, "workspace:alpha", texts=[text])
            catalog = self._call(root, "catalog")
            self.assertEqual(catalog["catalog"]["counts"]["portable_chat_messages"], 1)
            self.assertTrue(catalog["deeper_evidence_available"])
            summary = self._call(root, "summary", "portable cosmic")
            portable = [row for row in summary["items"]
                        if row["record_type"] == "portable_chat_message"]
            self.assertEqual(len(portable), 1)
            self.assertIn("Cosmic portable", portable[0]["excerpt"])
            self.assertNotIn("text", portable[0])
            detail = self._detail(root)
            self.assertEqual(detail["text"], text)
            self.assertEqual(detail["role"], "user")
            self.assertEqual(detail["message_id"], "fixture-message-1")
            source = self._source(root, detail)
            self.assertEqual(source["status"], "ok")
            self.assertTrue(source["exact_evidence"])
            self.assertEqual(source["source"]["content"], text)
            self.assertEqual(source["source"]["window_start_char"], 0)
            self.assertEqual(source["evidence"]["source_event_id"], "fixture-event-1")
            self.assertEqual(self._call(root, "summary", "no-matching-phrase")["items"], [])
            self.assertLessEqual(len(packed(source)), 10000)

    def test_copy_entire_os_folder_then_delete_original_keeps_same_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            write_archive(root, "workspace:alpha")
            detail = self._detail(root)
            source_before = self._source(root, detail)
            copied = Path(tmp) / "relocated-os"
            shutil.copytree(root, copied)
            shutil.rmtree(root)
            source_after = self._source(copied, detail)
            self.assertEqual(source_after["status"], "ok")
            self.assertEqual(source_after["source"], source_before["source"])
            self.assertEqual(source_after["evidence"], source_before["evidence"])

    def test_append_keeps_old_pointer_and_duplicate_identical_text_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            text = "portable identical visible message"
            path, old_rows = write_archive(root, "workspace:alpha", texts=[text])
            detail = self._detail(root)
            current = path.read_bytes()
            second = archive_record("workspace:alpha", "fixture-archive",
                                    "session-fixture-archive", 2, text,
                                    offset=old_rows[-1]["source_end_offset"])
            path.write_bytes(current + packed(second) + b"\n")
            self.assertEqual(self._source(root, detail)["status"], "ok")
            results = self._call(root, "detail", "portable")
            portable = [row for row in results["items"]
                        if row["record_type"] == "portable_chat_message"]
            self.assertEqual(len(portable), 2)
            self.assertNotEqual(portable[0]["id"], portable[1]["id"])
            self.assertEqual({row["message_id"] for row in portable},
                             {"fixture-message-1", "fixture-message-2"})
            self.assertEqual(self._call(root, "catalog")["catalog"]
                             ["counts"]["portable_chat_messages"], 2)

    def test_cross_workspace_denial_and_current_workspace_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            write_archive(root, "workspace:alpha", texts=["alpha portable witness"])
            write_archive(root, "workspace:beta", archive_id="beta-fixture",
                          texts=["beta private portable witness"])
            alpha = self._detail(root)
            other = mem.progressive_recall(
                "beta private portable", depth="detail", workspace="beta",
                root=root, mode=mem.MODE_NATIVE, max_bytes=10000)
            beta = next(row for row in other["items"]
                        if row["record_type"] == "portable_chat_message")
            with self.assertRaises(ValueError):
                self._source(root, beta)
            view = self._call(root, "summary", "private portable")
            self.assertNotIn("beta private", json.dumps(view).lower())
            self.assertEqual(self._source(root, alpha)["status"], "ok")
            (root / "workspaces/alpha/WORKSPACE.yaml").write_text(
                'schema_version: "2.0"\nid: "alpha"\nstatus: paused\n')
            with self.assertRaises(ValueError):
                self._source(root, alpha)

    def test_deleted_stale_and_corrupt_evidence_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            path, rows = write_archive(root, "workspace:alpha")
            detail = self._detail(root)
            path.unlink()
            self.assertEqual(self._source(root, detail)["status"], "unavailable")
            path, _ = write_archive(root, "workspace:alpha",
                                    texts=["portable changed source evidence"])
            self.assertEqual(self._source(root, detail)["status"], "stale")
            raw = path.read_bytes().replace(b"changed", b"broken!")
            path.write_bytes(raw)
            self.assertEqual(self._source(root, detail)["status"], "unavailable")

    def test_private_permissions_symlink_and_other_scope_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            path, _ = write_archive(root, "workspace:alpha")
            detail = self._detail(root)
            if os.name != "nt":
                path.chmod(0o644)
                self.assertEqual(self._source(root, detail)["status"], "unavailable")
                path.chmod(0o600)
            outside = Path(tmp) / "external-source.jsonl"
            shutil.copy2(path, outside)
            path.unlink()
            try:
                path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink fixtures unsupported")
            self.assertEqual(self._source(root, detail)["status"], "unavailable")

    def test_mixed_healthy_malformed_oversized_and_raced_archives_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            healthy, _ = write_archive(
                root, "workspace:alpha", archive_id="healthy-public-contract",
                texts=["portable healthy result stays retrievable"],
            )
            invalid, _ = write_archive(
                root, "workspace:alpha", archive_id="sensitive-invalid-client",
                texts=["SENSITIVE_MALFORMED_BODY_DO_NOT_ECHO"],
            )
            oversized, _ = write_archive(
                root, "workspace:alpha", archive_id="sensitive-too-large-client",
                texts=["SENSITIVE_OVERSIZE_BODY_DO_NOT_ECHO"],
            )
            raced, _ = write_archive(
                root, "workspace:alpha", archive_id="sensitive-race-client",
                texts=["SENSITIVE_RACE_BODY_DO_NOT_ECHO"],
            )
            # Load Memory's actual dynamic reader module from the public API.
            self._call(root, "catalog")
            import sys
            reader = sys.modules["_aiverse_memory_portable_chat_sources"]
            invalid.write_bytes(b'{"kind":,}\n')
            with oversized.open("ab") as stream:
                stream.truncate(reader.MAX_ARCHIVE_BYTES + 1)
            original = reader._read_bytes

            def raced_read(os_root, candidate):
                if candidate == raced:
                    raise FileNotFoundError("sensitive-race-client")
                return original(os_root, candidate)

            with mock.patch.object(reader, "_read_bytes", side_effect=raced_read):
                catalog = self._call(root, "catalog")
                summary = self._call(root, "summary", "portable healthy")
                detail = self._call(root, "detail", "portable healthy")
            health = {"skipped": 3, "invalid": 1, "oversized": 1, "raced": 1}
            for response in (catalog, summary, detail):
                self.assertEqual(response["provenance"]["archive_skips"], health)
                serialized = json.dumps(response, ensure_ascii=False)
                for secret in (
                    "sensitive-invalid-client", "sensitive-too-large-client",
                    "sensitive-race-client", "SENSITIVE_MALFORMED_BODY_DO_NOT_ECHO",
                    "SENSITIVE_OVERSIZE_BODY_DO_NOT_ECHO",
                    "SENSITIVE_RACE_BODY_DO_NOT_ECHO",
                ):
                    self.assertNotIn(secret, serialized)
            self.assertEqual(
                catalog["catalog"]["counts"]["portable_chat_messages"], 1
            )
            self.assertEqual(summary["candidate_counts"]["portable_chat_messages"], 1)
            self.assertEqual(detail["candidate_counts"]["portable_chat_messages"], 1)
            source = self._source(
                root, next(i for i in detail["items"]
                           if i["record_type"] == "portable_chat_message")
            )
            self.assertEqual(source["status"], "ok")
            self.assertEqual(source["source"]["content"],
                             "portable healthy result stays retrievable")
            self.assertTrue(healthy.is_file())

    def test_bad_exact_source_unavailable_while_another_archive_is_healthy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            healthy, _ = write_archive(
                root, "workspace:alpha", archive_id="healthy-contract",
                texts=["portable healthy exact source"],
            )
            damaged, _ = write_archive(
                root, "workspace:alpha", archive_id="damaged-contract",
                texts=["portable damaged exact source"],
            )
            details = self._call(root, "detail", "portable")
            pointers = {
                row["evidence"]["archive_id"]: row for row in details["items"]
                if row["record_type"] == "portable_chat_message"
            }
            damaged.write_bytes(b'{"kind":,}\n')
            self.assertEqual(
                self._source(root, pointers["damaged-contract"])["status"],
                "unavailable",
            )
            self.assertEqual(
                self._source(root, pointers["healthy-contract"])["status"],
                "ok",
            )
            self.assertTrue(healthy.exists())
            response = self._call(root, "detail", "portable")
            self.assertEqual(response["provenance"]["archive_skips"],
                             {"skipped": 1, "invalid": 1})
            self.assertEqual(response["candidate_counts"]["portable_chat_messages"], 1)

    def test_archive_local_failure_never_masks_revoked_workspace_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            file, _ = write_archive(root, "workspace:alpha",
                                    texts=["portable authorization-bound source"])
            self._call(root, "catalog")
            import sys
            reader = sys.modules["_aiverse_memory_portable_chat_sources"]
            manifest = root / "workspaces/alpha/WORKSPACE.yaml"

            def revoke_while_reading(os_root, candidate):
                manifest.write_text(
                    'schema_version: "2.0"\nid: "alpha"\nstatus: paused\n'
                )
                raise FileNotFoundError("file vanished under revoked permission")

            with mock.patch.object(reader, "_read_bytes", side_effect=revoke_while_reading):
                with self.assertRaises(ValueError):
                    self._call(root, "detail", "portable")
            self.assertTrue(file.exists())

    def test_global_archive_count_and_message_budgets_remain_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            write_archive(root, "workspace:alpha", archive_id="archive-a",
                          texts=["portable one", "portable two"])
            write_archive(root, "workspace:alpha", archive_id="archive-b",
                          texts=["portable three"])
            self._call(root, "catalog")
            import sys
            reader = sys.modules["_aiverse_memory_portable_chat_sources"]
            with mock.patch.object(reader, "MAX_ARCHIVES", 1):
                with self.assertRaises(reader.ArchiveSourceBlocked):
                    self._call(root, "catalog")
            with mock.patch.object(reader, "MAX_TOTAL_MESSAGES", 2):
                with self.assertRaises(reader.ArchiveSourceBlocked):
                    self._call(root, "detail", "portable")
            with mock.patch.object(reader, "MAX_DIAGNOSTIC_COUNT", 1):
                # Diagnostics are saturating but healthy results still survive.
                damaged, _ = write_archive(root, "workspace:alpha",
                                           archive_id="archive-invalid",
                                           texts=["unusable"])
                damaged.write_bytes(b"not-json\n")
                other, _ = write_archive(root, "workspace:alpha",
                                         archive_id="archive-another-invalid",
                                         texts=["unusable"])
                other.write_bytes(b"not-json\n")
                response = self._call(root, "detail", "portable")
                self.assertEqual(response["provenance"]["archive_skips"],
                                 {"skipped": 1, "invalid": 1, "saturated": True})

    def test_digest_fallback_and_no_archive_preserve_legacy_recall(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            mem.write_session_digest(
                "fallback-session", "Release digest portable fallback is preserved.",
                run_id="fallback-run", scope="workspace:alpha", topic="portable fallback",
                source_refs=["gateway:session:fallback-session"],
                source_coverage=["gateway:messages:0-2"],
                source_fingerprint="sha256:" + "a" * 64,
                source_version="gateway-run-v1",
                provenance={"owner": "gateway", "kind": "completed_session"},
                completed_at="2026-11-05T12:00:00+00:00",
                effect_id="fixture-digest-fallback", root=root, mode=mem.MODE_NATIVE)
            old = self._call(root, "detail", "portable fallback")
            digest = next(row for row in old["items"]
                          if row["record_type"] == "session_digest")
            fallback = self._source(root, digest, query="portable fallback")
            self.assertEqual(fallback["status"], "external_source_required")
            self.assertEqual(old["candidate_counts"]["session_digests"], 1)
            self.assertNotIn("portable_chat_messages", old["candidate_counts"])
            write_archive(root, "workspace:alpha",
                          texts=["portable fallback source side by side"])
            combined = self._call(root, "detail", "portable fallback")
            self.assertIn("session_digest",
                          {row["record_type"] for row in combined["items"]})
            self.assertIn("portable_chat_message",
                          {row["record_type"] for row in combined["items"]})
            self.assertEqual(self._source(root, digest,
                             query="portable fallback")["status"],
                             "external_source_required")


if __name__ == "__main__":
    unittest.main()
