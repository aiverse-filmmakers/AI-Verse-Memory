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
    def test_d2_captures_fair_neighbor_value_and_cost_evidence(self):
        result = bench.run_benchmark()
        print("D2_BENCHMARK_JSON=" + json.dumps(result, sort_keys=True))

        self.assertEqual(result["decision"], "pending_evidence_review")
        self.assertEqual(result["baseline"]["total_scenarios"], 4)
        self.assertEqual(result["candidate"]["total_scenarios"], 4)
        self.assertGreaterEqual(result["candidate"]["correctness_gain_scenarios"], 2)
        self.assertGreater(result["candidate"]["neighbors_returned"], 0)
        self.assertGreater(result["candidate"]["neighbor_bytes"], 0)
        self.assertGreaterEqual(result["candidate"]["context_inflation_ratio"], 1.0)

        self.assertTrue(result["bounds"]["one_hop_only"])
        self.assertTrue(result["bounds"]["query_intent_gated"])
        self.assertEqual(result["bounds"]["workspace"], "alpha")
        self.assertLessEqual(
            max(len(row["neighbor_ids"]) for row in result["scenarios"]),
            result["bounds"]["max_neighbors_per_query"],
        )

        self.assertEqual(result["safety"]["scope_leakage_count"], 0)
        self.assertEqual(result["safety"]["stale_neighbor_count"], 0)
        self.assertFalse(result["safety"]["canonical_mutation"])
        self.assertNotIn("BETA-PRIVATE-MARKER", json.dumps(result))

    def test_benchmark_covers_provenance_history_and_current_truth(self):
        result = bench.run_benchmark()
        by_name = {row["name"]: row for row in result["scenarios"]}
        self.assertEqual(
            set(by_name),
            {
                "lesson_provenance",
                "decision_provenance",
                "correction_history",
                "correction_current",
            },
        )

        self.assertFalse(by_name["lesson_provenance"]["baseline_correct"])
        self.assertTrue(by_name["lesson_provenance"]["candidate_correct"])
        self.assertFalse(by_name["decision_provenance"]["baseline_correct"])
        self.assertTrue(by_name["decision_provenance"]["candidate_correct"])
        self.assertFalse(by_name["correction_history"]["baseline_correct"])
        self.assertTrue(by_name["correction_history"]["candidate_correct"])

        self.assertTrue(by_name["correction_current"]["baseline_correct"])
        self.assertTrue(by_name["correction_current"]["candidate_correct"])
        self.assertEqual(by_name["correction_current"]["neighbor_ids"], [])
        self.assertEqual(by_name["correction_current"]["relation_intent"], [])


if __name__ == "__main__":
    unittest.main()
