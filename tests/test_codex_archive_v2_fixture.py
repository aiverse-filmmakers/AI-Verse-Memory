"""In-memory v2 Memory reader tests. The archive builder here is a test
fixture ONLY; a separate pinned cross-repository test uses the OS encoder.
No production archives, discovery, provider accounts, home or file I/O.
"""
import base64
from dataclasses import replace
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

SRC = Path(__file__).resolve().parents[1] / "scripts" / "codex_archive_v2_fixture.py"
spec = importlib.util.spec_from_file_location("_memory_3a8_v2_fixture", SRC)
reader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reader
spec.loader.exec_module(reader)


def line(row):
    return (json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False,
                       separators=(",", ":")).encode("utf-8") + b"\n")


class V2MemoryFixtureContractTests(unittest.TestCase):
    def frames(self):
        thread, turn = "synthetic-thread-v2", "synthetic-turn-v2"
        def ev(method, **params):
            return {"method": method, "params": params}
        return [
            ev("turn/started", threadId=thread,
               turn={"id":turn, "status":"inProgress", "items":[]}),
            ev("item/completed", threadId=thread, turnId=turn,
               item={"id":"first-item", "type":"userMessage",
                     "content":[{"type":"text", "text":" original 🧪 text \n "}]}),
            ev("item/completed", threadId=thread, turnId=turn,
               item={"id":"last-item", "type":"agentMessage",
                     "phase":"final_answer", "text":" final response 🚀 "}),
            ev("turn/completed", threadId=thread,
               turn={"id":turn, "status":"completed"}),
        ]

    def archive(self, events=None, header_changes=None, seal_changes=None,
                override_user_summary_text=None):
        events = self.frames() if events is None else events
        frames = [line(e) for e in events]
        header = {
            "kind": "header", "schema": reader.SCHEMA,
            "archive_id": "archive-v2-fixture", "scope": "workspace:alpha",
            "origin": "codex-app-server-received",
            "thread_id": "synthetic-thread-v2", "turn_id": "synthetic-turn-v2",
            "mode": "synthetic_fixture_only",
            "source_class": "exact_received_jsonl_unverified",
            "host_origin_authenticated": False, "scope_authenticated": False,
            "consent_verified": False, "complete_ui_coverage": False,
            "write_admitted": False,
        }
        if header_changes:
            header.update(header_changes)
        serialized = [line(header)]
        chain = hashlib.sha256(serialized[0]).digest()
        stream = hashlib.sha256()
        for index, raw in enumerate(frames):
            chain = hashlib.sha256(chain + raw).digest()
            stream.update(raw)
            serialized.append(line({
                "kind": "frame", "schema": reader.SCHEMA, "index": index,
                "wire_b64": base64.b64encode(raw).decode("ascii"),
                "wire_byte_length": len(raw), "wire_sha256": hashlib.sha256(raw).hexdigest(),
                "chain_sha256": chain.hex(),
            }))
        summary = []
        for index, item in ((1, events[1]["params"]["item"]),
                            (2, events[2]["params"]["item"])):
            role = "user" if index == 1 else "assistant"
            text = (override_user_summary_text if role == "user"
                    and override_user_summary_text is not None else
                    item["content"][0]["text"] if role == "user" else item["text"])
            summary.append({
                "role":role, "item_id":item["id"], "frame_index":index,
                "text_sha256":hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
        seal = {
            "kind":"seal", "schema":reader.SCHEMA,
            "frame_count":len(frames), "total_received_bytes":sum(map(len, frames)),
            "received_stream_sha256":stream.hexdigest(),
            "last_chain_sha256":chain.hex(), "messages":summary,
            "original_source_offsets":None,
            "host_origin_authenticated":False, "scope_authenticated":False,
            "consent_verified":False, "complete_ui_coverage":False,
            "write_admitted":False,
        }
        if seal_changes:
            seal.update(seal_changes)
        serialized.append(line(seal))
        return b"".join(serialized)

    def parse(self, blob=None, scope="workspace:alpha"):
        return reader.parse_synthetic_v2_bytes(
            self.archive() if blob is None else blob,
            expected_scope=scope, expected_archive_id="archive-v2-fixture",
        )

    def blocked(self, action):
        with self.assertRaises(reader.V2MemoryBlocked) as caught:
            action()
        self.assertEqual(str(caught.exception), "untrusted v2 Memory fixture refused")

    def test_valid_exact_received_wire_is_still_untrusted(self):
        result = self.parse()
        self.assertEqual([m.role for m in result.messages], ["user","assistant"])
        self.assertEqual(result.messages[0].text, " original 🧪 text \n ")
        self.assertEqual(result.messages[1].text, " final response 🚀 ")
        self.assertFalse(result.live_recall_admitted)
        self.assertFalse(result.consent_verified)
        self.assertFalse(result.host_origin_authenticated)
        self.assertFalse(result.complete_ui_coverage)
        self.assertEqual(result.verdict, "untrusted_synthetic_v2_fixture_not_discoverable")
        self.assertNotIn("original 🧪", repr(result))
        self.assertNotIn("original 🧪", repr(result.messages[0]))

    def test_data_change_breaks_hash_chain_even_if_json_valid(self):
        blob = self.archive()
        corrupt = blob.replace(b"\"wire_sha256\":", b"\"wire_sha252\":", 1)
        self.blocked(lambda: self.parse(corrupt))
        parsed = blob.splitlines(keepends=True)
        x = json.loads(parsed[2])
        x["chain_sha256"] = "0"*64
        parsed[2] = line(x)
        self.blocked(lambda: self.parse(b"".join(parsed)))

    def test_seal_mismatch_and_missing_frame_refuse(self):
        blob = self.archive()
        self.blocked(lambda: self.parse(blob.replace(
            b"\"frame_count\":4", b"\"frame_count\":5"
        )))
        rows = blob.splitlines(keepends=True)
        self.blocked(lambda: self.parse(b"".join(rows[:3]+rows[4:])))
        self.blocked(lambda: self.parse(blob[:-2]))
        self.blocked(lambda: self.parse(blob+b"{}\n"))

    def test_header_scope_is_match_guard_not_authorization(self):
        result = self.parse()
        self.assertEqual(result.scope, "workspace:alpha")
        self.blocked(lambda: self.parse(scope="workspace:beta"))
        self.blocked(lambda: self.parse(self.archive(
            header_changes={"scope":"workspace:beta"})))
        self.assertEqual(reader.discover_real_v2()["status"], "blocked")
        self.assertEqual(reader.expose_real_v2_source(result)["status"], "blocked")

    def test_claimed_consent_auth_and_full_coverage_refuse(self):
        for field in ("write_admitted", "host_origin_authenticated",
                      "scope_authenticated", "consent_verified",
                      "complete_ui_coverage"):
            with self.subTest(field=field):
                self.blocked(lambda: self.parse(
                    self.archive(header_changes={field:True})))
                self.blocked(lambda: self.parse(
                    self.archive(seal_changes={field:True})))

    def test_original_offset_claim_is_not_permitted(self):
        self.blocked(lambda: self.parse(self.archive(
            seal_changes={"original_source_offsets":{"start":0,"end":100}})))

    def test_noncanonical_envelope_and_extra_fields_refuse(self):
        rows = self.archive().splitlines(keepends=True)
        rows[0] = json.dumps(json.loads(rows[0]), indent=1).encode("utf-8")+b"\n"
        self.blocked(lambda: self.parse(b"".join(rows)))
        self.blocked(lambda: self.parse(self.archive(
            header_changes={"untrusted_new_field":"hidden"})))

    def test_noncanonical_base64_and_bad_hash_refuse(self):
        rows = self.archive().splitlines(keepends=True)
        item = json.loads(rows[1])
        item["wire_b64"] += "="
        rows[1] = line(item)
        self.blocked(lambda: self.parse(b"".join(rows)))
        rows = self.archive().splitlines(keepends=True)
        item = json.loads(rows[1])
        item["wire_sha256"] = "0"*64
        rows[1] = line(item)
        self.blocked(lambda: self.parse(b"".join(rows)))

    def test_mixed_thread_and_turn_synthetic_records_refuse(self):
        for index, change in ((0,{"threadId":"outside"}),
                              (1,{"turnId":"outside"}),
                              (3,{"threadId":"outside"})):
            with self.subTest(index=index):
                rows = self.frames()
                rows[index]["params"].update(change)
                self.blocked(lambda: self.parse(self.archive(rows)))

    def test_ambiguous_media_and_nonfinal_assistant_refuse(self):
        # Rebuild correct SHA-256/chain/seal for each source variant, so a
        # semantic failure cannot be mistaken for trivial corrupt hashes.
        for content in (
            [{"type":"image","url":"fake"}],
            [{"type":"text","text":"a"},{"type":"text","text":"b"}],
        ):
            rows = self.frames()
            rows[1]["params"]["item"]["content"] = content
            blob = self.archive(rows, override_user_summary_text="synthetic fallback")
            self.blocked(lambda: self.parse(blob))
        for phase in ("commentary", "partial_answer", None):
            rows = self.frames()
            rows[2]["params"]["item"]["phase"] = phase
            self.blocked(lambda: self.parse(self.archive(rows)))

    def test_writer_never_mints_real_disclosure_authority(self):
        self.assertEqual(reader.discover_real_v2()["status"], "blocked")
        self.assertEqual(reader.expose_real_v2_source()["status"], "blocked")
        with mock.patch("builtins.open", side_effect=AssertionError("no real file IO")):
            result = self.parse()
            self.assertFalse(result.live_recall_admitted)

    def test_invalid_bytes_size_and_record_count_refuse(self):
        for malformed in (b"", "notbytes", bytearray(self.archive()),
                          self.archive()+b"\r", self.archive()[:-1]):
            self.blocked(lambda: self.parse(malformed))
        with mock.patch.object(reader, "MAX_ARCHIVE_BYTES", 20):
            self.blocked(self.parse)

    def test_unknown_event_even_with_rebuilt_hash_chain_refuses(self):
        rows = self.frames()
        # A source with a perfectly valid envelope but an unrecognized
        # lifecycle method must still be refused by Memory's own parser.
        rows[2]["method"] = "thread/resumed"
        self.blocked(lambda: self.parse(self.archive(rows)))


if __name__ == "__main__":
    unittest.main()
