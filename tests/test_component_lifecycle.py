import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_component_tests", ROOT / "scripts" / "component.py")
component = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(component)


class ComponentLifecycleAcceptanceTests(unittest.TestCase):
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
            "id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: lifecycle acceptance\n",
            encoding="utf-8",
        )
        return root

    def test_install_setup_disable_update_enable_uninstall_reinstall_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._native_root(Path(tmp))

            installed = component._install_package(target, ROOT)
            self.assertEqual(installed["state"], "setup-required")
            self.assertTrue(installed["installed"])
            self.assertFalse(installed["attached"])
            self.assertFalse((target / ".aiverse/extensions/registry.json").exists())

            setup = component._setup(target, ROOT)
            self.assertEqual(setup["state"], "ready")
            self.assertTrue(setup["readiness"])
            self.assertTrue(setup["attached"])

            mem_id, mem_path, created = component.memory.write_atomic(
                "canonical state survives lifecycle",
                "experience",
                "workspace:alpha",
                effect_id="lifecycle-preserve",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )
            self.assertTrue(created)
            self.assertTrue(mem_path.exists())

            disabled = component._set_enabled(target, False)
            self.assertEqual(disabled["state"], "disabled")
            updated = component._update(target, ROOT)
            self.assertEqual(updated["state"], "disabled")
            self.assertFalse(updated["enabled"])

            enabled = component._set_enabled(target, True)
            self.assertEqual(enabled["state"], "ready")

            before_doctor = {
                path.relative_to(target).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in target.rglob("*")
                if path.is_file()
            }
            doctor = component.doctor_payload(target)
            after_doctor = {
                path.relative_to(target).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
                for path in target.rglob("*")
                if path.is_file()
            }
            self.assertEqual(doctor["doctor"], "PASS")
            self.assertTrue(doctor["readiness"])
            self.assertEqual(before_doctor, after_doctor)

            uninstalled = component._uninstall(target)
            self.assertEqual(uninstalled["state"], "absent")
            self.assertTrue(uninstalled["preserved_state"])
            self.assertTrue(mem_path.exists())
            self.assertIsNotNone(component.memory.locate_memory(mem_id, target, component.memory.MODE_NATIVE))
            registry = json.loads((target / ".aiverse/extensions/registry.json").read_text(encoding="utf-8"))
            self.assertNotIn("ai-verse-memory", registry["extensions"])

            reinstalled = component._install_package(target, ROOT)
            self.assertEqual(reinstalled["state"], "setup-required")
            self.assertTrue(mem_path.exists())

            reconciled = component._reconcile(target, ROOT)
            self.assertEqual(reconciled["state"], "ready")
            self.assertTrue(reconciled["readiness"])
            self.assertIsNotNone(component.memory.locate_memory(mem_id, target, component.memory.MODE_NATIVE))

    def test_structured_json_status_and_doctor(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._native_root(Path(tmp))
            component._install_package(target, ROOT)
            component._setup(target, ROOT)

            status_run = subprocess.run(
                [
                    component.sys.executable,
                    str(ROOT / "scripts" / "component.py"),
                    "--target",
                    str(target),
                    "--source-dir",
                    str(ROOT),
                    "--json",
                    "status",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            status = json.loads(status_run.stdout)
            self.assertEqual(status["component"], "ai-verse-memory")
            self.assertEqual(status["state"], "ready")
            self.assertTrue(status["readiness"])
            self.assertIn("supported_commands", status)

            doctor_run = subprocess.run(
                [
                    component.sys.executable,
                    str(ROOT / "scripts" / "component.py"),
                    "--target",
                    str(target),
                    "--source-dir",
                    str(ROOT),
                    "--json",
                    "doctor",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            doctor = json.loads(doctor_run.stdout)
            self.assertEqual(doctor["doctor"], "PASS")
            self.assertEqual(doctor["health_depth"]["operational"], "checked-read-only")
            self.assertEqual(doctor["health_depth"]["system_composed"], "not-checked")

    def test_setup_detects_legacy_without_silent_authority_transfer(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._native_root(Path(tmp))
            legacy = target / ".ai-verse-memory" / "memories" / "2026" / "09"
            legacy.mkdir(parents=True)
            old = legacy / "mem-old.md"
            old.write_text(
                "---\n"
                "id: mem-old\n"
                "type: fact\n"
                "scope: global\n"
                "status: active\n"
                "created_at: 2026-09-01T00:00:00+00:00\n"
                "---\n\n"
                "# Memory\n\nold canonical route\n",
                encoding="utf-8",
            )
            before = old.read_bytes()
            component._install_package(target, ROOT)
            setup = component._setup(target, ROOT)
            self.assertEqual(setup["state"], "migration-required")
            self.assertTrue(setup["migration_required"])
            self.assertEqual(old.read_bytes(), before)
            self.assertFalse((target / ".ai-verse-memory" / "AUTHORITY.json").exists())
            self.assertFalse(
                (target / "operator" / "memory" / ".ai-verse-memory-state" / "authority-handoff.json").exists()
            )

    def test_status_is_non_destructive_on_empty_standalone_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "empty"
            target.mkdir()
            before = list(target.iterdir())
            payload = component.status_payload(target)
            after = list(target.iterdir())
            self.assertEqual(payload["state"], "absent")
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
