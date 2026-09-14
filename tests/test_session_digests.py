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


class SessionDigestIndexTests(unittest.TestCase):
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
                f"id: {workspace}\nname: {workspace.title()}\ntype: test\nstatus: active\npurpose: digest index tests\n",
                encoding="utf-8",
            )
        return root

    def _digest(
        self,
        root: Path,
        *,
        session_id: str,
        run_id: str,
        scope: str,
        topic: str,
        summary: str,
        completed_at: str,
        effect_id: str,
    ):
        return mem.write_session_digest(
            session_id,
            summary,
            run_id=run_id,
            scope=scope,
            topic=topic,
            significant_outcomes=[f"Outcome for {session_id}"],
            unresolved_items=[f"Follow-up for {session_id}"],
            source_refs=[f"gateway:session:{session_id}", f"gateway:run:{run_id}"],
            source_coverage=[f"gateway:session:{session_id}:messages:1-10"],
            source_fingerprint=f"sha256:{session_id}",
            source_version="gateway-run-v1",
            provenance={"owner": "ai-verse-gateway", "session": session_id},
            completed_at=completed_at,
            effect_id=effect_id,
            root=root,
            mode=mem.MODE_NATIVE,
        )

    def test_targeted_recall_ranks_relevant_recent_digests_without_cross_workspace_leakage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            older_id, _, _ = self._digest(
                root,
                session_id="sess-alpha-old",
                run_id="run-alpha-old",
                scope="workspace:alpha",
                topic="Render pipeline review",
                summary="The render pipeline used the legacy retry policy.",
                completed_at="2026-01-10T10:00:00+00:00",
                effect_id="digest-alpha-old",
            )
            newer_id, _, _ = self._digest(
                root,
                session_id="sess-alpha-new",
                run_id="run-alpha-new",
                scope="workspace:alpha",
                topic="Render pipeline stabilization",
                summary="The render pipeline stabilized after bounded retry changes.",
                completed_at="2026-09-13T10:00:00+00:00",
                effect_id="digest-alpha-new",
            )
            beta_id, _, _ = self._digest(
                root,
                session_id="sess-beta-private",
                run_id="run-beta-private",
                scope="workspace:beta",
                topic="Render pipeline confidential beta",
                summary="Beta uses a private render pipeline configuration.",
                completed_at="2026-09-14T09:00:00+00:00",
                effect_id="digest-beta-private",
            )

            rows = mem.recall_session_digests(
                "render pipeline",
                workspace="alpha",
                limit=10,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            ids = [row["id"] for row in rows]
            self.assertIn(newer_id, ids)
            self.assertIn(older_id, ids)
            self.assertNotIn(beta_id, ids)
            self.assertLess(ids.index(newer_id), ids.index(older_id))
            self.assertTrue(all(row["scope"] != "workspace:beta" for row in rows))

    def test_digest_index_rebuilds_losslessly_after_shared_db_deletion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            atomic_id, _, _ = mem.write_atomic(
                "Alpha atomic memory must survive derived DB recreation.",
                "fact",
                "workspace:alpha",
                source="unit-test",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            digest_id, _, _ = self._digest(
                root,
                session_id="sess-rebuild",
                run_id="run-rebuild",
                scope="workspace:alpha",
                topic="Database rebuild evidence",
                summary="Session digest remains canonical outside the disposable SQLite projection.",
                completed_at="2026-09-14T10:00:00+00:00",
                effect_id="digest-rebuild",
            )

            self.assertEqual(
                mem.rebuild_session_digest_index(root=root, mode=mem.MODE_NATIVE),
                1,
            )
            first = mem.recall_session_digests(
                "disposable SQLite",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in first], [digest_id])

            db = mem.paths(root, mem.MODE_NATIVE)["db"]
            db.unlink()
            rebuilt = mem.rebuild_session_digest_index(root=root, mode=mem.MODE_NATIVE)
            self.assertEqual(rebuilt, 1)

            after = mem.recall_session_digests(
                "disposable SQLite",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in after], [digest_id])

            legacy = mem.recall(
                "atomic memory survive",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertTrue(any(row["id"] == atomic_id for row in legacy))

    def test_missing_canonical_digest_is_purged_from_derived_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, path, _ = self._digest(
                root,
                session_id="sess-delete",
                run_id="run-delete",
                scope="workspace:alpha",
                topic="Deletion freshness",
                summary="This digest should disappear when its canonical file disappears.",
                completed_at="2026-09-14T10:00:00+00:00",
                effect_id="digest-delete",
            )
            initial = mem.recall_session_digests(
                "canonical file disappears",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in initial], [digest_id])

            path.unlink()
            after = mem.recall_session_digests(
                "canonical file disappears",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(after, [])

            import sqlite3

            conn = sqlite3.connect(mem.paths(root, mem.MODE_NATIVE)["db"])
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM session_digest_items WHERE id=?",
                    (digest_id,),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 0)

    def test_changed_canonical_digest_refreshes_stale_derived_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, path, _ = self._digest(
                root,
                session_id="sess-refresh",
                run_id="run-refresh",
                scope="workspace:alpha",
                topic="Freshness refresh",
                summary="Original lighthouse phrase should be indexed.",
                completed_at="2026-09-14T10:00:00+00:00",
                effect_id="digest-refresh",
            )
            first = mem.recall_session_digests(
                "lighthouse",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in first], [digest_id])

            raw = path.read_text(encoding="utf-8")
            path.write_text(
                raw.replace(
                    "Original lighthouse phrase should be indexed.",
                    "Replacement observatory phrase should be indexed.",
                ),
                encoding="utf-8",
            )

            stale = mem.recall_session_digests(
                "lighthouse",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            fresh = mem.recall_session_digests(
                "observatory",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(stale, [])
            self.assertEqual([row["id"] for row in fresh], [digest_id])
            self.assertIn("observatory", fresh[0]["summary"])

    def test_legacy_recall_does_not_return_session_digest_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            mem.write_atomic(
                "Zeppelin is an atomic historical fact.",
                "fact",
                "workspace:alpha",
                source="unit-test",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            digest_id, _, _ = self._digest(
                root,
                session_id="sess-zeppelin",
                run_id="run-zeppelin",
                scope="workspace:alpha",
                topic="Zeppelin session",
                summary="Zeppelin also appears in a session digest.",
                completed_at="2026-09-14T10:00:00+00:00",
                effect_id="digest-zeppelin",
            )
            targeted = mem.recall_session_digests(
                "zeppelin",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in targeted], [digest_id])

            legacy = mem.recall(
                "zeppelin",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertTrue(legacy)
            self.assertTrue(all(row["kind"] != "session_digest" for row in legacy))
            self.assertFalse(any(row["id"] == digest_id for row in legacy))

    def test_standalone_digest_index_recovers_hashed_scope_without_scope_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "standalone"
            root.mkdir()
            os.environ["AI_VERSE_MEMORY_HOME"] = str(root / ".ai-verse-memory")
            try:
                digest_id, _, _ = mem.write_session_digest(
                    "sess-standalone-index",
                    "Standalone historical session mentions a cobalt workflow.",
                    run_id="run-standalone-index",
                    scope="project:blue",
                    topic="Cobalt workflow",
                    source_refs=["gateway:session:sess-standalone-index"],
                    source_coverage=["gateway:session:sess-standalone-index:messages:1-5"],
                    source_version="v1",
                    effect_id="standalone-index",
                    root=root,
                    mode=mem.MODE_STANDALONE,
                )
                self.assertEqual(
                    mem.rebuild_session_digest_index(
                        root=root,
                        mode=mem.MODE_STANDALONE,
                    ),
                    1,
                )
                rows = mem.recall_session_digests(
                    "cobalt",
                    scope="project:blue",
                    root=root,
                    mode=mem.MODE_STANDALONE,
                )
                self.assertEqual([row["id"] for row in rows], [digest_id])
            finally:
                os.environ.pop("AI_VERSE_MEMORY_HOME", None)


class SessionDigestPromotionTests(unittest.TestCase):
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
                f"id: {workspace}\nname: {workspace.title()}\ntype: test\nstatus: active\npurpose: promotion tests\n",
                encoding="utf-8",
            )
        return root

    def _digest(self, root: Path, *, session_id: str = "sess-promote"):
        run_id = f"run-{session_id}"
        return mem.write_session_digest(
            session_id,
            "The completed session contains bounded historical evidence for later selective promotion.",
            run_id=run_id,
            scope="workspace:alpha",
            topic="Selective promotion evidence",
            significant_outcomes=["Validated a durable review workflow"],
            unresolved_items=["No automatic current-state capture"],
            source_refs=[f"gateway:session:{session_id}", f"gateway:run:{run_id}"],
            source_coverage=[f"gateway:session:{session_id}:messages:1-12"],
            source_fingerprint=f"sha256:{session_id}",
            source_version="gateway-run-v1",
            provenance={"owner": "ai-verse-gateway", "kind": "completed_session"},
            completed_at="2026-09-14T12:00:00+00:00",
            effect_id=f"digest:{session_id}",
            root=root,
            mode=mem.MODE_NATIVE,
        )

    def _admission(self, **overrides):
        admission = {
            "durable": True,
            "historical": True,
            "current_truth": False,
            "contains_secret": False,
            "strategic": False,
            "permission_expansion": False,
            "privacy_ambiguous": False,
            "external_authority": False,
        }
        admission.update(overrides)
        return admission

    def test_promotes_only_durable_candidates_and_replay_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, _, _ = self._digest(root)
            candidates = [
                {
                    "text": "Client Alpha reviews are more reliable with concise checkpoint notes.",
                    "type": "lesson",
                    "importance": 4,
                    "confidence": 0.95,
                    "why": "This repeated review pattern has future value.",
                    "tags": "review,workflow",
                    "evidence_refs": ["gateway:session:sess-promote"],
                    "admission": self._admission(),
                },
                {
                    "text": "A temporary conversational aside should not become durable Memory.",
                    "type": "fact",
                    "confidence": 0.99,
                    "admission": self._admission(durable=False),
                },
            ]

            first = mem.promote_session_digest(
                digest_id,
                candidates,
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(first["attempted"], 2)
            self.assertEqual(first["captured"], 1)
            self.assertEqual(first["ignored"], 1)
            self.assertEqual(first["blocked"], 0)

            promoted = [
                row
                for row in mem.recall(
                    "concise checkpoint notes",
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
                if row["kind"] == "memory"
            ]
            self.assertEqual(len(promoted), 1)

            replay = mem.promote_session_digest(
                digest_id,
                candidates,
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(replay["captured"], 0)
            self.assertEqual(replay["existing"], 1)
            self.assertEqual(replay["ignored"], 1)
            self.assertEqual(
                replay["results"][0]["memory_id"],
                first["results"][0]["memory_id"],
            )

    def test_invalid_evidence_fails_before_any_candidate_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, _, _ = self._digest(root, session_id="sess-evidence")
            candidates = [
                {
                    "text": "Valid promotion should not partially write before validation finishes.",
                    "type": "lesson",
                    "confidence": 0.95,
                    "evidence_refs": ["gateway:session:sess-evidence"],
                    "admission": self._admission(),
                },
                {
                    "text": "This candidate cites evidence outside the digest.",
                    "type": "fact",
                    "confidence": 0.95,
                    "evidence_refs": ["gateway:session:not-covered"],
                    "admission": self._admission(),
                },
            ]
            with self.assertRaisesRegex(ValueError, "not covered by the session digest"):
                mem.promote_session_digest(
                    digest_id,
                    candidates,
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

            rows = mem.recall(
                "partially write",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertFalse(any(row["kind"] == "memory" for row in rows))

    def test_promotion_is_bounded_per_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, _, _ = self._digest(root, session_id="sess-bounded")
            candidates = [
                {
                    "text": f"Durable bounded lesson {index}",
                    "type": "lesson",
                    "confidence": 0.95,
                    "admission": self._admission(),
                }
                for index in range(mem.MAX_PROMOTIONS_PER_DIGEST + 1)
            ]
            with self.assertRaisesRegex(ValueError, "at most"):
                mem.promote_session_digest(
                    digest_id,
                    candidates,
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_explicit_correction_supersedes_stale_history_with_effect_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            old_id, old_path, _ = mem.write_atomic(
                "Client Alpha prefers daily CSV exports.",
                "fact",
                "workspace:alpha",
                source="historical-run",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            digest_id, _, _ = self._digest(root, session_id="sess-correction")
            candidate = {
                "text": "Client Alpha prefers weekly JSON exports.",
                "type": "correction",
                "supersedes": old_id,
                "importance": 5,
                "confidence": 0.99,
                "why": "The later completed session explicitly corrected the older preference.",
                "evidence_refs": ["gateway:session:sess-correction"],
                "admission": self._admission(),
            }

            first = mem.promote_session_digest(
                digest_id,
                [candidate],
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(first["captured"], 1)
            correction_id = first["results"][0]["memory_id"]

            old_meta, _ = mem.parse_markdown(old_path)
            self.assertEqual(old_meta["status"], "superseded")
            self.assertEqual(old_meta["superseded_by"], correction_id)

            correction_path = mem.locate_memory(
                correction_id, root=root, mode=mem.MODE_NATIVE
            )
            self.assertIsNotNone(correction_path)
            new_meta, _ = mem.parse_markdown(correction_path)
            self.assertEqual(new_meta["type"], "correction")
            self.assertEqual(new_meta["supersedes"], old_id)
            self.assertEqual(new_meta["scope"], "workspace:alpha")
            self.assertIn(
                f"memory:session-digest:{digest_id}",
                json.loads(new_meta["evidence_refs"]),
            )

            current = mem.recall(
                "exports",
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            current_ids = {row["id"] for row in current}
            self.assertIn(correction_id, current_ids)
            self.assertNotIn(old_id, current_ids)

            history = mem.recall(
                "exports",
                workspace="alpha",
                include_history=True,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            history_ids = {row["id"] for row in history}
            self.assertIn(correction_id, history_ids)
            self.assertIn(old_id, history_ids)

            replay = mem.promote_session_digest(
                digest_id,
                [candidate],
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(replay["existing"], 1)
            self.assertEqual(replay["results"][0]["memory_id"], correction_id)

    def test_correction_cannot_supersede_another_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            beta_id, _, _ = mem.write_atomic(
                "Beta private historical fact.",
                "fact",
                "workspace:beta",
                source="beta-run",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            digest_id, _, _ = self._digest(root, session_id="sess-cross-scope")
            candidate = {
                "text": "Attempted cross-scope correction.",
                "type": "correction",
                "supersedes": beta_id,
                "confidence": 0.99,
                "evidence_refs": ["gateway:session:sess-cross-scope"],
                "admission": self._admission(),
            }
            with self.assertRaisesRegex(ValueError, "across scope boundaries"):
                mem.promote_session_digest(
                    digest_id,
                    [candidate],
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

            beta_meta, _ = mem.parse_markdown(
                mem.locate_memory(beta_id, root=root, mode=mem.MODE_NATIVE)
            )
            self.assertEqual(beta_meta["status"], "active")

    def test_automatic_correction_without_target_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            result = mem.capture_candidate(
                {
                    "text": "Unbound correction must not become active history.",
                    "type": "correction",
                    "workspace": "alpha",
                    "confidence": 0.99,
                    "source": "unit-test",
                    "effect_id": "unbound-correction",
                    "evidence_refs": ["unit:test"],
                    "admission": self._admission(),
                },
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(result["state"], "blocked")
            self.assertFalse(result["changed"])


if __name__ == "__main__":
    unittest.main()
