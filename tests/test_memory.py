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


class StandaloneMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "agent-os"
        self.root.mkdir()
        os.environ["AI_VERSE_MEMORY_ROOT"] = str(self.root)
        os.environ["AI_VERSE_MEMORY_HOME"] = str(self.root / ".ai-verse-memory")
        mem.ensure_layout(self.root, mem.MODE_STANDALONE)
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_STANDALONE)

    def tearDown(self):
        os.environ.pop("AI_VERSE_MEMORY_ROOT", None)
        os.environ.pop("AI_VERSE_MEMORY_HOME", None)
        self.tmp.cleanup()

    def test_remember_deduplicate_recall_and_rebuild(self):
        first_id, first_path, created = mem.write_atomic(
            text="Prefer concise project updates",
            mem_type="preference",
            scope="project:test",
            source="unit-test",
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )
        self.assertTrue(created)
        self.assertTrue(first_path.exists())

        duplicate_id, _, duplicate_created = mem.write_atomic(
            text="Prefer concise project updates",
            mem_type="preference",
            scope="project:test",
            source="unit-test",
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )
        self.assertFalse(duplicate_created)
        self.assertEqual(first_id, duplicate_id)

        rows = mem.recall("concise updates", "project:test", 8, False, self.root, mem.MODE_STANDALONE)
        self.assertTrue(any(r["id"] == first_id for r in rows))

        db = mem.paths(self.root, mem.MODE_STANDALONE)["db"]
        db.unlink()
        count = mem.rebuild(silent=True, root=self.root, mode=mem.MODE_STANDALONE)
        self.assertGreaterEqual(count, 2)  # profile + atomic memory
        rows_after = mem.recall("project updates", "project:test", 8, False, self.root, mem.MODE_STANDALONE)
        self.assertTrue(any(r["id"] == first_id for r in rows_after))

    def test_supersession_preserves_history(self):
        old_id, old_path, _ = mem.write_atomic(
            text="Use workflow A",
            mem_type="decision",
            scope="project:test",
            source="old-source",
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )
        args = argparse.Namespace(
            id=old_id,
            text="Use workflow B",
            type="decision",
            scope="project:test",
            workspace=None,
            importance=4,
            confidence=1.0,
            source="new-source",
            why="Workflow B passed validation.",
            tags="workflow",
            valid_from="",
        )
        mem.supersede(args, self.root, mem.MODE_STANDALONE)

        old_meta, _ = mem.parse_markdown(old_path)
        self.assertEqual(old_meta["status"], "superseded")
        current = mem.recall("workflow", "project:test", 8, False, self.root, mem.MODE_STANDALONE)
        self.assertFalse(any(r["id"] == old_id for r in current))
        self.assertTrue(any("workflow B" in r["text"] for r in current))
        history = mem.recall("workflow", "project:test", 8, True, self.root, mem.MODE_STANDALONE)
        self.assertTrue(any(r["id"] == old_id for r in history))

    def test_forget_deletes_canonical_memory(self):
        mem_id, path, _ = mem.write_atomic(
            text="Temporary durable test memory",
            mem_type="fact",
            source="unit-test",
            root=self.root,
            mode=mem.MODE_STANDALONE,
        )
        mem.forget_memory(mem_id, True, self.root, mem.MODE_STANDALONE)
        self.assertFalse(path.exists())


class NativeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ai-verse-os"
        self.root.mkdir()
        os.environ["AI_VERSE_MEMORY_ROOT"] = str(self.root)
        os.environ.pop("AI_VERSE_MEMORY_HOME", None)
        self._make_native_fixture()
        mem.ensure_layout(self.root, mem.MODE_NATIVE)
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_NATIVE)

    def tearDown(self):
        os.environ.pop("AI_VERSE_MEMORY_ROOT", None)
        self.tmp.cleanup()

    def _make_native_fixture(self):
        (self.root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\npaths:\n  operator: operator/\n  workspaces: workspaces/\n',
            encoding="utf-8",
        )
        for path in [
            "operator/profile",
            "operator/context",
            "operator/memory",
            "operator/decisions",
            "workspaces/alpha/context",
            "workspaces/alpha/memory",
            "workspaces/alpha/decisions",
            "workspaces/beta/context",
            "workspaces/beta/memory",
            "workspaces/beta/decisions",
            "runtime",
            "skills",
            ".claude/skills",
            ".agents/skills",
        ]:
            (self.root / path).mkdir(parents=True, exist_ok=True)
        (self.root / "workspaces/alpha/WORKSPACE.yaml").write_text("id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: test\n", encoding="utf-8")
        (self.root / "workspaces/beta/WORKSPACE.yaml").write_text("id: beta\nname: Beta\ntype: test\nstatus: active\npurpose: test\n", encoding="utf-8")
        (self.root / "operator/profile/preferences.md").write_text("# Preferences\n\nPrefer concise updates.\n", encoding="utf-8")
        (self.root / "operator/context/CURRENT.md").write_text("# Current\n\nOperator is focused on reliability.\n", encoding="utf-8")
        (self.root / "operator/decisions/log.md").write_text("# Decisions\n\nUse supervised rollout for risky automation.\n", encoding="utf-8")
        (self.root / "workspaces/alpha/context/CURRENT.md").write_text("# Alpha current\n\nAlpha is in supervised testing.\n", encoding="utf-8")
        (self.root / "workspaces/beta/context/CURRENT.md").write_text("# Beta current\n\nBeta is in private research.\n", encoding="utf-8")
        (self.root / "AGENTS.md").write_text("# Runtime\n", encoding="utf-8")
        (self.root / "CLAUDE.md").write_text("# Adapter\n", encoding="utf-8")
        (self.root / "skills/registry.yaml").write_text("schema_version: \"2.0\"\ncapabilities:\n\npromotion_rule: test\n", encoding="utf-8")

    def test_detect_native_and_no_second_profile(self):
        self.assertEqual(mem.detect_mode(self.root), mem.MODE_NATIVE)
        p = mem.ensure_layout(self.root, mem.MODE_NATIVE)
        self.assertTrue(p["operator_atomic"].exists())
        self.assertFalse((self.root / ".ai-verse-memory/profile.md").exists())
        self.assertEqual(p["db"], self.root / "runtime/indexes/ai-verse-memory/memory.db")

    def test_operator_and_workspace_physical_storage(self):
        _, operator_path, _ = mem.write_atomic(
            "Operator learned a durable lesson",
            "experience",
            "operator",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        _, alpha_path, _ = mem.write_atomic(
            "Alpha reached gate three",
            "state",
            "workspace:alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        self.assertIn("operator/memory/atomic", operator_path.as_posix())
        self.assertIn("workspaces/alpha/memory/atomic", alpha_path.as_posix())

    def test_workspace_recall_is_isolated_but_includes_operator(self):
        op_id, _, _ = mem.write_atomic(
            "Launch reviews should remain concise",
            "preference",
            "operator",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        alpha_id, _, _ = mem.write_atomic(
            "Alpha launch uses supervised approval",
            "state",
            "workspace:alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        beta_id, _, _ = mem.write_atomic(
            "Beta launch is confidential",
            "state",
            "workspace:beta",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        rows = mem.recall("launch", workspace="alpha", root=self.root, mode=mem.MODE_NATIVE)
        ids = {r["id"] for r in rows}
        self.assertIn(op_id, ids)
        self.assertIn(alpha_id, ids)
        self.assertNotIn(beta_id, ids)

        all_rows = mem.recall("launch", all_workspaces=True, root=self.root, mode=mem.MODE_NATIVE)
        all_ids = {r["id"] for r in all_rows}
        self.assertIn(beta_id, all_ids)

    def test_current_context_and_decisions_are_indexed_in_place(self):
        rows = mem.recall("supervised", workspace="alpha", root=self.root, mode=mem.MODE_NATIVE)
        paths = {r["path"] for r in rows}
        kinds = {r["kind"] for r in rows}
        self.assertIn("workspaces/alpha/context/CURRENT.md", paths)
        self.assertIn("operator/decisions/log.md", paths)
        self.assertIn("context", kinds)
        self.assertIn("decision", kinds)

    def test_unknown_workspace_refuses_write(self):
        with self.assertRaises(ValueError):
            mem.write_atomic(
                "Should not leak",
                "fact",
                "workspace:missing",
                root=self.root,
                mode=mem.MODE_NATIVE,
            )

    def test_legacy_project_scope_maps_only_to_existing_workspace(self):
        normalized = mem.normalize_scope("project:alpha", self.root, mem.MODE_NATIVE)
        self.assertEqual(normalized, "workspace:alpha")
        with self.assertRaises(ValueError):
            mem.normalize_scope("project:unknown", self.root, mem.MODE_NATIVE)

    def test_legacy_migration_is_non_destructive_and_scope_safe(self):
        legacy = self.root / ".ai-verse-memory/memories/2026/01"
        legacy.mkdir(parents=True)
        (legacy / "mem-global.md").write_text(
            "---\nid: mem-global\ntype: preference\nscope: global\nstatus: active\ncreated_at: 2026-01-01T00:00:00+00:00\n---\n\n# Memory\n\nPrefer local tools.\n",
            encoding="utf-8",
        )
        (legacy / "mem-alpha.md").write_text(
            "---\nid: mem-alpha\ntype: project_state\nscope: project:alpha\nstatus: active\ncreated_at: 2026-01-02T00:00:00+00:00\n---\n\n# Memory\n\nAlpha was prototyped.\n",
            encoding="utf-8",
        )
        (legacy / "mem-unknown.md").write_text(
            "---\nid: mem-unknown\ntype: fact\nscope: project:unknown\nstatus: active\ncreated_at: 2026-01-03T00:00:00+00:00\n---\n\n# Memory\n\nUnknown project detail.\n",
            encoding="utf-8",
        )
        dry = mem.migrate_legacy(self.root, apply=False)
        self.assertEqual(dry["migratable"], 2)
        self.assertEqual(dry["copied"], 0)
        self.assertEqual(dry["unresolved"], 1)
        self.assertIsNone(mem.locate_memory("mem-global", self.root, mem.MODE_NATIVE))

        applied = mem.migrate_legacy(self.root, apply=True)
        self.assertEqual(applied["copied"], 2)
        global_path = mem.locate_memory("mem-global", self.root, mem.MODE_NATIVE)
        alpha_path = mem.locate_memory("mem-alpha", self.root, mem.MODE_NATIVE)
        self.assertIsNotNone(global_path)
        self.assertIsNotNone(alpha_path)
        self.assertTrue((self.root / ".ai-verse-memory/memories/2026/01/mem-global.md").exists())
        self.assertIsNone(mem.locate_memory("mem-unknown", self.root, mem.MODE_NATIVE))
        global_meta, _ = mem.parse_markdown(global_path)
        alpha_meta, _ = mem.parse_markdown(alpha_path)
        self.assertEqual(global_meta["scope"], "operator")
        self.assertEqual(alpha_meta["scope"], "workspace:alpha")


if __name__ == "__main__":
    unittest.main()
