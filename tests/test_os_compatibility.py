import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


compat = load_module("test_os_compat", ROOT / "scripts" / "os_compat.py")
installer = load_module("test_installer_gate", ROOT / "scripts" / "install.py")
memory = load_module("test_memory_gate", ROOT / "scripts" / "memory.py")


def write_manifest(root: Path, schema: str = "2.0", architecture: str = "unified-workspace") -> None:
    (root / "AI-VERSE.yaml").write_text(
        f'schema_version: "{schema}"\narchitecture: "{architecture}"\n',
        encoding="utf-8",
    )


def make_layout(root: Path) -> None:
    (root / "operator").mkdir(parents=True, exist_ok=True)
    (root / "workspaces").mkdir(parents=True, exist_ok=True)


def snapshot(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            result[relative] = ("dir", None)
        elif path.is_file():
            result[relative] = ("file", path.read_bytes())
        else:
            result[relative] = ("other", None)
    return result


class CompatibilityClassifierTests(unittest.TestCase):
    def test_no_manifest_is_no_os(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = compat.detect_os_compatibility(Path(tmp))
            self.assertEqual(result.status, compat.OS_NONE)

    def test_supported_v2_is_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, "2.7")
            make_layout(root)
            result = compat.detect_os_compatibility(root)
            self.assertEqual(result.status, compat.OS_COMPATIBLE)
            self.assertEqual(installer.detect_native(root), True)
            self.assertEqual(memory.detect_mode(root), memory.MODE_NATIVE)

    def test_v3_is_incompatible_not_standalone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_manifest(root, "3.0")
            make_layout(root)
            result = compat.detect_os_compatibility(root)
            self.assertEqual(result.status, compat.OS_INCOMPATIBLE)
            with self.assertRaises(RuntimeError):
                installer.detect_native(root)
            with self.assertRaises(RuntimeError):
                memory.detect_mode(root)

    def test_malformed_and_incomplete_manifests_are_incompatible(self):
        cases = [
            ('architecture: "unified-workspace"\n', True),
            ('schema_version: "banana"\narchitecture: "unified-workspace"\n', True),
            ('schema_version: "2.0"\narchitecture: "other"\n', True),
            ('schema_version: "2.0"\nschema_version: "2.1"\narchitecture: "unified-workspace"\n', True),
            ('schema_version: "2.0"\narchitecture: "unified-workspace"\n', False),
        ]
        for manifest_text, include_layout in cases:
            with self.subTest(manifest=manifest_text, include_layout=include_layout):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    (root / "AI-VERSE.yaml").write_text(manifest_text, encoding="utf-8")
                    if include_layout:
                        make_layout(root)
                    result = compat.detect_os_compatibility(root)
                    self.assertEqual(result.status, compat.OS_INCOMPATIBLE)


class IncompatibleHostNoWriteTests(unittest.TestCase):
    def make_incompatible(self, schema: str = "3.0", malformed: bool = False) -> Path:
        root = Path(self.tmp.name) / "host"
        root.mkdir()
        if malformed:
            (root / "AI-VERSE.yaml").write_text('schema_version: "2.0"\n', encoding="utf-8")
        else:
            write_manifest(root, schema)
        make_layout(root)
        (root / "AGENTS.md").write_text("# Existing host instructions\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# Existing Claude instructions\n", encoding="utf-8")
        return root

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def assert_no_memory_install_artifacts(self, root: Path) -> None:
        self.assertFalse((root / ".ai-verse-memory").exists())
        self.assertFalse((root / ".aiverse").exists())
        self.assertFalse((root / ".claude").exists())
        self.assertFalse((root / ".agents").exists())
        self.assertFalse((root / "scripts" / "ai-verse-memory").exists())
        self.assertFalse((root / "runtime").exists())

    def run_installer_and_assert_unchanged(self, root: Path) -> None:
        before = snapshot(root)
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "install.py"),
                "--target",
                str(root),
                "--source-dir",
                str(ROOT),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("install blocked", result.stderr)
        self.assertEqual(snapshot(root), before)
        self.assert_no_memory_install_artifacts(root)

    def run_engine_and_assert_unchanged(self, root: Path) -> None:
        before = snapshot(root)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "memory.py"), "--root", str(root), "init"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("Incompatible AI-Verse OS", result.stderr)
        self.assertEqual(snapshot(root), before)
        self.assert_no_memory_install_artifacts(root)

    def test_v3_installer_and_engine_block_before_writes(self):
        root = self.make_incompatible(schema="3.0")
        self.run_installer_and_assert_unchanged(root)
        self.run_engine_and_assert_unchanged(root)

    def test_malformed_manifest_installer_and_engine_block_before_writes(self):
        root = self.make_incompatible(malformed=True)
        self.run_installer_and_assert_unchanged(root)
        self.run_engine_and_assert_unchanged(root)

    def test_incomplete_v2_layout_blocks_before_writes(self):
        root = Path(self.tmp.name) / "incomplete"
        root.mkdir()
        write_manifest(root, "2.0")
        (root / "AGENTS.md").write_text("unchanged\n", encoding="utf-8")
        before = snapshot(root)
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "install.py"), "--target", str(root), "--source-dir", str(ROOT)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(snapshot(root), before)
        self.assert_no_memory_install_artifacts(root)


if __name__ == "__main__":
    unittest.main()
