import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_freshness", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class CanonicalFreshnessAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "ai-verse-os"
        self.root.mkdir()
        (self.root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\npaths:\n  operator: operator/\n  workspaces: workspaces/\n',
            encoding="utf-8",
        )
        for path in (
            "operator/profile",
            "operator/context",
            "operator/memory/atomic",
            "operator/decisions",
            "workspaces/alpha/context",
            "workspaces/alpha/memory/atomic",
            "workspaces/alpha/decisions",
            "runtime",
        ):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        (self.root / "workspaces/alpha/WORKSPACE.yaml").write_text(
            "id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: freshness acceptance\n",
            encoding="utf-8",
        )
        mem.ensure_layout(self.root, mem.MODE_NATIVE)

    def tearDown(self):
        self.tmp.cleanup()

    def _canonical_sources(self, prefix: str):
        return {
            "profile": (
                self.root / "operator/profile/preferences.md",
                "operator",
                None,
                f"{prefix}profiletoken",
            ),
            "context": (
                self.root / "workspaces/alpha/context/CURRENT.md",
                "workspace:alpha",
                "alpha",
                f"{prefix}contexttoken",
            ),
            "decision": (
                self.root / "workspaces/alpha/decisions/log.md",
                "workspace:alpha",
                "alpha",
                f"{prefix}decisiontoken",
            ),
        }

    def _recall(self, query: str, scope: str, workspace):
        if workspace:
            return mem.recall(query, workspace=workspace, root=self.root, mode=mem.MODE_NATIVE)
        return mem.recall(query, scope=scope, root=self.root, mode=mem.MODE_NATIVE)

    def _row_for_path(self, relative: str):
        conn, _ = mem.connect_db(self.root, mem.MODE_NATIVE)
        row = conn.execute("SELECT * FROM items WHERE path=?", (relative,)).fetchone()
        conn.close()
        return row

    def test_next_recall_refreshes_edited_profile_context_and_decision(self):
        sources = self._canonical_sources("old")
        for kind, (path, _, _, text) in sources.items():
            path.write_text(f"# {kind.title()}\n\n{text}\n", encoding="utf-8")
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_NATIVE)

        before_versions = {}
        for kind, (path, scope, workspace, old_text) in sources.items():
            relative = path.relative_to(self.root).as_posix()
            old_rows = self._recall(old_text, scope, workspace)
            old_row = next(r for r in old_rows if r["path"] == relative)
            before_versions[kind] = old_row["source_version"]
            self.assertEqual(old_row["freshness"], "fresh")
            self.assertTrue(old_row["source_identity"].startswith("sha256:"))
            self.assertTrue(old_row["source_version"].startswith("sha256:"))
            self.assertTrue(old_row["indexed_at"])

        for kind, (path, _, _, _) in sources.items():
            path.write_text(f"# {kind.title()}\n\nnew{kind}token\n", encoding="utf-8")

        for kind, (path, scope, workspace, old_text) in sources.items():
            relative = path.relative_to(self.root).as_posix()
            new_rows = self._recall(f"new{kind}token", scope, workspace)
            current = [r for r in new_rows if r["path"] == relative]
            self.assertEqual(len(current), 1)
            self.assertIn(f"new{kind}token", current[0]["text"])
            self.assertEqual(current[0]["freshness"], "fresh")
            self.assertNotEqual(current[0]["source_version"], before_versions[kind])

            old_rows = self._recall(old_text, scope, workspace)
            self.assertFalse(any(r["path"] == relative for r in old_rows))

    def test_next_recall_discovers_new_canonical_documents(self):
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_NATIVE)
        additions = self._canonical_sources("brandnew")

        for kind, (path, scope, workspace, text) in additions.items():
            path.write_text(f"# {kind.title()}\n\n{text}\n", encoding="utf-8")
            relative = path.relative_to(self.root).as_posix()
            rows = self._recall(text, scope, workspace)
            matches = [r for r in rows if r["path"] == relative]
            self.assertEqual(len(matches), 1, kind)
            self.assertEqual(matches[0]["freshness"], "fresh")
            self.assertTrue(matches[0]["source_version"].startswith("sha256:"))

    def test_next_recall_removes_deleted_profile_context_and_decision_from_items_and_fts(self):
        sources = self._canonical_sources("delete")
        for kind, (path, _, _, text) in sources.items():
            path.write_text(f"# {kind.title()}\n\n{text}\n", encoding="utf-8")
        mem.rebuild(silent=True, root=self.root, mode=mem.MODE_NATIVE)

        for kind, (path, scope, workspace, text) in sources.items():
            relative = path.relative_to(self.root).as_posix()
            row = self._row_for_path(relative)
            self.assertIsNotNone(row)
            row_id = row["id"]
            path.unlink()

            rows = self._recall(text, scope, workspace)
            self.assertFalse(any(r["path"] == relative for r in rows), kind)

            conn, fts = mem.connect_db(self.root, mem.MODE_NATIVE)
            self.assertIsNone(conn.execute("SELECT id FROM items WHERE id=?", (row_id,)).fetchone())
            self.assertIsNone(conn.execute("SELECT item_id FROM source_state WHERE item_id=?", (row_id,)).fetchone())
            if fts:
                count = conn.execute("SELECT count(*) FROM item_fts WHERE id=?", (row_id,)).fetchone()[0]
                self.assertEqual(count, 0)
            conn.close()

    def test_atomic_history_is_not_live_refreshed_as_canonical_context(self):
        mem_id, path, _ = mem.write_atomic(
            "historicalatomictokenold",
            "fact",
            "workspace:alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        original = mem.recall(
            "historicalatomictokenold",
            workspace="alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        row = next(r for r in original if r["id"] == mem_id)
        self.assertEqual(row["freshness"], "historical")
        indexed_version = row["source_version"]

        meta, _ = mem.parse_markdown(path)
        path.write_text(
            mem.render_frontmatter(meta)
            + "\n\n# Memory\n\nhistoricalatomictokenchanged\n",
            encoding="utf-8",
        )

        old_rows = mem.recall(
            "historicalatomictokenold",
            workspace="alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        old_row = next(r for r in old_rows if r["id"] == mem_id)
        self.assertIn("historicalatomictokenold", old_row["text"])
        self.assertEqual(old_row["source_version"], indexed_version)
        self.assertEqual(old_row["freshness"], "historical")

        changed_rows = mem.recall(
            "historicalatomictokenchanged",
            workspace="alpha",
            root=self.root,
            mode=mem.MODE_NATIVE,
        )
        self.assertFalse(any(r["id"] == mem_id for r in changed_rows))

    def test_existing_index_gets_source_state_without_manual_rebuild(self):
        db = mem.paths(self.root, mem.MODE_NATIVE)["db"]
        db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db)
        conn.execute(
            """
            CREATE TABLE items (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                type TEXT,
                scope TEXT,
                status TEXT,
                importance REAL,
                confidence REAL,
                created_at TEXT,
                updated_at TEXT,
                source TEXT,
                tags TEXT,
                text TEXT NOT NULL,
                why TEXT,
                authority REAL
            )
            """
        )
        conn.commit()
        conn.close()

        conn, _ = mem.connect_db(self.root, mem.MODE_NATIVE)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(source_state)").fetchall()}
        conn.close()
        self.assertEqual(
            columns,
            {"item_id", "source_identity", "source_version", "freshness", "indexed_at"},
        )


if __name__ == "__main__":
    unittest.main()
