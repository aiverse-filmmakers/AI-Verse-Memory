import argparse
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class MemoryLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / ".ai-verse-memory"
        os.environ["AI_VERSE_MEMORY_HOME"] = str(self.home)
        mem.ensure_layout()
        mem.rebuild(silent=True)

    def tearDown(self):
        os.environ.pop("AI_VERSE_MEMORY_HOME", None)
        self.tmp.cleanup()

    def test_remember_deduplicate_recall_and_rebuild(self):
        first_id, first_path, created = mem.write_atomic(
            text="Prefer cinematic bright images",
            mem_type="preference",
            scope="project:test",
            source="unit-test",
        )
        self.assertTrue(created)
        self.assertTrue(first_path.exists())

        duplicate_id, _, duplicate_created = mem.write_atomic(
            text="Prefer cinematic bright images",
            mem_type="preference",
            scope="project:test",
            source="unit-test",
        )
        self.assertFalse(duplicate_created)
        self.assertEqual(first_id, duplicate_id)

        rows = mem.recall("cinematic images", "project:test", 8, False)
        self.assertTrue(any(r["id"] == first_id for r in rows))

        db = mem.paths()["db"]
        db.unlink()
        count = mem.rebuild(silent=True)
        self.assertGreaterEqual(count, 2)  # profile + atomic memory
        rows_after = mem.recall("bright cinematic", "project:test", 8, False)
        self.assertTrue(any(r["id"] == first_id for r in rows_after))

    def test_supersession_preserves_history(self):
        old_id, old_path, _ = mem.write_atomic(
            text="Use workflow A",
            mem_type="decision",
            scope="project:test",
            source="old-source",
        )
        args = argparse.Namespace(
            id=old_id,
            text="Use workflow B",
            type="decision",
            scope="project:test",
            importance=4,
            confidence=1.0,
            source="new-source",
            why="Workflow B passed the new validation gate.",
            tags="workflow",
            valid_from="",
        )
        mem.supersede(args)

        old_meta, _ = mem.parse_markdown(old_path)
        self.assertEqual(old_meta["status"], "superseded")
        self.assertTrue(old_meta["superseded_by"])

        current = mem.recall("workflow", "project:test", 8, False)
        self.assertFalse(any(r["id"] == old_id for r in current))
        self.assertTrue(any("workflow B" in r["text"] for r in current))

        history = mem.recall("workflow", "project:test", 8, True)
        self.assertTrue(any(r["id"] == old_id for r in history))

    def test_discovery_and_migration_marker(self):
        project = Path(self.tmp.name) / "project"
        (project / "context").mkdir(parents=True)
        (project / "context" / "preferences.md").write_text("Prefer short updates", encoding="utf-8")
        (project / "node_modules").mkdir()
        (project / "node_modules" / "noise.md").write_text("ignore", encoding="utf-8")
        report = self.home / "state" / "discovery.md"

        found = mem.discover(project, report, 50)
        paths = {p.resolve() for p, _, _ in found}
        self.assertIn((project / "context" / "preferences.md").resolve(), paths)
        self.assertNotIn((project / "node_modules" / "noise.md").resolve(), paths)
        self.assertTrue(report.exists())

        mem.migration_complete("unit test")
        payload = mem.paths()["migration"].read_text(encoding="utf-8")
        self.assertIn("unit test", payload)


if __name__ == "__main__":
    unittest.main()
