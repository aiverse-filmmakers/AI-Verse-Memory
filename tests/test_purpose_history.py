import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("_purpose_history_test_module", ROOT / "scripts" / "purpose_history.py")
PURPOSE_HISTORY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = PURPOSE_HISTORY
SPEC.loader.exec_module(PURPOSE_HISTORY)


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.rows = [
            {
                "id": "recent-2",
                "kind": "memory",
                "type": "lesson",
                "scope": "workspace:film",
                "text": "The render queue failed until the retry budget was reduced.",
                "created_at": "2026-10-06T10:00:00+00:00",
                "updated_at": "2026-10-07T11:00:00+00:00",
            },
            {
                "id": "current-source",
                "kind": "context",
                "type": "state",
                "scope": "workspace:film",
                "text": "This is current source data, not historical Memory.",
                "updated_at": "2026-10-07T12:00:00+00:00",
            },
            {
                "id": "other-workspace",
                "kind": "memory",
                "type": "lesson",
                "scope": "workspace:other",
                "text": "Unrelated workspace history.",
                "updated_at": "2026-10-07T12:00:00+00:00",
            },
            {
                "id": "recent-1",
                "kind": "memory",
                "type": "experience",
                "scope": "workspace:film",
                "text": "A client review changed the delivery order for the film.",
                "created_at": "2026-10-07T10:00:00+00:00",
                "updated_at": "2026-10-07T10:00:00+00:00",
            },
            {
                "id": "old",
                "kind": "memory",
                "type": "lesson",
                "scope": "workspace:film",
                "text": "Old historical context outside the configured recent window.",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
        ]

    def recall(self, query, **kwargs):
        self.calls.append((query, kwargs))
        return list(self.rows)


class PurposeHistoryTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        PURPOSE_HISTORY.apply(self.engine)
        self.ref = {
            "owner": "ai-verse-brain",
            "scope": "workspace:film",
            "kind": "goal",
            "id": "ship-film",
            "version": "3",
        }

    def test_public_memory_wrapper_exposes_reader(self):
        spec = importlib.util.spec_from_file_location("_purpose_history_public_memory", ROOT / "scripts" / "memory.py")
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.read_purpose_history))
        self.assertEqual(module.PURPOSE_HISTORY_VERSION, "memory.purpose-history.v1")

    def test_returns_recent_scoped_memory_only(self):
        result = self.engine.read_purpose_history(
            scope="workspace:film",
            purpose_refs=[self.ref],
            query="film delivery retry",
            limit=8,
            max_bytes=4096,
            max_age_days=30,
            now="2026-10-07T12:00:00+00:00",
        )

        self.assertEqual(result["api_version"], "memory.purpose-history.v1")
        self.assertEqual(result["scope"], "workspace:film")
        self.assertEqual(result["purpose_refs"], [self.ref])
        self.assertEqual([item["id"] for item in result["history"]], ["recent-2", "recent-1"])
        self.assertFalse(any(item["id"] == "current-source" for item in result["history"]))
        self.assertFalse(any(item["id"] == "other-workspace" for item in result["history"]))
        self.assertFalse(any(item["id"] == "old" for item in result["history"]))
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False).encode("utf-8")), 4096)

        query, kwargs = self.engine.calls[0]
        self.assertEqual(query, "film delivery retry")
        self.assertEqual(kwargs["scope"], "workspace:film")
        self.assertEqual(kwargs["workspace"], "film")
        self.assertFalse(kwargs["all_workspaces"])
        self.assertFalse(kwargs["include_history"])
        self.assertLessEqual(kwargs["limit"], 50)

    def test_is_deterministic_and_hard_bounded(self):
        self.engine.rows = [
            {
                "id": f"m-{index:02d}",
                "kind": "memory",
                "type": "lesson",
                "scope": "workspace:film",
                "text": "x" * 2000,
                "updated_at": f"2026-10-{7 - index:02d}T10:00:00+00:00",
            }
            for index in range(6)
        ]
        first = self.engine.read_purpose_history(
            scope="workspace:film",
            purpose_refs=[self.ref],
            query="film",
            limit=5,
            max_bytes=2048,
            max_age_days=30,
            now="2026-10-07T12:00:00+00:00",
        )
        second = self.engine.read_purpose_history(
            scope="workspace:film",
            purpose_refs=[self.ref],
            query="film",
            limit=5,
            max_bytes=2048,
            max_age_days=30,
            now="2026-10-07T12:00:00+00:00",
        )
        self.assertEqual(first, second)
        self.assertTrue(first["truncated"])
        self.assertLessEqual(len(json.dumps(first, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")), 2048)
        self.assertLessEqual(first["returned"], 5)

    def test_rejects_cross_scope_or_unbound_requests(self):
        with self.assertRaisesRegex(ValueError, "does not match request scope"):
            self.engine.read_purpose_history(
                scope="workspace:film",
                purpose_refs=[{**self.ref, "scope": "workspace:other"}],
                query="film",
            )
        with self.assertRaisesRegex(ValueError, "purpose_refs must contain"):
            self.engine.read_purpose_history(
                scope="workspace:film",
                purpose_refs=[],
                query="film",
            )
        with self.assertRaisesRegex(ValueError, "query must be non-empty"):
            self.engine.read_purpose_history(
                scope="workspace:film",
                purpose_refs=[self.ref],
                query="",
            )


if __name__ == "__main__":
    unittest.main()
