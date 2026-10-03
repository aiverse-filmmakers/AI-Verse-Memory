import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from tests.native_lifecycle_fixture import mark_native_ready

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ai_verse_memory_handoff_atomicity",
    ROOT / "scripts" / "memory.py",
)
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class MigrationHandoffAtomicityTests(unittest.TestCase):
    STAGES = (
        "after-target-prepared",
        "after-source-retiring",
        "after-target-pending",
        "after-writer-fenced",
        "after-source-retired",
        "after-target-complete",
    )

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
            'id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: handoff atomicity test\n',
            encoding="utf-8",
        )
        mem.ensure_layout(root, mem.MODE_NATIVE)
        mark_native_ready(root, mem)
        return root

    def _standalone_root(self, base: Path) -> Path:
        root = base / "standalone"
        root.mkdir()
        mem.ensure_layout(root, mem.MODE_STANDALONE)
        return root

    def _setup(self, base: Path):
        source = self._standalone_root(base)
        target = self._native_root(base)
        mem_id, source_memory, created = mem.write_atomic(
            "pre-OS handoff atomicity memory",
            "fact",
            "global",
            source="standalone:wsa-014",
            root=source,
            mode=mem.MODE_STANDALONE,
        )
        self.assertTrue(created)
        writer = source / ".ai-verse-memory" / "memory.py"
        writer.write_text("print('legacy writer remains active')\n", encoding="utf-8")
        dry = mem.migrate_legacy(target, apply=False, source_root=source)
        self.assertEqual(dry["migratable"], 1)
        return source, target, mem_id, source_memory, writer

    def _target_normal_writable(self, target: Path) -> bool:
        try:
            mem.public_beta_assert_writable_authority(target, mem.MODE_NATIVE)
            return True
        except RuntimeError:
            return False

    def _legacy_executable_writable(self, source: Path, writer: Path) -> bool:
        authority_path = source / ".ai-verse-memory" / "AUTHORITY.json"
        authority = {}
        if authority_path.exists():
            authority = json.loads(authority_path.read_text(encoding="utf-8"))
        if authority.get("status") == "retired":
            return False
        if not writer.exists():
            return False
        body = writer.read_text(encoding="utf-8")
        return "Retired AI-Verse Memory standalone writer" not in body

    def _inject(self, stage: str):
        def fail(current: str):
            if current == stage:
                raise RuntimeError(f"injected handoff fault: {stage}")

        return fail

    def test_fault_at_every_cross_root_transition_preserves_singular_authority_and_recovers(self):
        for stage in self.STAGES:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                source, target, mem_id, source_memory, writer = self._setup(Path(tmp))
                source_bytes = source_memory.read_bytes()
                mem._public_beta._HANDOFF_FAULT_INJECTOR = self._inject(stage)
                try:
                    with self.assertRaisesRegex(RuntimeError, f"injected handoff fault: {stage}"):
                        mem.migrate_legacy(target, apply=True, source_root=source)
                finally:
                    mem._public_beta._HANDOFF_FAULT_INJECTOR = None

                target_writable = self._target_normal_writable(target)
                source_writable = self._legacy_executable_writable(source, writer)
                self.assertLessEqual(
                    int(target_writable) + int(source_writable),
                    1,
                    f"two writable canonical routes after {stage}",
                )
                if stage != "after-target-complete":
                    self.assertFalse(target_writable, f"target published write authority too early at {stage}")

                native_authority = mem.public_beta_authority_file(target, mem.MODE_NATIVE)
                self.assertTrue(native_authority.exists())
                first = json.loads(native_authority.read_text(encoding="utf-8"))
                handoff_id = first["handoff_id"]

                recovered = mem.migrate_legacy(target, apply=True, source_root=source)
                self.assertEqual(recovered["handoff_complete"], 1)
                self.assertEqual(source_memory.read_bytes(), source_bytes)
                self.assertIsNotNone(mem.locate_memory(mem_id, target, mem.MODE_NATIVE))

                complete = json.loads(native_authority.read_text(encoding="utf-8"))
                source_authority = json.loads(
                    (source / ".ai-verse-memory" / "AUTHORITY.json").read_text(encoding="utf-8")
                )
                self.assertEqual(complete["status"], "complete")
                self.assertIs(complete["source_retirement_verified"], True)
                self.assertEqual(complete["handoff_id"], handoff_id)
                self.assertEqual(source_authority["status"], "retired")
                self.assertEqual(source_authority["handoff_id"], handoff_id)
                self.assertFalse(self._legacy_executable_writable(source, writer))
                self.assertTrue((source / ".ai-verse-memory" / "memory.py.pre-handoff").exists())
                self.assertTrue(self._target_normal_writable(target))

                replay = mem.migrate_legacy(target, apply=True, source_root=source)
                self.assertEqual(replay["handoff_complete"], 1)
                replay_receipt = json.loads(native_authority.read_text(encoding="utf-8"))
                self.assertEqual(replay_receipt["handoff_id"], handoff_id)
                self.assertIs(replay_receipt["source_retirement_verified"], True)

    def test_prepared_crash_allows_reviewed_replan_if_source_changes_before_fencing(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, _, _, _ = self._setup(Path(tmp))
            mem._public_beta._HANDOFF_FAULT_INJECTOR = self._inject("after-target-prepared")
            try:
                with self.assertRaisesRegex(RuntimeError, "injected handoff fault: after-target-prepared"):
                    mem.migrate_legacy(target, apply=True, source_root=source)
            finally:
                mem._public_beta._HANDOFF_FAULT_INJECTOR = None

            native_authority = mem.public_beta_authority_file(target, mem.MODE_NATIVE)
            stale = json.loads(native_authority.read_text(encoding="utf-8"))
            stale_handoff_id = stale["handoff_id"]
            self.assertEqual(stale["status"], "prepared")
            self.assertFalse(self._target_normal_writable(target))
            self.assertFalse((source / ".ai-verse-memory" / "AUTHORITY.json").exists())

            _, _, created = mem.write_atomic(
                "source changed after target-only prepared crash",
                "fact",
                "global",
                source="standalone:wsa-014-replan",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            self.assertTrue(created)

            replanned = mem.migrate_legacy(target, apply=False, source_root=source)
            self.assertEqual(replanned["migratable"], 1)
            recovered = mem.migrate_legacy(target, apply=True, source_root=source)
            self.assertEqual(recovered["handoff_complete"], 1)

            final = json.loads(native_authority.read_text(encoding="utf-8"))
            self.assertEqual(final["status"], "complete")
            self.assertIs(final["source_retirement_verified"], True)
            self.assertNotEqual(final["handoff_id"], stale_handoff_id)
            self.assertEqual(final["replaced_prepared_handoff_id"], stale_handoff_id)
            source_authority = json.loads(
                (source / ".ai-verse-memory" / "AUTHORITY.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_authority["handoff_id"], final["handoff_id"])
            self.assertEqual(source_authority["status"], "retired")
            self.assertTrue(self._target_normal_writable(target))

    def test_old_premature_complete_receipt_is_fenced_and_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target, _, _, writer = self._setup(Path(tmp))
            plan_path = target / "operator" / "memory" / "migrations" / "legacy-ai-verse-memory-plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            handoff_id = "handoff-" + hashlib.sha256(
                (plan["source_fingerprint"] + "\n" + str(target.resolve())).encode("utf-8")
            ).hexdigest()[:24]
            old_receipt = {
                "schema_version": 1,
                "handoff_id": handoff_id,
                "status": "complete",
                "completed_at": "2026-09-15T00:00:00+00:00",
                "source_root": plan["source_root"],
                "legacy_root": plan["legacy_root"],
                "source_fingerprint": plan["source_fingerprint"],
                "target_root": str(target.resolve()),
                "target_scope_fingerprint": plan["target_scope_fingerprint"],
                "counts": {"migratable": 1, "copied": 1},
            }
            native_authority = mem.public_beta_authority_file(target, mem.MODE_NATIVE)
            mem.public_beta_atomic_write_json(native_authority, old_receipt)

            self.assertFalse(self._target_normal_writable(target))
            self.assertTrue(self._legacy_executable_writable(source, writer))

            recovered = mem.migrate_legacy(target, apply=True, source_root=source)
            self.assertEqual(recovered["handoff_complete"], 1)
            receipt = json.loads(native_authority.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "complete")
            self.assertIs(receipt["source_retirement_verified"], True)
            self.assertEqual(receipt["handoff_id"], handoff_id)
            self.assertIs(receipt["recovered_from_unverified_complete"], True)
            source_authority = json.loads(
                (source / ".ai-verse-memory" / "AUTHORITY.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source_authority["status"], "retired")
            self.assertEqual(source_authority["handoff_id"], handoff_id)
            self.assertFalse(self._legacy_executable_writable(source, writer))
            self.assertTrue(self._target_normal_writable(target))


if __name__ == "__main__":
    unittest.main()
