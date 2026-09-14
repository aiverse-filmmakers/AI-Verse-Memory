import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "scripts" / "memory.py"


def load_memory(name="ai_verse_memory_orientation_tests"):
    spec = importlib.util.spec_from_file_location(name, MEMORY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mem = load_memory()


class OrientationMapTests(unittest.TestCase):
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
                'purpose: "orientation map tests"\n',
                encoding="utf-8",
            )
        return root

    def _digest(
        self,
        root: Path,
        *,
        workspace: str,
        session_id: str,
        topic: str,
        summary: str,
    ):
        run_id = f"run-{session_id}"
        return mem.write_session_digest(
            session_id,
            summary,
            run_id=run_id,
            scope=f"workspace:{workspace}",
            topic=topic,
            significant_outcomes=[f"Outcome for {session_id}"],
            unresolved_items=[],
            source_refs=[
                f"gateway:session:{session_id}",
                f"gateway:run:{run_id}",
            ],
            source_coverage=[f"gateway:run:{run_id}:messages:0-8"],
            source_fingerprint="sha256:" + ("a" if workspace == "alpha" else "b") * 64,
            source_version="gateway-run-v1",
            provenance={"owner": "ai-verse-gateway", "kind": "completed_session"},
            completed_at="2026-09-14T12:00:00+00:00",
            effect_id=f"digest:{session_id}",
            root=root,
            mode=mem.MODE_NATIVE,
        )

    def _write_large_fixture(self, root: Path):
        operator_context = root / "operator" / "context"
        operator_context.mkdir(parents=True)
        (operator_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\n"
            + ("Operator current routing detail. " * 180)
            + "\n",
            encoding="utf-8",
        )

        alpha_context = root / "workspaces" / "alpha" / "context"
        alpha_context.mkdir(parents=True)
        (alpha_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\n"
            + ("Alpha delivery state and checkpoint routing detail. " * 220)
            + "\n",
            encoding="utf-8",
        )

        beta_context = root / "workspaces" / "beta" / "context"
        beta_context.mkdir(parents=True)
        (beta_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\n"
            + ("Beta private current material. " * 180)
            + "\n",
            encoding="utf-8",
        )

        operator_id, operator_path, _ = mem.write_atomic(
            "Operator review preference " + ("concise evidence " * 140),
            "preference",
            "operator",
            tags="review-style",
            source="orientation-fixture",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        alpha_id, alpha_path, _ = mem.write_atomic(
            "Alpha historical delivery workflow " + ("verified checkpoint " * 180),
            "workflow",
            "workspace:alpha",
            tags="delivery, review",
            source="orientation-fixture",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        beta_id, beta_path, _ = mem.write_atomic(
            "Beta private historical workflow " + ("private beta phrase " * 180),
            "workflow",
            "workspace:beta",
            tags="beta-private-tag",
            source="orientation-fixture",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        alpha_digest = self._digest(
            root,
            workspace="alpha",
            session_id="sess-alpha-orientation",
            topic="Alpha release checkpoint",
            summary="Alpha completed-session summary " + ("bounded historical evidence " * 120),
        )
        beta_digest = self._digest(
            root,
            workspace="beta",
            session_id="sess-beta-orientation",
            topic="Beta private research",
            summary="Beta private completed-session summary " + ("private beta evidence " * 120),
        )
        return {
            "operator_path": operator_path,
            "alpha_path": alpha_path,
            "beta_path": beta_path,
            "alpha_digest_path": alpha_digest[1],
            "beta_digest_path": beta_digest[1],
            "operator_id": operator_id,
            "alpha_id": alpha_id,
            "beta_id": beta_id,
        }

    def test_workspace_map_is_tiny_deterministic_and_scope_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            paths = self._write_large_fixture(root)

            first = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            second = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(first, second)
            self.assertEqual(first["scope"], "workspace:alpha")
            self.assertEqual(first["visible_scopes"], ["workspace:alpha", "operator"])
            self.assertEqual(first["counts"]["atomic_memory"], 2)
            self.assertEqual(first["counts"]["session_digests"], 1)

            rendered = json.dumps(first, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("Beta private", rendered)
            self.assertNotIn("beta-private-tag", rendered)
            self.assertNotIn(paths["beta_id"], rendered)
            self.assertNotIn("Alpha historical delivery workflow", rendered)
            self.assertNotIn("Alpha completed-session summary", rendered)

            labels = {row["label"] for row in first["topics"]}
            self.assertIn("delivery", labels)
            self.assertIn("review", labels)
            self.assertIn("review-style", labels)
            self.assertIn("Alpha release checkpoint", labels)

            source_routes = json.dumps(first["source_routes"], sort_keys=True)
            self.assertIn("workspaces/alpha/context/CURRENT.md", source_routes)
            self.assertNotIn("workspaces/beta/", source_routes)

            source_files = [
                paths["operator_path"],
                paths["alpha_path"],
                paths["alpha_digest_path"],
                root / "operator" / "context" / "CURRENT.md",
                root / "workspaces" / "alpha" / "context" / "CURRENT.md",
                root / "workspaces" / "alpha" / "WORKSPACE.yaml",
            ]
            source_bytes = sum(path.stat().st_size for path in source_files)
            map_bytes = len(
                json.dumps(
                    first,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self.assertGreater(source_bytes, map_bytes * 4)

    def test_operator_map_never_includes_workspace_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_large_fixture(root)
            projection = mem.get_orientation_map(
                scope="operator",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            rendered = json.dumps(projection, ensure_ascii=False, sort_keys=True)
            self.assertEqual(projection["visible_scopes"], ["operator"])
            self.assertNotIn("workspace:alpha", rendered)
            self.assertNotIn("workspace:beta", rendered)
            self.assertNotIn("Alpha release checkpoint", rendered)
            self.assertNotIn("Beta private research", rendered)

    def test_projection_table_can_be_deleted_and_rebuilt_losslessly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_large_fixture(root)
            before = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )

            db = mem.ensure_layout(root, mem.MODE_NATIVE)["db"]
            conn = sqlite3.connect(db)
            try:
                conn.execute("DROP TABLE orientation_maps")
                conn.commit()
            finally:
                conn.close()

            after = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(after, before)

    def test_canonical_removal_and_update_remove_stale_map_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            alpha_context = root / "workspaces" / "alpha" / "context"
            alpha_context.mkdir(parents=True)
            current = alpha_context / "CURRENT.md"
            current.write_text(
                "# Current Context\n\n## Current state\n\nOld routed source.\n",
                encoding="utf-8",
            )

            _, atomic_path, _ = mem.write_atomic(
                "Historical alpha workflow.",
                "workflow",
                "workspace:alpha",
                tags="old-tag",
                source="orientation-refresh-test",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            _, digest_path, _ = self._digest(
                root,
                workspace="alpha",
                session_id="sess-stale-map",
                topic="Old session topic",
                summary="Historical session evidence that should disappear after canonical removal.",
            )

            before = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            labels_before = {row["label"] for row in before["topics"]}
            self.assertIn("old-tag", labels_before)
            self.assertIn("Old session topic", labels_before)
            self.assertEqual(before["counts"]["atomic_memory"], 1)
            self.assertEqual(before["counts"]["session_digests"], 1)
            self.assertTrue(
                any(
                    "workspaces/alpha/context/CURRENT.md" in route["paths"]
                    for route in before["source_routes"]
                )
            )

            raw = atomic_path.read_text(encoding="utf-8")
            atomic_path.write_text(raw.replace("tags: old-tag", "tags: new-tag"), encoding="utf-8")
            digest_path.unlink()
            current.unlink()

            after = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            labels_after = {row["label"] for row in after["topics"]}
            self.assertNotIn("old-tag", labels_after)
            self.assertIn("new-tag", labels_after)
            self.assertNotIn("Old session topic", labels_after)
            self.assertEqual(after["counts"]["atomic_memory"], 1)
            self.assertEqual(after["counts"]["session_digests"], 0)
            self.assertFalse(
                any(
                    "workspaces/alpha/context/CURRENT.md" in route["paths"]
                    for route in after["source_routes"]
                )
            )

            atomic_path.unlink()
            final = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(final["counts"]["atomic_memory"], 0)
            self.assertNotIn("new-tag", {row["label"] for row in final["topics"]})

    def test_source_fingerprint_tracks_authoritative_drift_without_cross_workspace_noise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            paths = self._write_large_fixture(root)

            first = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            fingerprint = first["source_fingerprint"]
            self.assertTrue(fingerprint.startswith("sha256:"))

            beta_raw = paths["beta_path"].read_text(encoding="utf-8")
            paths["beta_path"].write_text(
                beta_raw.replace("private beta phrase", "private beta revised phrase", 1),
                encoding="utf-8",
            )
            unrelated = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(unrelated["source_fingerprint"], fingerprint)

            alpha_raw = paths["alpha_path"].read_text(encoding="utf-8")
            paths["alpha_path"].write_text(
                alpha_raw.replace("verified checkpoint", "verified checkpoint revised", 1),
                encoding="utf-8",
            )
            atomic_changed = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertNotEqual(atomic_changed["source_fingerprint"], fingerprint)

            current = root / "workspaces" / "alpha" / "context" / "CURRENT.md"
            current.write_text(
                current.read_text(encoding="utf-8") + "\nUpdated current-source evidence.\n",
                encoding="utf-8",
            )
            source_changed = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertNotEqual(
                source_changed["source_fingerprint"],
                atomic_changed["source_fingerprint"],
            )

            self._digest(
                root,
                workspace="alpha",
                session_id="sess-alpha-fingerprint-second",
                topic="Fingerprint follow-up",
                summary="A second completed session changes canonical digest evidence.",
            )
            digest_changed = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertNotEqual(
                digest_changed["source_fingerprint"],
                source_changed["source_fingerprint"],
            )

    def test_stale_stored_projection_is_replaced_from_authoritative_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            paths = self._write_large_fixture(root)
            before = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )

            db = mem.ensure_layout(root, mem.MODE_NATIVE)["db"]
            conn = sqlite3.connect(db)
            try:
                stale = dict(before)
                stale["source_fingerprint"] = "sha256:" + ("0" * 64)
                stale["topics"] = [{"label": "stale fabricated topic", "count": 999, "origins": ["invalid"]}]
                conn.execute(
                    "UPDATE orientation_maps SET projection_json=? WHERE scope=?",
                    (json.dumps(stale, sort_keys=True), "workspace:alpha"),
                )
                conn.commit()
            finally:
                conn.close()

            raw = paths["alpha_path"].read_text(encoding="utf-8")
            paths["alpha_path"].write_text(
                raw.replace("verified checkpoint", "fresh canonical checkpoint", 1),
                encoding="utf-8",
            )
            refreshed = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertNotEqual(refreshed["source_fingerprint"], stale["source_fingerprint"])
            self.assertNotIn(
                "stale fabricated topic",
                {row["label"] for row in refreshed["topics"]},
            )

            conn = sqlite3.connect(db)
            try:
                stored = json.loads(
                    conn.execute(
                        "SELECT projection_json FROM orientation_maps WHERE scope=?",
                        ("workspace:alpha",),
                    ).fetchone()[0]
                )
            finally:
                conn.close()
            self.assertEqual(stored, refreshed)

    def test_configured_budget_is_hard_deterministic_and_preserves_core_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_large_fixture(root)
            for index in range(14):
                self._digest(
                    root,
                    workspace="alpha",
                    session_id=f"sess-budget-{index:02d}",
                    topic=(f"Budget topic {index:02d} " + ("navigation signal " * 8)).strip(),
                    summary="Budget fixture historical evidence.",
                )

            full = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
                max_bytes=8192,
            )
            bounded = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
                max_bytes=2200,
            )
            repeated = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
                max_bytes=2200,
            )

            rendered = json.dumps(
                bounded,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.assertLessEqual(len(rendered), 2200)
            self.assertTrue(bounded["truncated"])
            self.assertEqual(bounded["budget_bytes"], 2200)
            self.assertEqual(bounded["source_fingerprint"], full["source_fingerprint"])
            self.assertEqual(bounded["counts"], full["counts"])
            self.assertEqual(bounded["memory_types"], full["memory_types"])
            self.assertEqual(bounded["source_kinds"], full["source_kinds"])
            self.assertEqual(repeated, bounded)
            with self.assertRaises(ValueError):
                mem.get_orientation_map(
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                    max_bytes=512,
                )

    def test_diagnostics_are_bounded_content_free_and_match_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_large_fixture(root)

            projection = mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
                max_bytes=4096,
            )
            diagnostics = mem.get_orientation_map_diagnostics(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
                max_bytes=4096,
            )
            expected_bytes = len(
                json.dumps(
                    projection,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
            self.assertEqual(diagnostics["projection_bytes"], expected_bytes)
            self.assertEqual(diagnostics["estimated_tokens"], (expected_bytes + 3) // 4)
            self.assertEqual(diagnostics["source_fingerprint"], projection["source_fingerprint"])
            self.assertEqual(diagnostics["source_counts"], projection["counts"])
            self.assertEqual(diagnostics["freshness"], "fresh")
            self.assertLessEqual(diagnostics["projection_bytes"], diagnostics["budget_bytes"])

            rendered = json.dumps(diagnostics, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("Alpha historical delivery workflow", rendered)
            self.assertNotIn("Alpha completed-session summary", rendered)
            self.assertNotIn("Beta private", rendered)
            self.assertNotIn("chain", rendered.lower())

    def test_map_generation_never_rewrites_canonical_owner_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_large_fixture(root)

            canonical_roots = [root / "operator", root / "workspaces"]
            before = {}
            for base in canonical_roots:
                for path in sorted(p for p in base.rglob("*") if p.is_file()):
                    before[path.relative_to(root).as_posix()] = path.read_bytes()

            mem.get_orientation_map(
                workspace="alpha",
                root=root,
                mode=mem.MODE_NATIVE,
            )

            after = {}
            for base in canonical_roots:
                for path in sorted(p for p in base.rglob("*") if p.is_file()):
                    after[path.relative_to(root).as_posix()] = path.read_bytes()
            self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
