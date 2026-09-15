import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_PATH = ROOT / "scripts" / "context_ladder_benchmark.py"

spec = importlib.util.spec_from_file_location(
    "ai_verse_memory_j1_context_benchmark_tests",
    BENCHMARK_PATH,
)
benchmark = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(benchmark)


class ContextLadderJ1BenchmarkTests(unittest.TestCase):
    def test_machine_readable_j1_memory_benchmark(self):
        result = benchmark.run_benchmark(samples=1)

        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(
            result["benchmark_version"],
            "memory.context-ladder-j1.v1",
        )
        self.assertEqual(result["owner"], "ai-verse-memory")
        self.assertEqual(result["candidate"]["total_scenarios"], 6)
        self.assertEqual(result["candidate"]["correct_scenarios"], 6)
        self.assertEqual(result["candidate"]["correctness"], 1.0)
        self.assertTrue(result["candidate"]["exact_fact_recovery"])
        self.assertTrue(result["candidate"]["long_history_recovery"])
        self.assertEqual(result["safety"]["scope_leakage_count"], 0)
        self.assertTrue(result["safety"]["stale_source_fail_closed"])
        self.assertFalse(result["safety"]["canonical_mutation_during_rebuild"])
        self.assertTrue(result["durability"]["orientation_rebuilt_equivalent"])
        self.assertTrue(result["durability"]["relationship_rebuilt_equivalent"])
        self.assertTrue(result["durability"]["restart_recall_ok"])
        self.assertGreaterEqual(result["candidate"]["source_reads"], 3)

        scenario_ids = {row["scenario_id"] for row in result["scenarios"]}
        self.assertEqual(
            scenario_ids,
            {
                "very_old_prior_session",
                "corrected_fact",
                "exact_number_date_path_config",
                "repeated_project_client_context",
                "two_similar_workspaces",
                "canonical_source_changed_after_derived_artifact",
            },
        )

        print(
            "J1_MEMORY_BENCHMARK_JSON="
            + json.dumps(result, sort_keys=True, separators=(",", ":"))
        )


if __name__ == "__main__":
    unittest.main()
