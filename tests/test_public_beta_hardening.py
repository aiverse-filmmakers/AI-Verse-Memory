import concurrent.futures
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_public_beta_tests", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


class PublicBetaHardeningTests(unittest.TestCase):
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
            "id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: public beta acceptance\n",
            encoding="utf-8",
        )
        return root

    def _standalone_root(self, base: Path) -> Path:
        root = base / "old-agent"
        root.mkdir()
        mem.ensure_layout(root, mem.MODE_STANDALONE)
        return root

    def test_native_write_rejects_symlinked_workspace_memory_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._native_root(base)
            outside = base / "outside"
            outside.mkdir()
            memory_dir = root / "workspaces" / "alpha" / "memory"
            try:
                memory_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            with self.assertRaises(RuntimeError):
                mem.write_atomic(
                    "must not escape",
                    "fact",
                    "workspace:alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
            self.assertEqual(list(outside.rglob("*.md")), [])

    def test_native_write_rejects_symlinked_operator_memory_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._native_root(base)
            outside = base / "outside"
            outside.mkdir()
            memory_dir = root / "operator" / "memory"
            try:
                memory_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            with self.assertRaises(RuntimeError):
                mem.write_atomic("must not escape", "fact", "operator", root=root, mode=mem.MODE_NATIVE)
            self.assertEqual(list(outside.rglob("*.md")), [])

    def test_effect_id_is_durable_and_learning_evidence_stays_historical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            first_id, first_path, created = mem.write_atomic(
                "Retrying a failed render with bounded backoff succeeded.",
                "lesson",
                "workspace:alpha",
                source="run:render-42",
                evidence_refs=["receipt:42", "artifact:render-42"],
                effect_id="learning-effect-42",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertTrue(created)
            second_id, second_path, created_again = mem.write_atomic(
                "Retrying a failed render with bounded backoff succeeded.",
                "lesson",
                "workspace:alpha",
                source="run:render-42",
                evidence_refs=["receipt:42", "artifact:render-42"],
                effect_id="learning-effect-42",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertFalse(created_again)
            self.assertEqual(first_id, second_id)
            self.assertEqual(first_path, second_path)
            meta, _ = mem.parse_markdown(first_path)
            self.assertEqual(meta["type"], "lesson")
            self.assertIn("receipt:42", meta["evidence_refs"])
            self.assertEqual(meta["source"], "run:render-42")

            with self.assertRaises(RuntimeError):
                mem.write_atomic(
                    "Different effect body",
                    "lesson",
                    "workspace:alpha",
                    effect_id="learning-effect-42",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_concurrent_writers_are_serialized_without_losing_memories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))

            def write(index: int):
                return mem.write_atomic(
                    f"concurrent canonical memory {index}",
                    "experience",
                    "workspace:alpha",
                    effect_id=f"concurrent-{index}",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(write, range(8)))

            self.assertEqual(len({item[0] for item in results}), 8)
            rows = mem.recall(
                "concurrent canonical memory",
                workspace="alpha",
                limit=20,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            ids = {row["id"] for row in rows}
            self.assertTrue({item[0] for item in results}.issubset(ids))

    def test_mutation_wait_timeout_tracks_queue_progress_not_total_queue_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            original_wait = mem._public_beta.LOCK_WAIT_SECONDS
            mem._public_beta.LOCK_WAIT_SECONDS = 0.30
            import threading
            barrier = threading.Barrier(3)

            def hold(index: int):
                barrier.wait()
                with mem.public_beta_mutation_lock(root, mem.MODE_NATIVE):
                    time.sleep(0.20)
                    return index

            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    results = list(pool.map(hold, range(3)))
            finally:
                mem._public_beta.LOCK_WAIT_SECONDS = original_wait

            self.assertEqual(sorted(results), [0, 1, 2])

    def test_stale_mutation_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            state = root / "operator" / "memory" / ".ai-verse-memory-state"
            state.mkdir(parents=True)
            lock = state / "mutation.lock"
            lock.write_text(
                json.dumps({"schema_version": 1, "pid": 999999999, "created_at": "2000-01-01T00:00:00+00:00"}) + "\n",
                encoding="utf-8",
            )
            old = time.time() - 3600
            os.utime(lock, (old, old))
            mem_id, _, created = mem.write_atomic(
                "stale lock recovery",
                "fact",
                "operator",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertTrue(created)
            self.assertTrue(mem_id.startswith("mem-"))
            self.assertFalse(lock.exists())

    def test_external_migration_detects_drift_fixes_blank_provenance_and_retires_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._standalone_root(base)
            target = self._native_root(base)

            mem_id, old_path, created = mem.write_atomic(
                "pre-OS historical lesson",
                "lesson",
                "project:alpha",
                source="",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            self.assertTrue(created)
            legacy_writer = source / ".ai-verse-memory" / "memory.py"
            legacy_writer.write_text("print('legacy writer')\n", encoding="utf-8")

            dry = mem.migrate_legacy(target, apply=False, source_root=source)
            self.assertEqual(dry["migratable"], 1)
            self.assertEqual(dry["handoff_complete"], 0)

            # Source changes after review must invalidate apply.
            original_text = old_path.read_text(encoding="utf-8")
            old_path.write_text(original_text.replace("historical lesson", "historical lesson changed"), encoding="utf-8")
            with self.assertRaises(ValueError):
                mem.migrate_legacy(target, apply=True, source_root=source)

            # Review the changed source and apply that exact snapshot.
            mem.migrate_legacy(target, apply=False, source_root=source)
            source_memory_before = old_path.read_bytes()
            applied = mem.migrate_legacy(target, apply=True, source_root=source)
            self.assertEqual(applied["copied"], 1)
            self.assertEqual(applied["handoff_complete"], 1)
            self.assertEqual(old_path.read_bytes(), source_memory_before)

            new_path = mem.locate_memory(mem_id, target, mem.MODE_NATIVE)
            self.assertIsNotNone(new_path)
            meta, body = mem.parse_markdown(new_path)
            self.assertEqual(meta["scope"], "workspace:alpha")
            self.assertTrue(meta["source"].startswith("legacy:"))
            self.assertIn("migration_source_sha256", meta)
            self.assertIn("historical lesson changed", body)

            authority = json.loads((source / ".ai-verse-memory" / "AUTHORITY.json").read_text(encoding="utf-8"))
            self.assertEqual(authority["status"], "retired")
            handoff = json.loads(
                (target / "operator" / "memory" / ".ai-verse-memory-state" / "authority-handoff.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(handoff["status"], "complete")
            self.assertEqual(handoff["handoff_id"], authority["handoff_id"])
            self.assertIn("retired after canonical authority handoff", legacy_writer.read_text(encoding="utf-8"))

            with self.assertRaises(RuntimeError):
                mem.write_atomic(
                    "old writer must remain retired",
                    "fact",
                    "global",
                    root=source,
                    mode=mem.MODE_STANDALONE,
                )

            mem.migration_complete("verified handoff", target, mem.MODE_NATIVE)
            marker = json.loads(
                (target / "operator" / "memory" / ".ai-verse-memory-state" / "migration.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(marker["summary"], "verified handoff")

    def test_unresolved_migration_never_retires_old_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = self._standalone_root(base)
            target = self._native_root(base)
            mem.write_atomic(
                "unknown project memory",
                "fact",
                "project:does-not-exist",
                root=source,
                mode=mem.MODE_STANDALONE,
            )
            mem.migrate_legacy(target, apply=False, source_root=source)
            applied = mem.migrate_legacy(target, apply=True, source_root=source)
            self.assertEqual(applied["unresolved"], 1)
            self.assertEqual(applied["handoff_complete"], 0)
            self.assertFalse((source / ".ai-verse-memory" / "AUTHORITY.json").exists())
            self.assertFalse(
                (target / "operator" / "memory" / ".ai-verse-memory-state" / "authority-handoff.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
