import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "scripts" / "memory.py"


def load_memory(name="ai_verse_memory_relationship_projection_tests"):
    spec = importlib.util.spec_from_file_location(name, MEMORY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mem = load_memory()


class RelationshipProjectionTests(unittest.TestCase):
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
                'schema_version: "2.0"\n'
                f'id: "{workspace}"\n'
                f'name: "{workspace.title()}"\n'
                'type: "test"\n'
                'status: "active"\n'
                'purpose: "relationship projection tests"\n',
                encoding="utf-8",
            )
        return root

    def _digest(
        self,
        root: Path,
        *,
        workspace: str,
        session_id: str,
        run_id: str,
        marker: str,
    ):
        return mem.write_session_digest(
            session_id,
            f"{marker} compact session result.",
            run_id=run_id,
            scope=f"workspace:{workspace}",
            topic=f"{marker} session",
            significant_outcomes=[f"{marker} outcome"],
            unresolved_items=[],
            source_refs=[
                f"gateway:session:{session_id}",
                f"gateway:run:{run_id}",
            ],
            source_coverage=[f"gateway:run:{run_id}:messages:0-5"],
            source_fingerprint="sha256:" + (
                "a" if workspace == "alpha" else "b"
            ) * 64,
            source_version="gateway-run-v1",
            provenance={
                "owner": "ai-verse-gateway",
                "kind": "completed_session",
                "session_id": session_id,
                "run_id": run_id,
            },
            completed_at="2026-09-14T12:00:00+00:00",
            effect_id=f"digest:{workspace}:{run_id}",
            root=root,
            mode=mem.MODE_NATIVE,
        )

    def _fixture(self, root: Path):
        alpha_digest_1 = self._digest(
            root,
            workspace="alpha",
            session_id="sess-shared-alpha",
            run_id="run-alpha-1",
            marker="Alpha one",
        )
        alpha_digest_2 = self._digest(
            root,
            workspace="alpha",
            session_id="sess-shared-alpha",
            run_id="run-alpha-2",
            marker="Alpha two",
        )
        beta_digest = self._digest(
            root,
            workspace="beta",
            session_id="sess-beta-private",
            run_id="run-beta-1",
            marker="Beta private",
        )

        promoted_id, promoted_path, _ = mem.write_atomic(
            "Alpha delivery lesson promoted from the completed session.",
            "lesson",
            "workspace:alpha",
            source=f"memory:session-digest:{alpha_digest_1[0]}",
            evidence_refs=[
                f"memory:session-digest:{alpha_digest_1[0]}",
                "gateway:run:run-alpha-1",
            ],
            tags="alpha,delivery",
            effect_id="rel-alpha-promoted",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        beta_id, _, _ = mem.write_atomic(
            "Beta private relationship material.",
            "lesson",
            "workspace:beta",
            evidence_refs=[
                f"memory:session-digest:{beta_digest[0]}",
                "gateway:run:run-beta-1",
            ],
            effect_id="rel-beta-promoted",
            root=root,
            mode=mem.MODE_NATIVE,
        )

        old_id, old_path, _ = mem.write_atomic(
            "Alpha release path was /srv/alpha/v1.json.",
            "fact",
            "workspace:alpha",
            effect_id="rel-alpha-old",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        new_id, new_path, _ = mem.supersede_atomic(
            old_id,
            "Alpha release path is /srv/alpha/v2.json.",
            mem_type="correction",
            scope="workspace:alpha",
            evidence_refs=["gateway:run:run-alpha-2"],
            effect_id="rel-alpha-correction",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        return {
            "alpha_digest_1": alpha_digest_1[0],
            "alpha_digest_2": alpha_digest_2[0],
            "beta_digest": beta_digest[0],
            "promoted_id": promoted_id,
            "promoted_path": promoted_path,
            "beta_id": beta_id,
            "old_id": old_id,
            "old_path": old_path,
            "new_id": new_id,
            "new_path": new_path,
        }

    @staticmethod
    def _key(edge):
        return (
            edge["scope"],
            edge["relation_type"],
            edge["source_kind"],
            edge["source_ref"],
            edge["target_kind"],
            edge["target_ref"],
        )

    def test_projection_contains_only_explicit_deterministic_relationships(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            f = self._fixture(root)

            summary = mem.rebuild_relationship_projection(
                root=root,
                mode=mem.MODE_NATIVE,
            )
            alpha = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            keys = {self._key(edge) for edge in alpha}

            self.assertGreater(summary["edge_count"], 0)
            self.assertTrue(summary["projection_fingerprint"].startswith("sha256:"))
            self.assertIn("supersedes", summary["relation_types"])
            self.assertIn("superseded_by", summary["relation_types"])
            self.assertIn("derived_from", summary["relation_types"])
            self.assertIn("same_session", summary["relation_types"])

            self.assertIn(
                (
                    "workspace:alpha",
                    "supersedes",
                    "atomic_memory",
                    f["new_id"],
                    "atomic_memory",
                    f["old_id"],
                ),
                keys,
            )
            self.assertIn(
                (
                    "workspace:alpha",
                    "superseded_by",
                    "atomic_memory",
                    f["old_id"],
                    "atomic_memory",
                    f["new_id"],
                ),
                keys,
            )
            self.assertIn(
                (
                    "workspace:alpha",
                    "derived_from",
                    "atomic_memory",
                    f["promoted_id"],
                    "session_digest",
                    f["alpha_digest_1"],
                ),
                keys,
            )
            self.assertIn(
                (
                    "workspace:alpha",
                    "derived_from",
                    "atomic_memory",
                    f["promoted_id"],
                    "external_ref",
                    "gateway:run:run-alpha-1",
                ),
                keys,
            )
            self.assertIn(
                (
                    "workspace:alpha",
                    "same_session",
                    "session_digest",
                    f["alpha_digest_1"],
                    "session",
                    "gateway:session:sess-shared-alpha",
                ),
                keys,
            )
            self.assertIn(
                (
                    "workspace:alpha",
                    "same_session",
                    "session_digest",
                    f["alpha_digest_2"],
                    "session",
                    "gateway:session:sess-shared-alpha",
                ),
                keys,
            )

            # same_session is O(n) via a stable session identity node, not
            # pairwise digest-to-digest graph expansion.
            same_session = [
                edge
                for edge in alpha
                if edge["relation_type"] == "same_session"
                and edge["target_ref"] == "gateway:session:sess-shared-alpha"
            ]
            self.assertEqual(len(same_session), 2)
            self.assertTrue(all(edge["target_kind"] == "session" for edge in same_session))

            for edge in alpha:
                self.assertTrue(edge["edge_id"].startswith("rel-"))
                self.assertTrue(edge["source_version"].startswith("sha256:"))
                self.assertIsInstance(edge["evidence"], list)
                self.assertTrue(edge["evidence"])
                self.assertNotIn("Alpha delivery lesson", json.dumps(edge))
                self.assertNotIn("release path is", json.dumps(edge))

    def test_workspace_visibility_never_leaks_unrelated_workspace_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            f = self._fixture(root)

            alpha = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            rendered = json.dumps(alpha, sort_keys=True)
            self.assertNotIn("workspace:beta", rendered)
            self.assertNotIn(f["beta_id"], rendered)
            self.assertNotIn(f["beta_digest"], rendered)
            self.assertNotIn("run-beta-1", rendered)

            beta = mem.list_relationships(
                workspace="beta",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertTrue(beta)
            self.assertTrue(
                all(edge["scope"] in {"workspace:beta", "operator"} for edge in beta)
            )

    def test_drop_and_rebuild_is_exactly_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._fixture(root)

            first_summary = mem.rebuild_relationship_projection(
                root=root,
                mode=mem.MODE_NATIVE,
            )
            first = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            conn, _ = mem.connect_db(root, mem.MODE_NATIVE)
            try:
                conn.execute("DROP TABLE IF EXISTS memory_relationships")
                conn.commit()
            finally:
                conn.close()

            second_summary = mem.rebuild_relationship_projection(
                root=root,
                mode=mem.MODE_NATIVE,
            )
            second = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(second_summary, first_summary)
            self.assertEqual(second, first)

    def test_canonical_edit_and_delete_remove_stale_derived_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            f = self._fixture(root)

            before = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            before_keys = {self._key(edge) for edge in before}
            promoted_digest_key = (
                "workspace:alpha",
                "derived_from",
                "atomic_memory",
                f["promoted_id"],
                "session_digest",
                f["alpha_digest_1"],
            )
            self.assertIn(promoted_digest_key, before_keys)

            meta, body = mem.parse_markdown(f["promoted_path"])
            meta["evidence_refs"] = json.dumps(
                ["gateway:run:run-alpha-revised"],
                separators=(",", ":"),
            )
            meta["source"] = "manual-revision"
            f["promoted_path"].write_text(
                mem.render_frontmatter(meta) + "\n\n" + body.strip() + "\n",
                encoding="utf-8",
            )

            revised = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            revised_keys = {self._key(edge) for edge in revised}
            self.assertNotIn(promoted_digest_key, revised_keys)
            self.assertIn(
                (
                    "workspace:alpha",
                    "derived_from",
                    "atomic_memory",
                    f["promoted_id"],
                    "external_ref",
                    "gateway:run:run-alpha-revised",
                ),
                revised_keys,
            )

            # Removing the superseded canonical target makes both canonical
            # supersession edges disappear on the next refresh.
            f["old_path"].unlink()
            after_delete = mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            after_keys = {self._key(edge) for edge in after_delete}
            self.assertNotIn(
                (
                    "workspace:alpha",
                    "supersedes",
                    "atomic_memory",
                    f["new_id"],
                    "atomic_memory",
                    f["old_id"],
                ),
                after_keys,
            )
            self.assertNotIn(
                (
                    "workspace:alpha",
                    "superseded_by",
                    "atomic_memory",
                    f["old_id"],
                    "atomic_memory",
                    f["new_id"],
                ),
                after_keys,
            )

    def test_projection_never_rewrites_canonical_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._fixture(root)

            canonical = sorted(
                [
                    *mem.iter_atomic_files(root=root, mode=mem.MODE_NATIVE),
                    *(
                        path
                        for path in root.rglob("sdg-*.md")
                        if path.is_file() and not path.is_symlink()
                    ),
                ]
            )
            before = {str(path): path.read_bytes() for path in canonical}

            mem.rebuild_relationship_projection(root=root, mode=mem.MODE_NATIVE)
            mem.list_relationships(
                workspace="alpha",
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            mem.refresh_relationship_projection(root=root, mode=mem.MODE_NATIVE)

            after = {str(path): path.read_bytes() for path in canonical}
            self.assertEqual(after, before)

    def test_malformed_or_dangling_explicit_refs_do_not_create_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            memory_id, path, _ = mem.write_atomic(
                "Dangling metadata fixture.",
                "fact",
                "workspace:alpha",
                effect_id="rel-dangling",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            meta, body = mem.parse_markdown(path)
            meta["supersedes"] = "mem-does-not-exist"
            meta["evidence_refs"] = "{not-json"
            path.write_text(
                mem.render_frontmatter(meta) + "\n\n" + body.strip() + "\n",
                encoding="utf-8",
            )

            rows = mem.list_relationships(
                workspace="alpha",
                source_ref=memory_id,
                limit=200,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
