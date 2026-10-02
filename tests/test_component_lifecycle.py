import importlib.util
import json
import os
import shutil
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
    def _make_dir_link(self, link: Path, destination: Path) -> None:
        if os.name == "nt":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link), str(destination)],
                check=True,
                capture_output=True,
                text=True,
            )
        else:
            link.symlink_to(destination, target_is_directory=True)

    def _replace_with_dir_link(self, path: Path, destination: Path) -> None:
        if path.exists() or path.is_symlink():
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._make_dir_link(path, destination)

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

    def _assert_loaded_writer_blocked(self, target: Path, *, mem_path=None, digest_id=None, marker: str):
        with self.assertRaisesRegex(RuntimeError, "lifecycle authority|attached|enabled|setup-complete|migration"):
            component.memory.write_atomic(
                f"blocked atomic {marker}",
                "fact",
                "workspace:alpha",
                effect_id=f"blocked-atomic-{marker}",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )

        with self.assertRaisesRegex(RuntimeError, "lifecycle authority|attached|enabled|setup-complete|migration"):
            component.memory.write_session_digest(
                f"sess-{marker}",
                f"blocked digest {marker}",
                run_id=f"run-{marker}",
                scope="workspace:alpha",
                topic=f"blocked {marker}",
                source_refs=[f"gateway:run:run-{marker}"],
                source_coverage=[f"gateway:run:run-{marker}:messages:1-2"],
                source_version="test",
                effect_id=f"blocked-digest-{marker}",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )

        if mem_path is not None:
            with self.assertRaisesRegex(RuntimeError, "lifecycle authority|attached|enabled|setup-complete|migration"):
                component.memory.update_meta(mem_path, {"tags": f"blocked-{marker}"})

        if digest_id is not None:
            with self.assertRaisesRegex(RuntimeError, "lifecycle authority|attached|enabled|setup-complete|migration"):
                component.memory.promote_session_digest(
                    digest_id,
                    [
                        {
                            "text": f"blocked promotion {marker}",
                            "type": "lesson",
                            "confidence": 0.95,
                            "admission": {
                                "durable": True,
                                "historical": True,
                                "current_truth": False,
                                "contains_secret": False,
                                "strategic": False,
                                "permission_expansion": False,
                                "privacy_ambiguous": False,
                                "external_authority": False,
                            },
                        }
                    ],
                    workspace="alpha",
                    root=target,
                    mode=component.memory.MODE_NATIVE,
                )

    def test_wsa_2026_013_loaded_native_writer_obeys_setup_disable_detach_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._native_root(Path(tmp))
            component._install_package(target, ROOT)

            # Package installation alone must not authorize canonical native writes.
            self._assert_loaded_writer_blocked(target, marker="pre-setup")

            component._setup(target, ROOT)
            mem_id, mem_path, created = component.memory.write_atomic(
                "Lifecycle-authorized canonical record",
                "fact",
                "workspace:alpha",
                effect_id="wsa-013-seed",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )
            self.assertTrue(created)
            digest_id, _, digest_created = component.memory.write_session_digest(
                "sess-wsa-013",
                "Lifecycle authority seed digest.",
                run_id="run-wsa-013",
                scope="workspace:alpha",
                topic="Lifecycle authority",
                source_refs=["gateway:run:run-wsa-013"],
                source_coverage=["gateway:run:run-wsa-013:messages:1-4"],
                source_version="test",
                effect_id="wsa-013-digest",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )
            self.assertTrue(digest_created)

            component._set_enabled(target, False)
            self._assert_loaded_writer_blocked(
                target,
                mem_path=mem_path,
                digest_id=digest_id,
                marker="disabled",
            )

            component._set_enabled(target, True)
            component._detach(target)
            self._assert_loaded_writer_blocked(
                target,
                mem_path=mem_path,
                digest_id=digest_id,
                marker="detached",
            )

            component._setup(target, ROOT)
            component._uninstall(target)
            self._assert_loaded_writer_blocked(
                target,
                mem_path=mem_path,
                digest_id=digest_id,
                marker="uninstalled",
            )

            # Reinstall without setup leaves preserved canonical data but no write authority.
            component._install_package(target, ROOT)
            self.assertEqual(component.status_payload(target)["state"], "setup-required")
            self._assert_loaded_writer_blocked(
                target,
                mem_path=mem_path,
                digest_id=digest_id,
                marker="reinstalled-pre-setup",
            )
            self.assertIsNotNone(component.memory.locate_memory(mem_id, target, component.memory.MODE_NATIVE))

    def test_wsa_2026_013_registry_supported_and_installed_flags_are_write_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = self._native_root(Path(tmp))
            component._install_package(target, ROOT)
            component._setup(target, ROOT)
            registry_path = target / ".aiverse/extensions/registry.json"

            for field in ("supported", "installed"):
                with self.subTest(field=field):
                    payload = json.loads(registry_path.read_text(encoding="utf-8"))
                    payload["extensions"]["ai-verse-memory"][field] = False
                    registry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "lifecycle authority"):
                        component.memory.write_atomic(
                            f"must fail when registry {field}=false",
                            "fact",
                            "workspace:alpha",
                            root=target,
                            mode=component.memory.MODE_NATIVE,
                        )
                    payload["extensions"]["ai-verse-memory"][field] = True
                    registry_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

            created = component.memory.write_atomic(
                "registry authority restored",
                "fact",
                "workspace:alpha",
                root=target,
                mode=component.memory.MODE_NATIVE,
            )
            self.assertTrue(created[2])

    def test_install_and_setup_reject_symlink_or_reparse_lifecycle_parents(self):
        cases = (
            ("scripts", "install"),
            ("scripts/ai-verse-memory", "install"),
            (".claude", "setup"),
            (".claude/skills", "setup"),
            (".claude/skills/ai-verse-memory", "setup"),
            (".agents", "setup"),
            (".agents/skills", "setup"),
            (".agents/skills/ai-verse-memory", "setup"),
        )
        for relative, action in cases:
            with self.subTest(relative=relative, action=action):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    target = self._native_root(base)
                    outside = base / "outside"
                    outside.mkdir()
                    sentinel = outside / "sentinel.txt"
                    sentinel.write_text("must survive", encoding="utf-8")

                    if action == "setup":
                        component._install_package(target, ROOT)

                    self._replace_with_dir_link(target / relative, outside)
                    with self.assertRaises(RuntimeError):
                        if action == "install":
                            component._install_package(target, ROOT)
                        else:
                            component._setup(target, ROOT)

                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "must survive")
                    self.assertFalse((outside / "memory.py").exists())
                    self.assertFalse((outside / "SKILL.md").exists())

    def test_uninstall_preflight_rejects_symlink_or_reparse_paths_without_external_deletion(self):
        cases = (
            "scripts",
            "scripts/ai-verse-memory",
            ".claude",
            ".claude/skills",
            ".claude/skills/ai-verse-memory",
            ".agents",
            ".agents/skills",
            ".agents/skills/ai-verse-memory",
        )
        for relative in cases:
            with self.subTest(relative=relative):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    target = self._native_root(base)
                    component._install_package(target, ROOT)
                    component._setup(target, ROOT)

                    outside = base / "outside"
                    outside.mkdir()
                    external_component = outside / "ai-verse-memory"
                    external_component.mkdir()
                    sentinel = external_component / "sentinel.txt"
                    sentinel.write_text("must survive uninstall", encoding="utf-8")

                    if relative.endswith("ai-verse-memory"):
                        destination = external_component
                    else:
                        destination = outside
                    self._replace_with_dir_link(target / relative, destination)

                    registry_before = (target / ".aiverse" / "extensions" / "registry.json").read_bytes()
                    with self.assertRaises(RuntimeError):
                        component._uninstall(target)

                    self.assertEqual(sentinel.read_text(encoding="utf-8"), "must survive uninstall")
                    self.assertEqual(
                        (target / ".aiverse" / "extensions" / "registry.json").read_bytes(),
                        registry_before,
                    )

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
            with self.assertRaisesRegex(RuntimeError, "migration"):
                component.memory.write_atomic(
                    "ordinary write must wait for authority handoff",
                    "fact",
                    "workspace:alpha",
                    root=target,
                    mode=component.memory.MODE_NATIVE,
                )
            planned = component.memory.migrate_legacy(target, apply=False)
            self.assertEqual(planned["migratable"], 1)

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
