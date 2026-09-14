import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "scripts" / "memory.py"


def load_memory(name="ai_verse_memory_progressive_recall_tests"):
    spec = importlib.util.spec_from_file_location(name, MEMORY_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


mem = load_memory()


def stable_bytes(value) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


class ProgressiveRecallTests(unittest.TestCase):
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
                'purpose: "progressive recall tests"\n',
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
            unresolved_items=[f"Unresolved for {session_id}"],
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

    def _fixture(self, root: Path):
        operator_context = root / "operator" / "context"
        operator_context.mkdir(parents=True)
        (operator_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\nOperator release review context.\n",
            encoding="utf-8",
        )
        alpha_context = root / "workspaces" / "alpha" / "context"
        alpha_context.mkdir(parents=True)
        (alpha_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\nAlpha release checkpoint is ready for delivery.\n",
            encoding="utf-8",
        )
        beta_context = root / "workspaces" / "beta" / "context"
        beta_context.mkdir(parents=True)
        (beta_context / "CURRENT.md").write_text(
            "# Current Context\n\n## Current state\n\nBeta private release checkpoint material.\n",
            encoding="utf-8",
        )

        operator = mem.write_atomic(
            "Operator release review preference requires concise evidence.",
            "preference",
            "operator",
            tags="release,review",
            source="progressive-fixture",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        alpha = mem.write_atomic(
            "Alpha release delivery workflow uses the verified checkpoint and owner review.",
            "workflow",
            "workspace:alpha",
            tags="alpha-release,delivery",
            source="progressive-fixture",
            why="Keeps Alpha release delivery reproducible.",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        beta = mem.write_atomic(
            "Beta private release workflow must never appear in Alpha retrieval.",
            "workflow",
            "workspace:beta",
            tags="beta-private",
            source="progressive-fixture",
            root=root,
            mode=mem.MODE_NATIVE,
        )
        alpha_digest = self._digest(
            root,
            workspace="alpha",
            session_id="sess-alpha-progressive",
            topic="Alpha release checkpoint",
            summary="Alpha release checkpoint completed with delivery evidence.",
        )
        beta_digest = self._digest(
            root,
            workspace="beta",
            session_id="sess-beta-progressive",
            topic="Beta private release",
            summary="Beta private release evidence must remain isolated.",
        )
        return {
            "operator_id": operator[0],
            "alpha_id": alpha[0],
            "beta_id": beta[0],
            "alpha_digest_id": alpha_digest[0],
            "beta_digest_id": beta_digest[0],
        }

    def test_catalog_depth_reuses_orientation_and_is_scope_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            fixture = self._fixture(root)

            response = mem.progressive_recall(
                depth="catalog",
                workspace="alpha",
                max_bytes=4096,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(response["api_version"], mem.PROGRESSIVE_RECALL_VERSION)
            self.assertEqual(response["depth"], "catalog")
            self.assertEqual(response["scope"], "workspace:alpha")
            self.assertEqual(
                response["catalog"]["visible_scopes"],
                ["workspace:alpha", "operator"],
            )
            self.assertEqual(response["next_depth"], "summary")
            self.assertFalse(response["source_depth_available"])
            self.assertLessEqual(stable_bytes(response), 4096)

            rendered = json.dumps(response, ensure_ascii=False, sort_keys=True)
            self.assertNotIn("Beta private", rendered)
            self.assertNotIn(fixture["beta_id"], rendered)
            self.assertNotIn(fixture["beta_digest_id"], rendered)
            self.assertEqual(
                response["provenance"]["source_fingerprint"],
                response["catalog"]["source_fingerprint"],
            )

    def test_summary_and_detail_are_query_bound_bounded_and_provenance_bearing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            fixture = self._fixture(root)

            summary = mem.progressive_recall(
                "alpha release checkpoint delivery",
                depth="summary",
                workspace="alpha",
                limit=6,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(summary["depth"], "summary")
            self.assertEqual(summary["next_depth"], "detail")
            self.assertTrue(summary["deeper_evidence_available"])
            self.assertFalse(summary["source_depth_available"])
            self.assertLessEqual(summary["returned_items"], 6)
            self.assertLessEqual(stable_bytes(summary), 6000)
            self.assertEqual(summary["provenance"]["owner"], "ai-verse-memory")
            self.assertTrue(summary["provenance"]["query_bound"])

            summary_types = {item["record_type"] for item in summary["items"]}
            self.assertIn("session_digest", summary_types)
            self.assertIn("indexed_record", summary_types)
            self.assertTrue(
                any(item["id"] == fixture["alpha_digest_id"] for item in summary["items"])
            )
            self.assertTrue(
                any(item["id"] == fixture["alpha_id"] for item in summary["items"])
            )
            for item in summary["items"]:
                self.assertIn("evidence", item)
                self.assertNotIn("why", item)
                if item["record_type"] == "indexed_record":
                    self.assertIn("excerpt", item)
                    self.assertNotIn("text", item)

            detail = mem.progressive_recall(
                "alpha release checkpoint delivery",
                depth="detail",
                workspace="alpha",
                limit=6,
                max_bytes=10000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(detail["depth"], "detail")
            self.assertEqual(detail["next_depth"], "source")
            self.assertFalse(detail["source_depth_available"])
            self.assertTrue(detail["deeper_evidence_available"])
            self.assertLessEqual(detail["returned_items"], 6)
            self.assertLessEqual(stable_bytes(detail), 10000)

            indexed = next(
                item
                for item in detail["items"]
                if item["record_type"] == "indexed_record"
                and item["id"] == fixture["alpha_id"]
            )
            self.assertIn("Alpha release delivery workflow", indexed["text"])
            self.assertTrue(indexed["evidence"]["path"])
            self.assertTrue(indexed["evidence"]["source_version"].startswith("sha256:"))

            digest = next(
                item
                for item in detail["items"]
                if item["record_type"] == "session_digest"
                and item["id"] == fixture["alpha_digest_id"]
            )
            self.assertIn("Alpha release checkpoint completed", digest["summary"])
            self.assertTrue(digest["evidence"]["canonical_version"].startswith("sha256:"))
            self.assertTrue(digest["evidence"]["source_refs"])

    def test_progressive_budget_truncates_navigation_without_scope_or_evidence_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._fixture(root)

            for index in range(12):
                mem.write_atomic(
                    (
                        f"Alpha release delivery note {index:02d} "
                        + ("long bounded detail " * 180)
                    ),
                    "experience",
                    "workspace:alpha",
                    tags=f"release-note-{index:02d}",
                    source="progressive-budget-fixture",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
                self._digest(
                    root,
                    workspace="alpha",
                    session_id=f"sess-progressive-budget-{index:02d}",
                    topic=f"Alpha release budget checkpoint {index:02d}",
                    summary="Alpha release delivery " + ("historical summary detail " * 100),
                )

            response = mem.progressive_recall(
                "alpha release delivery",
                depth="detail",
                workspace="alpha",
                limit=20,
                max_bytes=4096,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            repeated = mem.progressive_recall(
                "alpha release delivery",
                depth="detail",
                workspace="alpha",
                limit=20,
                max_bytes=4096,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertLessEqual(stable_bytes(response), 4096)
            self.assertTrue(response["truncated"])
            self.assertGreater(response["candidate_counts"]["session_digests"], 0)
            self.assertGreater(response["candidate_counts"]["indexed_records"], 0)
            self.assertGreater(response["returned_items"], 0)
            self.assertEqual(response, repeated)
            for item in response["items"]:
                self.assertEqual(item["scope"] in {"workspace:alpha", "operator"}, True)
                self.assertIn("evidence", item)

    def test_alpha_progressive_recall_never_returns_beta_private_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            fixture = self._fixture(root)

            response = mem.progressive_recall(
                "private release workflow",
                depth="detail",
                workspace="alpha",
                limit=20,
                max_bytes=8192,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            rendered = json.dumps(response, ensure_ascii=False, sort_keys=True)
            self.assertNotIn(fixture["beta_id"], rendered)
            self.assertNotIn(fixture["beta_digest_id"], rendered)
            self.assertNotIn("Beta private", rendered)

    def test_legacy_recall_behavior_is_unchanged_by_progressive_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            fixture = self._fixture(root)

            before = mem.recall(
                "alpha release delivery",
                workspace="alpha",
                limit=8,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            before_ids = [row["id"] for row in before]
            self.assertIn(fixture["alpha_id"], before_ids)

            mem.progressive_recall(
                "alpha release delivery",
                depth="summary",
                workspace="alpha",
                limit=8,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            mem.progressive_recall(
                "alpha release delivery",
                depth="detail",
                workspace="alpha",
                limit=8,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            after = mem.recall(
                "alpha release delivery",
                workspace="alpha",
                limit=8,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual([row["id"] for row in after], before_ids)

    def test_version_depth_query_and_budget_contracts_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._fixture(root)

            with self.assertRaises(ValueError):
                mem.progressive_recall(
                    "alpha",
                    version="memory.progressive-recall.v0",
                    depth="summary",
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
            with self.assertRaises(ValueError):
                mem.progressive_recall(
                    "alpha",
                    depth="source",
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
            with self.assertRaises(ValueError):
                mem.progressive_recall(
                    "",
                    depth="detail",
                    workspace="alpha",
                    root=root,
                    mode=mem.MODE_NATIVE,
                )
            with self.assertRaises(ValueError):
                mem.progressive_recall(
                    "alpha",
                    depth="summary",
                    workspace="alpha",
                    max_bytes=1024,
                    root=root,
                    mode=mem.MODE_NATIVE,
                )


if __name__ == "__main__":
    unittest.main()
