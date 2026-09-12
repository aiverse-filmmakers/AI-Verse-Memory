import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ai_verse_memory_external_migration",
    ROOT / "scripts" / "memory.py",
)
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class ExternalLegacyMigrationTests(unittest.TestCase):
    def _native_root(self, base: Path) -> Path:
        root = base / "os"
        root.mkdir()
        (root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\n',
            encoding="utf-8",
        )
        (root / "operator").mkdir()
        (root / "workspaces" / "alpha").mkdir(parents=True)
        (root / "workspaces" / "alpha" / "WORKSPACE.yaml").write_text(
            'id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: migration test\n',
            encoding="utf-8",
        )
        mem.ensure_layout(root, mem.MODE_NATIVE)
        return root

    def _standalone_root(self, base: Path) -> Path:
        root = base / "standalone"
        root.mkdir()
        mem.ensure_layout(root, mem.MODE_STANDALONE)
        return root

    def test_external_standalone_store_migrates_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._standalone_root(base)
            native = self._native_root(base)

            operator_id, operator_path, created = mem.write_atomic(
                text="pre-os operator memory",
                mem_type="fact",
                scope="global",
                source="standalone:test",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            self.assertTrue(created)
            workspace_id, workspace_path, created = mem.write_atomic(
                text="pre-os workspace memory",
                mem_type="state",
                scope="project:alpha",
                source="standalone:test",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            self.assertTrue(created)

            source_before = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }

            dry = mem.migrate_legacy(native, apply=False, source_root=source)
            self.assertEqual(dry["migratable"], 2)
            self.assertEqual(dry["copied"], 0)
            self.assertIsNone(mem.locate_memory(operator_id, native, mem.MODE_NATIVE))
            self.assertIsNone(mem.locate_memory(workspace_id, native, mem.MODE_NATIVE))

            applied = mem.migrate_legacy(native, apply=True, source_root=source)
            self.assertEqual(applied["copied"], 2)
            operator_new = mem.locate_memory(operator_id, native, mem.MODE_NATIVE)
            workspace_new = mem.locate_memory(workspace_id, native, mem.MODE_NATIVE)
            self.assertIsNotNone(operator_new)
            self.assertIsNotNone(workspace_new)
            self.assertIn("operator/memory/atomic", operator_new.as_posix())
            self.assertIn("workspaces/alpha/memory/atomic", workspace_new.as_posix())

            source_after = {
                path.relative_to(source).as_posix(): path.read_bytes()
                for path in source.rglob("*")
                if path.is_file()
            }
            self.assertEqual(source_after, source_before)
            self.assertTrue(operator_path.exists())
            self.assertTrue(workspace_path.exists())

    def test_external_source_rejects_symlinked_memory_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._standalone_root(base)
            native = self._native_root(base)
            _, memory_path, _ = mem.write_atomic(
                text="safe original",
                mem_type="fact",
                scope="global",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            outside = base / "outside.md"
            outside.write_text(
                "---\nid: escaped\ntype: fact\nscope: global\ncreated_at: 2026-09-12T00:00:00+00:00\n---\n\n# Memory\n\nescaped\n",
                encoding="utf-8",
            )
            memory_path.unlink()
            try:
                memory_path.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable: {exc}")

            result = mem.migrate_legacy(native, apply=True, source_root=source)
            self.assertEqual(result["invalid"], 1)
            self.assertEqual(result["copied"], 0)
            self.assertIsNone(mem.locate_memory("escaped", native, mem.MODE_NATIVE))


if __name__ == "__main__":
    unittest.main()
