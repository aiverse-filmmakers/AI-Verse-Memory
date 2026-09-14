import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ai_verse_memory_d2_neighbor_benchmark_tests",
    ROOT / "scripts" / "neighbor_recall_benchmark.py",
)
bench = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(bench)


class NeighborRecallBenchmarkTests(unittest.TestCase):
    def test_d2_rejects_unearned_runtime_neighbor_expansion(self):
        result = bench.run_benchmark()
        print("D2_BENCHMARK_JSON=" + json.dumps(result, sort_keys=True))

        self.assertEqual(result["decision"], "reject")
        self.assertEqual(result["baseline"]["correct_scenarios"], 3)
        self.assertEqual(result["candidate"]["correct_scenarios"], 3)
        self.assertEqual(result["candidate"]["correctness_gain_scenarios"], 0)
        self.assertGreater(result["candidate"]["neighbors_returned"], 0)
        self.assertGreater(result["candidate"]["neighbor_bytes"], 0)
        self.assertGreaterEqual(
            result["candidate"]["context_inflation_ratio"],
            1.0,
        )

        self.assertTrue(result["bounds"]["one_hop_only"])
        self.assertEqual(result["bounds"]["workspace"], "alpha")
        self.assertLessEqual(
            max(len(row["neighbor_ids"]) for row in result["scenarios"]),
            result["bounds"]["max_neighbors_per_query"],
        )

        self.assertEqual(result["safety"]["scope_leakage_count"], 0)
        self.assertEqual(result["safety"]["stale_neighbor_count"], 0)
        self.assertFalse(result["safety"]["canonical_mutation"])
        self.assertNotIn("BETA-PRIVATE-MARKER", json.dumps(result))

    def test_benchmark_covers_decisions_lessons_and_corrections(self):
        result = bench.run_benchmark()
        self.assertEqual(
            {row["name"] for row in result["scenarios"]},
            {"decision", "lesson", "correction"},
        )
        correction = next(
            row for row in result["scenarios"] if row["name"] == "correction"
        )
        self.assertTrue(correction["baseline_correct"])
        self.assertTrue(correction["candidate_correct"])


if __name__ == "__main__":
    unittest.main()
