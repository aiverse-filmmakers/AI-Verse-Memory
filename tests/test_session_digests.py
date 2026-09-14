import importlib.util
import inspect
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "scripts" / "memory.py"


def load_memory(name="ai_verse_memory_session_digest_tests"):
    spec = importlib.util.spec_from_file_location(name, MEMORY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mem = load_memory()


class SessionDigestTests(unittest.TestCase):
    def _native_root(self, base: Path) -> Path:
        root = base / "os"
        root.mkdir()
        (root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\n',
            encoding="utf-8",
        )
        (root / "operator").mkdir()
        for workspace in ("alpha", "beta"):
            owner = root / "workspaces" / workspace
            owner.mkdir(parents=True)
            (owner / "WORKSPACE.yaml").write_text(
                f"id: {workspace}\nname: {workspace.title()}\ntype: test\nstatus: active\npurpose: digest tests\n",
                encoding="utf-8",
            )
        return root

    def _write_alpha(self, root: Path, **overrides):
        args = {
            "session_id": "sess-alpha-42",
            "run_id": "run-alpha-42",
            "scope": "workspace:alpha",
            "topic": "Release gate follow-up",
            "summary": "Verified the release candidate and identified one remaining validation task.",
            "significant_outcomes": ["Candidate manifest verified", "No ownership violation found"],
            "unresolved_items": ["Run final validation workflow"],
            "source_refs": ["gateway:session:sess-alpha-42", "gateway:run:run-alpha-42"],
            "source_coverage": ["message:1-18", "run:event:complete"],
            "source_fingerprint": "sha256:source-alpha",
            "source_version": "gateway-run-v1",
            "provenance": {"owner": "ai-verse-gateway", "kind": "completed_session"},
            "completed_at": "2026-09-14T10:00:00+00:00",
            "effect_id": "digest-effect-alpha-42",
            "root": root,
            "mode": mem.MODE_NATIVE,
        }
        args.update(overrides)
        return mem.write_session_digest(**args)

    def test_api_is_compact_and_does_not_accept_raw_transcript_fields(self):
        params = inspect.signature(mem.write_session_digest).parameters
        self.assertNotIn("messages", params)
        self.assertNotIn("transcript", params)

        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            with self.assertRaises(TypeError):
                mem.write_session_digest(
                    "sess-x",
                    "Compact handoff",
                    scope="workspace:alpha",
                    topic="Test",
                    transcript="User: raw transcript that Memory must not own",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_native_digest_persists_compact_metadata_and_restarts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, path, created = self._write_alpha(root)

            self.assertTrue(created)
            self.assertTrue(digest_id.startswith("sdg-"))
            self.assertIn("workspaces/alpha/memory/session-digests", path.as_posix())
            self.assertNotIn("/atomic/", path.as_posix())

            raw = path.read_text(encoding="utf-8")
            self.assertIn("Candidate manifest verified", raw)
            self.assertNotIn("User:", raw)
            self.assertNotIn("Assistant:", raw)

            record = mem.read_session_digest(
                digest_id,
                scope="workspace:alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(record["session_id"], "sess-alpha-42")
            self.assertEqual(record["run_id"], "run-alpha-42")
            self.assertEqual(record["scope"], "workspace:alpha")
            self.assertEqual(record["topic"], "Release gate follow-up")
            self.assertEqual(record["source_refs"], [
                "gateway:session:sess-alpha-42",
                "gateway:run:run-alpha-42",
            ])
            self.assertEqual(record["source_coverage"], ["message:1-18", "run:event:complete"])
            self.assertEqual(record["source_fingerprint"], "sha256:source-alpha")
            self.assertEqual(record["source_version"], "gateway-run-v1")
            self.assertEqual(record["provenance"]["owner"], "ai-verse-gateway")
            self.assertEqual(record["unresolved_items"], ["Run final validation workflow"])

            restarted = load_memory("ai_verse_memory_session_digest_restart")
            after_restart = restarted.read_session_digest(
                digest_id,
                scope="workspace:alpha",
                root=root,
                mode=restarted.MODE_NATIVE,
            )
            self.assertEqual(after_restart["digest_fingerprint"], record["digest_fingerprint"])
            self.assertEqual(after_restart["summary"], record["summary"])

    def test_effect_replay_is_idempotent_and_changed_payload_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            first_id, first_path, created = self._write_alpha(root)
            self.assertTrue(created)

            second_id, second_path, created_again = self._write_alpha(root)
            self.assertFalse(created_again)
            self.assertEqual(first_id, second_id)
            self.assertEqual(first_path, second_path)

            with self.assertRaises(RuntimeError):
                self._write_alpha(
                    root,
                    summary="Changed content under the same durable effect id.",
                )

            files = list((root / "workspaces/alpha/memory/session-digests").rglob("sdg-*.md"))
            self.assertEqual(len(files), 1)

    def test_immutable_identity_rejects_changed_content_without_effect_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, _, created = self._write_alpha(root, effect_id="")
            self.assertTrue(created)

            replay_id, _, replay_created = self._write_alpha(root, effect_id="")
            self.assertEqual(replay_id, digest_id)
            self.assertFalse(replay_created)

            with self.assertRaisesRegex(RuntimeError, "identity already exists with different content"):
                self._write_alpha(
                    root,
                    effect_id="",
                    significant_outcomes=["Different outcome"],
                )

    def test_workspace_listing_is_strictly_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            alpha_id, _, _ = self._write_alpha(root)
            beta_id, _, _ = mem.write_session_digest(
                "sess-beta-7",
                "Beta private research summary.",
                run_id="run-beta-7",
                scope="workspace:beta",
                topic="Private beta research",
                source_refs=["gateway:session:sess-beta-7"],
                source_version="gateway-run-v1",
                effect_id="digest-effect-beta-7",
                root=root,
                mode=mem.MODE_NATIVE,
            )

            alpha = mem.list_session_digests(
                scope="workspace:alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            beta = mem.list_session_digests(
                scope="workspace:beta",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([item["id"] for item in alpha], [alpha_id])
            self.assertEqual([item["id"] for item in beta], [beta_id])
            self.assertNotIn("Beta private", json.dumps(alpha))
            self.assertNotIn("Candidate manifest", json.dumps(beta))

            with self.assertRaises(FileNotFoundError):
                mem.read_session_digest(
                    beta_id,
                    scope="workspace:alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_native_digest_write_rejects_symlinked_memory_parent(self):
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
                self._write_alpha(root)
            self.assertEqual(list(outside.rglob("*.md")), [])

    def test_digest_directory_symlink_is_rejected_on_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = self._native_root(base)
            memory_dir = root / "workspaces" / "alpha" / "memory"
            memory_dir.mkdir()
            (memory_dir / "atomic").mkdir()
            outside = base / "outside"
            outside.mkdir()
            digest_dir = memory_dir / "session-digests"
            try:
                digest_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            with self.assertRaises(RuntimeError):
                self._write_alpha(root)
            self.assertEqual(list(outside.rglob("*.md")), [])

    def test_standalone_scope_is_hashed_and_cannot_escape_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "standalone"
            root.mkdir()
            os.environ["AI_VERSE_MEMORY_HOME"] = str(root / ".ai-verse-memory")
            try:
                digest_id, path, created = mem.write_session_digest(
                    "sess-standalone",
                    "Compact standalone digest.",
                    scope="../../outside",
                    topic="Standalone path safety",
                    source_refs=["session:sess-standalone"],
                    source_version="v1",
                    effect_id="standalone-digest-1",
                    root=root,
                    mode=mem.MODE_STANDALONE,
                )
                self.assertTrue(created)
                home = (root / ".ai-verse-memory").resolve()
                path.resolve().relative_to(home)
                self.assertNotIn("..", path.relative_to(home).parts)
                record = mem.read_session_digest(
                    digest_id,
                    scope="../../outside",
                    root=root,
                    mode=mem.MODE_STANDALONE,
                )
                self.assertEqual(record["scope"], "../../outside")
            finally:
                os.environ.pop("AI_VERSE_MEMORY_HOME", None)

    def test_digest_requires_authoritative_source_reference_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            with self.assertRaisesRegex(ValueError, "source_refs must contain"):
                mem.write_session_digest(
                    "sess-no-source",
                    "A digest without source evidence must not be accepted.",
                    scope="workspace:alpha",
                    topic="Missing source",
                    source_refs=[],
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
            with self.assertRaisesRegex(ValueError, "source_coverage must contain"):
                mem.write_session_digest(
                    "sess-no-coverage",
                    "A digest with empty explicit coverage must not be accepted.",
                    scope="workspace:alpha",
                    topic="Missing coverage",
                    source_refs=["gateway:session:sess-no-coverage"],
                    source_coverage=[],
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_bounds_reject_transcript_sized_digest_instead_of_silently_truncating(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            with self.assertRaisesRegex(ValueError, "summary exceeds"):
                self._write_alpha(root, summary="x" * 6001)


if __name__ == "__main__":
    unittest.main()
