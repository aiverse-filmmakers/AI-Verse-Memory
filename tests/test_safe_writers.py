import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ENGINE = _load("safe_writers_engine", "memory_engine.py")
INSTALL = _load("safe_writers_install_engine", "install_engine.py")


class EngineSafeWriterTests(unittest.TestCase):
    def test_crash_during_replace_keeps_old_file_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "memory.md"
            target.write_text("old content\n", encoding="utf-8")
            with mock.patch.object(ENGINE.os, "replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    ENGINE.safe_write_text(target, "new content\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old content\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["memory.md"])

    def test_crash_while_writing_keeps_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "memory.md"
            target.write_text("old content\n", encoding="utf-8")
            with mock.patch.object(ENGINE.os, "fsync", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    ENGINE.safe_write_text(target, "new content\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old content\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["memory.md"])

    def test_writes_utf8_with_lf_and_creates_missing_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a" / "b" / "memory.md"
            ENGINE.safe_write_text(target, "café\nline two\n")
            self.assertEqual(target.read_bytes(), "café\nline two\n".encode("utf-8"))

    @unittest.skipIf(os.name == "nt", "permission bits are not meaningful on Windows")
    def test_existing_file_keeps_its_mode_and_new_file_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "existing.md"
            existing.write_text("old\n", encoding="utf-8")
            os.chmod(existing, 0o644)
            ENGINE.safe_write_text(existing, "new\n")
            self.assertEqual(existing.stat().st_mode & 0o777, 0o644)
            fresh = Path(tmp) / "fresh.md"
            ENGINE.safe_write_text(fresh, "new\n")
            self.assertEqual(fresh.stat().st_mode & 0o777, 0o600)

    def test_symlinked_target_keeps_the_link_and_replaces_the_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            real_dir = Path(tmp) / "real"
            real_dir.mkdir()
            real = real_dir / "memory.md"
            real.write_text("old\n", encoding="utf-8")
            link = Path(tmp) / "link.md"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            ENGINE.safe_write_text(link, "new\n")
            self.assertTrue(link.is_symlink())
            self.assertEqual(real.read_text(encoding="utf-8"), "new\n")
            self.assertEqual(sorted(p.name for p in real_dir.iterdir()), ["memory.md"])

    def test_engine_has_no_plain_write_text_left(self):
        source = (SCRIPTS / "memory_engine.py").read_text(encoding="utf-8")
        self.assertNotIn(".write_text(", source)


class InstallerSafeWriterTests(unittest.TestCase):
    def test_text_write_crash_keeps_old_file_and_permissions_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "AGENTS.md"
            target.write_text("old\n", encoding="utf-8")
            os.chmod(target, 0o640)
            with mock.patch.object(INSTALL.os, "replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    INSTALL._write_text_lf(target, "new\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["AGENTS.md"])
            INSTALL._write_text_lf(target, "new\n")
            self.assertEqual(target.read_bytes(), b"new\n")
            if os.name != "nt":
                self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_copy_crash_keeps_old_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.py"
            dest = Path(tmp) / "dest.py"
            src.write_text("new\n", encoding="utf-8")
            dest.write_text("old\n", encoding="utf-8")
            with mock.patch.object(INSTALL.os, "replace", side_effect=OSError("simulated crash")):
                with self.assertRaises(OSError):
                    INSTALL._atomic_copy(src, dest)
            self.assertEqual(dest.read_text(encoding="utf-8"), "old\n")
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["dest.py", "src.py"])
            INSTALL._atomic_copy(src, dest)
            self.assertEqual(dest.read_text(encoding="utf-8"), "new\n")


class DirectRunTests(unittest.TestCase):
    def test_engine_file_refuses_a_direct_run(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "memory_engine.py"), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot be run directly", result.stderr)
        self.assertIn("memory.py", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_supported_entry_point_still_runs(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "memory.py"), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
