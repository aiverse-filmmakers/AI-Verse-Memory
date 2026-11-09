"""Pinned cross-repository OS #124 v2 fixture encoder -> Memory decoder.

Both implementations are loaded as code from pinned GitHub checkouts in
synthetic CI. No Codex process, user files, real OS storage, Memory
installation, live host, hooks or network access at test runtime.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest

from scripts import codex_archive_v2_fixture as mem_reader


OS_ROOT = os.environ.get("AI_VERSE_SYNTHETIC_OS_V2_ROOT", "")
OS_PIN = "f23d479f50c42636136a102922b42025a1533858"
PKG = "system/extensions/packages/ai-verse-codex-learning/"


def _load(name, relative):
    path = Path(OS_ROOT) / PKG / relative
    if not path.is_file() or path.is_symlink():
        raise AssertionError("pinned OS v2 source unavailable")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(OS_ROOT, "dedicated pinned OS v2 contract job only")
class ActualPinnedOSV2MemoryFixtureContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _load("_pinned_os_v2_evidence", "codex_app_server_source_evidence.py")
        cls.writer = _load("_pinned_os_v2_fixture_writer", "codex_app_server_archive_v2.py")
        if cls.writer.SCHEMA != mem_reader.SCHEMA:
            raise AssertionError("Memory and OS v2 archive schemas disagree")

    def frames(self):
        tid, turn = "fixture-crossrepo-8", "turn-crossrepo-8"
        def ev(method, **params):
            return {"method": method, "params": params}
        return [
            ev("turn/started", threadId=tid,
               turn={"id": turn, "status":"inProgress", "items":[]}),
            ev("item/completed", threadId=tid, turnId=turn,
               completedAtMs=1000, item={"id":"os-user-8", "type":"userMessage",
                     "content":[{"type":"text","text":"Crossrepo exact prompt 🧪 中文 \n  "}]}),
            ev("item/completed", threadId=tid, turnId=turn,
               completedAtMs=1001, item={"id":"os-agent-8", "type":"agentMessage",
                     "text":"Crossrepo final answer 🚀  ", "phase":"final_answer"}),
            ev("turn/completed", threadId=tid,
               turn={"id": turn, "status": "completed"}),
        ]

    def build(self):
        events = self.frames()
        wire = [
            json.dumps(e, ensure_ascii=False,
                       separators=(", ", ": ") if i % 2 else (",", ":")
                       ).encode("utf-8") + b"\n"
            for i, e in enumerate(events)
        ]
        candidate = self.source.evaluate_exact_fixture_frames(
            wire, expected_thread="fixture-crossrepo-8",
            expected_turn="turn-crossrepo-8",
        )
        result = self.writer.create_synthetic_envelope(
            candidate, wire, archive_id="pinned-v2-example",
            scope="workspace:alpha",
        )
        return result, wire, candidate

    def test_actual_os_encoder_to_independent_memory_v2_decoder(self):
        blob, wire, candidate = self.build()
        outcome = mem_reader.parse_synthetic_v2_bytes(
            blob, expected_scope="workspace:alpha",
            expected_archive_id="pinned-v2-example",
        )
        self.assertEqual(outcome.schema, self.writer.SCHEMA)
        self.assertEqual(outcome.messages[0].text, candidate.messages[0].text)
        self.assertEqual(outcome.messages[1].text, candidate.messages[1].text)
        self.assertEqual(outcome.messages[0].text_sha256,
                         hashlib.sha256(candidate.messages[0].text.encode()).hexdigest())
        self.assertFalse(outcome.live_recall_admitted)
        self.assertFalse(outcome.host_origin_authenticated)
        self.assertFalse(outcome.complete_ui_coverage)
        self.assertEqual(self.writer.admission(blob)["status"], "blocked")
        self.assertEqual(self.writer.save_real_chat(blob)["status"], "blocked")
        self.assertEqual(mem_reader.discover_real_v2()["status"], "blocked")
        self.assertNotIn(b"source_byte_offset", blob)

    def test_mutated_os_fixture_blob_rejected_by_actual_memory_decoder(self):
        blob, wire, _ = self.build()
        with self.assertRaises(mem_reader.V2MemoryBlocked):
            mem_reader.parse_synthetic_v2_bytes(
                blob[:-1], expected_scope="workspace:alpha",
                expected_archive_id="pinned-v2-example",
            )
        with self.assertRaises(mem_reader.V2MemoryBlocked):
            mem_reader.parse_synthetic_v2_bytes(
                blob, expected_scope="workspace:beta",
                expected_archive_id="pinned-v2-example",
            )
        rows = blob.splitlines(keepends=True)
        corrupted = json.loads(rows[2])
        corrupted["chain_sha256"] = "0"*64
        rows[2] = (json.dumps(corrupted, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":")).encode() + b"\n")
        with self.assertRaises(mem_reader.V2MemoryBlocked):
            mem_reader.parse_synthetic_v2_bytes(
                b"".join(rows), expected_scope="workspace:alpha",
                expected_archive_id="pinned-v2-example",
            )

    def test_no_v1_v2_confusion_and_no_live_source_provenance(self):
        blob, _, _ = self.build()
        self.assertNotIn(b"ai-verse.chat-archive/v1", blob)
        self.assertIn(self.writer.SCHEMA.encode(), blob)
        self.assertFalse(
            mem_reader.parse_synthetic_v2_bytes(
                blob, expected_scope="workspace:alpha",
                expected_archive_id="pinned-v2-example",
            ).consent_verified
        )
        self.assertEqual(mem_reader.expose_real_v2_source()["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
