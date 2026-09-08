import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_installer", ROOT / "scripts" / "install.py")
installer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(installer)


class InstallerLogicTests(unittest.TestCase):
    def test_native_detection_requires_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "operator").mkdir()
            (root / "workspaces").mkdir()
            (root / "AI-VERSE.yaml").write_text('schema_version: "2.0"\narchitecture: unified-workspace\n', encoding="utf-8")
            self.assertTrue(installer.detect_native(root))
            (root / "AI-VERSE.yaml").write_text('schema_version: "1.0"\narchitecture: other\n', encoding="utf-8")
            self.assertFalse(installer.detect_native(root))

    def test_marker_replacement_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            path.write_text("# Rules\n", encoding="utf-8")
            installer.replace_marker_block(path, installer.NATIVE_BLOCK)
            installer.replace_marker_block(path, installer.NATIVE_BLOCK)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("AI-VERSE-MEMORY:START"), 1)
            installer.replace_marker_block(path, None)
            self.assertNotIn("AI-VERSE-MEMORY:START", path.read_text(encoding="utf-8"))

    def test_capability_registration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            registry = root / "skills/registry.yaml"
            registry.write_text('schema_version: "2.0"\ncapabilities:\n\npromotion_rule: "test"\n', encoding="utf-8")
            installer.register_capability(root)
            installer.register_capability(root)
            text = registry.read_text(encoding="utf-8")
            self.assertEqual(text.count("id: ai-verse-memory"), 1)


if __name__ == "__main__":
    unittest.main()
