import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MEMORY_SPEC = importlib.util.spec_from_file_location(
    "ai_verse_memory_relationship_neighbor_runtime_tests",
    ROOT / "scripts" / "memory.py",
)
mem = importlib.util.module_from_spec(MEMORY_SPEC)
assert MEMORY_SPEC.loader is not None
MEMORY_SPEC.loader.exec_module(mem)

BENCH_SPEC = importlib.util.spec_from_file_location(
    "ai_verse_memory_d2_fixture",
    ROOT / "scripts" / "neighbor_recall_benchmark.py",
)
bench = importlib.util.module_from_spec(BENCH_SPEC)
assert BENCH_SPEC.loader is not None
BENCH_SPEC.loader.exec_module(bench)


class RelationshipNeighborRuntimeTests(unittest.TestCase):
    def _fixture(self, base: Path):
        root = bench.native_root(base)
        fx = bench.fixture(mem, root)
        mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)
        return root, fx

    def test_detail_provenance_intent_adds_bounded_digest_neighbor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, fx = self._fixture(Path(tmp))
            digest_id = fx["ids"]["lesson_digest"]

            response = mem.progressive_recall(
                "Aurora export denoise context",
                depth="detail",
                workspace="alpha",
                limit=6,
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            neighbor = next(
                item for item in response["items"] if item.get("id") == digest_id
            )
            self.assertEqual(neighbor["record_type"], "session_digest")
            self.assertTrue(neighbor["relationship_neighbor"])
            self.assertEqual(
                neighbor["relationship"]["relation_type"],
                "derived_from",
            )
            self.assertTrue(neighbor["relationship"]["one_hop_only"])
            self.assertEqual(
                response["candidate_counts"]["relationship_neighbors"],
                1,
            )
            expansion = response["provenance"]["relationship_expansion"]
            self.assertTrue(expansion["enabled"])
            self.assertEqual(expansion["relations"], ["derived_from"])
            self.assertTrue(expansion["one_hop_only"])
            self.assertLessEqual(
                response["candidate_counts"]["relationship_neighbors"],
                mem.PROGRESSIVE_RECALL_MAX_RELATION_NEIGHBORS,
            )
            self.assertNotIn("BETA-PRIVATE-MARKER", json.dumps(response))

    def test_history_intent_adds_superseded_neighbor_and_preserves_exact_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, fx = self._fixture(Path(tmp))
            old_id = fx["ids"]["old"]

            response = mem.progressive_recall(
                "Atlas target port before correction",
                depth="detail",
                workspace="alpha",
                limit=6,
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            old = next(item for item in response["items"] if item.get("id") == old_id)

            self.assertTrue(old["relationship_neighbor"])
            self.assertEqual(old["status"], "superseded")
            self.assertEqual(old["relationship"]["relation_type"], "supersedes")

            source = mem.progressive_recall(
                "Atlas target port 7100",
                depth="source",
                workspace="alpha",
                evidence_ref=old,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(source["status"], "ok")
            self.assertTrue(source["exact_evidence"])
            self.assertIn("7100", source["source"]["content"])

    def test_current_truth_query_does_not_reintroduce_superseded_neighbor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, fx = self._fixture(Path(tmp))
            old_id = fx["ids"]["old"]
            current_id = fx["ids"]["correction"]

            response = mem.progressive_recall(
                "current Atlas target port",
                depth="detail",
                workspace="alpha",
                limit=6,
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            returned = {item.get("id") for item in response["items"]}

            self.assertIn(current_id, returned)
            self.assertNotIn(old_id, returned)
            self.assertEqual(
                response["candidate_counts"]["relationship_neighbors"],
                0,
            )
            expansion = response["provenance"]["relationship_expansion"]
            self.assertFalse(expansion["enabled"])
            self.assertEqual(expansion["relations"], [])
            self.assertNotIn("BETA-PRIVATE-MARKER", json.dumps(response))

    def test_summary_depth_and_full_limit_do_not_expand_neighbors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, fx = self._fixture(Path(tmp))
            digest_id = fx["ids"]["lesson_digest"]

            summary = mem.progressive_recall(
                "Aurora export denoise context",
                depth="summary",
                workspace="alpha",
                limit=6,
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertNotIn(digest_id, {item.get("id") for item in summary["items"]})
            self.assertEqual(
                summary["candidate_counts"]["relationship_neighbors"],
                0,
            )
            self.assertFalse(
                summary["provenance"]["relationship_expansion"]["enabled"]
            )

            bounded = mem.progressive_recall(
                "Aurora export denoise context",
                depth="detail",
                workspace="alpha",
                limit=1,
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertLessEqual(bounded["returned_items"], 1)
            self.assertEqual(
                bounded["candidate_counts"]["relationship_neighbors"],
                0,
            )
            self.assertNotIn(digest_id, {item.get("id") for item in bounded["items"]})


if __name__ == "__main__":
    unittest.main()
