import importlib.util
import json
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
            with self.assertRaises(RuntimeError):
                installer.detect_native(root)

    def test_marker_replacement_is_idempotent_for_standalone_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "AGENTS.md"
            path.write_text("# Rules\n", encoding="utf-8")
            installer.replace_marker_block(path, installer.STANDALONE_BLOCK)
            installer.replace_marker_block(path, installer.STANDALONE_BLOCK)
            text = path.read_text(encoding="utf-8")
            self.assertEqual(text.count("AI-VERSE-MEMORY:START"), 1)
            installer.replace_marker_block(path, None)
            self.assertNotIn("AI-VERSE-MEMORY:START", path.read_text(encoding="utf-8"))

    def test_local_extension_registration_is_idempotent_and_preserves_unknown_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / installer.LOCAL_REGISTRY
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "custom_top_level": {"keep": True},
                        "extensions": {
                            "other-extension": {"id": "other-extension", "enabled": True, "custom": "keep"},
                            "ai-verse-memory": {"id": "ai-verse-memory", "enabled": False, "custom": "keep-me"},
                        },
                    }
                ),
                encoding="utf-8",
            )

            installer.register_local_extension(root)
            installer.register_local_extension(root)
            payload = json.loads(registry.read_text(encoding="utf-8"))

            self.assertEqual(payload["custom_top_level"], {"keep": True})
            self.assertEqual(payload["extensions"]["other-extension"]["custom"], "keep")
            memory = payload["extensions"]["ai-verse-memory"]
            self.assertFalse(memory["enabled"])
            self.assertEqual(memory["custom"], "keep-me")
            self.assertTrue(memory["supported"])
            self.assertTrue(memory["installed"])
            self.assertEqual(memory["instructions"], "scripts/ai-verse-memory/MEMORY-PROTOCOL.md")
            self.assertEqual(memory["engine"], "scripts/ai-verse-memory/memory.py")
            self.assertEqual(len(memory["adapters"]), 2)

    def test_exact_legacy_native_edits_are_removed_without_touching_unrelated_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            agents = root / "AGENTS.md"
            baseline_agents = "# Rules\n\nUser-owned unrelated rule stays here.\n"
            agents.write_text(baseline_agents, encoding="utf-8")
            installer.replace_marker_block(agents, installer.NATIVE_BLOCK)

            registry = root / "skills/registry.yaml"
            baseline_registry = (
                'schema_version: "2.0"\n'
                "capabilities:\n"
                "  - id: onboard\n"
                "    scope: universal\n"
                "    purpose: \"Keep me\"\n\n"
                'promotion_rule: "Keep me too"\n'
            )
            registry.write_text(
                baseline_registry.replace(
                    'promotion_rule: "Keep me too"\n',
                    installer.LEGACY_REGISTRY_BLOCK + '\npromotion_rule: "Keep me too"\n',
                ),
                encoding="utf-8",
            )

            results = installer.migrate_legacy_native_integration(root)

            self.assertEqual(agents.read_text(encoding="utf-8"), baseline_agents)
            self.assertEqual(registry.read_text(encoding="utf-8"), baseline_registry)
            self.assertTrue(any("migrated exact legacy Memory marker" in item for item in results))
            self.assertTrue(any("migrated exact legacy Memory entry" in item for item in results))

    def test_modified_legacy_blocks_are_reported_and_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            agents = root / "AGENTS.md"
            modified_block = installer.NATIVE_BLOCK.replace(
                "AI-Verse Memory is installed as an optional memory engine.",
                "AI-Verse Memory is installed with my custom local note.",
            )
            agents.write_text("# Rules\n\n" + modified_block + "\n", encoding="utf-8")
            original_agents = agents.read_text(encoding="utf-8")

            registry = root / "skills/registry.yaml"
            registry.write_text(
                'schema_version: "2.0"\ncapabilities:\n'
                '  - id: ai-verse-memory\n    scope: user-modified\n    purpose: "custom"\n\n'
                'promotion_rule: "test"\n',
                encoding="utf-8",
            )
            original_registry = registry.read_text(encoding="utf-8")

            results = installer.migrate_legacy_native_integration(root)

            self.assertEqual(agents.read_text(encoding="utf-8"), original_agents)
            self.assertEqual(registry.read_text(encoding="utf-8"), original_registry)
            warnings = [item for item in results if item.startswith("warning:")]
            self.assertGreaterEqual(len(warnings), 2)


    def test_registry_lock_blocks_concurrent_memory_writer_without_losing_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / installer.LOCAL_REGISTRY
            registry.parent.mkdir(parents=True)
            registry.write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "extensions": {"ai-verse-data": {"id": "ai-verse-data", "custom": "keep"}},
                }) + "\n",
                encoding="utf-8",
            )
            lock = root / installer.LOCAL_REGISTRY_LOCK
            lock.write_text('{"extension_id":"other"}\n', encoding="utf-8")
            before = registry.read_bytes()

            with self.assertRaises(RuntimeError):
                installer.register_local_extension(root)

            self.assertEqual(registry.read_bytes(), before)
            self.assertEqual(
                json.loads(registry.read_text(encoding="utf-8"))["extensions"]["ai-verse-data"]["custom"],
                "keep",
            )

    def test_disable_enable_and_detach_preserve_canonical_memory_and_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "operator" / "memory" / "atomic").mkdir(parents=True)
            (root / "workspaces").mkdir()
            (root / "AI-VERSE.yaml").write_text(
                'schema_version: "2.0"\narchitecture: unified-workspace\n',
                encoding="utf-8",
            )
            canonical = root / "operator" / "memory" / "atomic" / "keep.md"
            canonical.write_text("# Memory\n\nkeep forever\n", encoding="utf-8")
            registry = root / installer.LOCAL_REGISTRY
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps({
                    "schema_version": "1.0",
                    "extensions": {"ai-verse-data": {"id": "ai-verse-data", "enabled": True}},
                }) + "\n",
                encoding="utf-8",
            )

            installer.register_local_extension(root)
            installer.disable_native(root)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            self.assertFalse(payload["extensions"]["ai-verse-memory"]["enabled"])
            self.assertIn("ai-verse-data", payload["extensions"])
            self.assertEqual(canonical.read_text(encoding="utf-8"), "# Memory\n\nkeep forever\n")

            installer.enable_native(root)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            self.assertTrue(payload["extensions"]["ai-verse-memory"]["enabled"])

            installer.detach_native(root)
            payload = json.loads(registry.read_text(encoding="utf-8"))
            self.assertNotIn("ai-verse-memory", payload["extensions"])
            self.assertIn("ai-verse-data", payload["extensions"])
            self.assertEqual(canonical.read_text(encoding="utf-8"), "# Memory\n\nkeep forever\n")

    def test_invalid_local_registry_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / installer.LOCAL_REGISTRY
            registry.parent.mkdir(parents=True)
            registry.write_text("not-json\n", encoding="utf-8")
            original = registry.read_bytes()

            with self.assertRaises(RuntimeError):
                installer.register_local_extension(root)

            self.assertEqual(registry.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
