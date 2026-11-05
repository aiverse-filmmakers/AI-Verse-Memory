"""Synthetic cross-repository contract against the *actual* OS PR #122 writer.

The pinned source is checked out read-only by the dedicated GitHub Actions job.
These tests invoke OS ChatArchive.append, then Memory progressive_recall.
No provider, hooks, running host, personal installation or fixture re-renderer.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

from tests.test_chat_archive_progressive import ChatArchiveProgressiveTests
from tests.test_progressive_recall import mem


OS_WRITER_RELATIVE = (
    "system/extensions/packages/ai-verse-codex-learning/chat_archive.py"
)
OS_WRITER_PIN = "237f333347ffb5b6f94131c8555f90b22fc39556"
OS_CHECKOUT = os.environ.get("AI_VERSE_SYNTHETIC_OS_WRITER_ROOT", "")


def _load_actual_os_writer():
    path = Path(OS_CHECKOUT) / OS_WRITER_RELATIVE
    if not path.is_file() or path.is_symlink():
        raise AssertionError("pinned OS #122 writer unavailable; do not substitute fixture")
    module_name = "_synthetic_actual_os_1b_writer_contract"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("cannot import pinned OS writer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    if module.SCHEMA != "ai-verse.chat-archive/v1":
        raise AssertionError("OS writer archive schema changed")
    return module


def _raw_event(seq, text):
    return (json.dumps({
        "type": "user" if seq % 2 else "assistant",
        "sessionId": "contract-session",
        "uuid": f"source-event-{seq}",
        "message": {"role": "user" if seq % 2 else "assistant",
                    "content": [{"type": "text", "text": text}]},
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")


@unittest.skipUnless(OS_CHECKOUT, "dedicated pinned OS writer contract CI only")
class PinnedOSWriterMemoryContract(unittest.TestCase):
    def setUp(self):
        self.os_writer = _load_actual_os_writer()
        self.helper = ChatArchiveProgressiveTests()

    def _root(self, tmp):
        return self.helper._root(tmp)

    def _archive(self, root, scope="workspace:alpha", archive_id="real-writer-fixture"):
        return self.os_writer.ChatArchive(
            root,
            scope=scope, authorized_scope=scope,
            archive_id=archive_id, chat_id="contract-chat",
            origin="claude-code", session_id="contract-session",
            authorization_check=lambda selected: selected == scope,
        )

    def _append(self, archive, seq, text, offset):
        source = _raw_event(seq, text)
        event = self.os_writer.ArchiveEvent(
            source_event_id=f"immutable-source-{seq}",
            source_byte_offset=offset,
            source_end_offset=offset + len(source),
            source_record_sha256=hashlib.sha256(source).hexdigest(),
            source_record_bytes=source,
            block_index=0,
            message_id=f"provider-message-{seq}",
            sequence=seq,
            role="user" if seq % 2 else "assistant",
            text=text,
            record_terminated=True,
            attachment_availability="not_embedded",
        )
        receipt = archive.append(event)
        return event, receipt, offset + len(source)

    def _detail(self, root, query="crossrepo"):
        result = mem.progressive_recall(
            query, depth="detail", workspace="alpha",
            root=root, mode=mem.MODE_NATIVE, max_bytes=10000,
        )
        return [i for i in result["items"]
                if i["record_type"] == "portable_chat_message"]

    def _source(self, root, detail):
        return mem.progressive_recall(
            "crossrepo", depth="source", evidence_ref=detail,
            workspace="alpha", root=root, mode=mem.MODE_NATIVE,
            max_bytes=10000,
        )

    def test_real_os_writer_to_memory_exact_bytes_and_replayed_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            archive = self._archive(root)
            text = "  crossrepo exact text 👩‍🚀 中文\n\n\ttrailing spaces  "
            event1, receipt1, offset = self._append(archive, 1, text, 0)
            self.assertEqual(receipt1.status, "saved")
            self.assertEqual(archive.append(event1).status, "replayed")
            self.assertEqual(archive.read().messages[0]["text"], text)

            # Actual physical JSONL is emitted by OS writer, not test renderer.
            path = root / "archives/private-chat-history/v1/workspaces/alpha/real-writer-fixture.jsonl"
            self.assertTrue(path.is_file())
            lines = path.read_bytes().splitlines()
            self.assertEqual(len(lines), 2)
            committed_record = json.loads(lines[1])
            self.assertEqual(committed_record["source_end_offset"], offset)
            self.assertEqual(committed_record["source_event_id"], "immutable-source-1")
            self.assertEqual(committed_record["message_id"], "provider-message-1")

            detail = self._detail(root)
            self.assertEqual(len(detail), 1)
            self.assertEqual(detail[0]["text"], text)
            self.assertEqual(detail[0]["message_id"], "provider-message-1")
            self.assertEqual(detail[0]["evidence"]["source_record_sha256"],
                             event1.source_record_sha256)
            result = self._source(root, detail[0])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["source"]["content"], text)
            self.assertTrue(result["exact_evidence"])

    def test_actual_writer_append_duplicate_text_and_copied_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            archive = self._archive(root)
            identical = "crossrepo duplicated visible text"
            first, _, offset = self._append(archive, 1, identical, 0)
            first_detail = self._detail(root)[0]
            second, _, offset = self._append(archive, 2, identical, offset)
            self.assertEqual(archive.append(second).status, "replayed")
            items = self._detail(root)
            self.assertEqual(len(items), 2)
            self.assertNotEqual(items[0]["id"], items[1]["id"])
            self.assertEqual({d["message_id"] for d in items},
                             {"provider-message-1", "provider-message-2"})
            self.assertEqual(self._source(root, first_detail)["status"], "ok")

            copied = Path(tmp) / "copied-os"
            shutil.copytree(root, copied)
            shutil.rmtree(root)
            self.assertEqual(self._source(copied, first_detail)["status"], "ok")
            self.assertEqual(self._source(copied, items[1])["source"]["content"],
                             identical)
            self.assertEqual(self._detail(copied)[0]["id"], first_detail["id"])

    def test_actual_writer_pending_source_conflict_and_denied_deleted_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._root(tmp)
            archive = self._archive(root)
            first, _, offset = self._append(archive, 1, "crossrepo first", 0)
            # The OS writer is authoritative for distinguishing provisional
            # from committed source records. Memory must never see pending.
            partial_bytes = b'{"type":"assistant","content":"pending"}'
            pending = self.os_writer.ArchiveEvent(
                source_event_id="uncommitted-source",
                source_byte_offset=offset,
                source_end_offset=offset + len(partial_bytes),
                source_record_sha256=hashlib.sha256(partial_bytes).hexdigest(),
                source_record_bytes=partial_bytes,
                block_index=0, message_id="pending-message", sequence=2,
                role="assistant", text="crossrepo pending",
                record_terminated=False,
            )
            self.assertEqual(archive.append(pending).status, "pending")
            self.assertEqual(len(self._detail(root)), 1)

            # Changed bytes at an immutable event identity cannot be appended.
            changed = self.os_writer.ArchiveEvent(
                source_event_id=first.source_event_id,
                source_byte_offset=0, source_end_offset=first.source_end_offset,
                source_record_sha256=first.source_record_sha256,
                source_record_bytes=first.source_record_bytes,
                block_index=0, message_id=first.message_id, sequence=1,
                role=first.role, text="crossrepo changed",
                record_terminated=True,
            )
            with self.assertRaises(self.os_writer.ArchiveConflict):
                archive.append(changed)

            detail = self._detail(root)[0]
            self.assertEqual(self._source(root, detail)["status"], "ok")
            manifest = root / "workspaces/alpha/WORKSPACE.yaml"
            manifest.write_text('schema_version: "2.0"\nid: "alpha"\nstatus: paused\n',
                                encoding="utf-8")
            with self.assertRaises(ValueError):
                self._source(root, detail)
            manifest.write_text('schema_version: "2.0"\nid: "alpha"\nstatus: active\n',
                                encoding="utf-8")
            path = root / "archives/private-chat-history/v1/workspaces/alpha/real-writer-fixture.jsonl"
            path.unlink()
            self.assertEqual(self._source(root, detail)["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
