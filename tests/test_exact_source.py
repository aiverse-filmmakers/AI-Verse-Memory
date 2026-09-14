import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "scripts" / "memory.py"


def load_memory(name="ai_verse_memory_exact_source_tests"):
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


class ExactSourceTests(unittest.TestCase):
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
                'purpose: "exact source tests"\n',
                encoding="utf-8",
            )
        return root

    def _write_current(self, root: Path, workspace: str, text: str) -> Path:
        base = root / "workspaces" / workspace / "context"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "CURRENT.md"
        path.write_text(text, encoding="utf-8")
        return path

    def _alpha_current(self, root: Path) -> Path:
        return self._write_current(
            root,
            "alpha",
            "# Current Context\n\n"
            "## Exact deployment facts\n\n"
            "Deployment ID: deploy-ALPHA-4821\n"
            "Release date: 2026-09-21\n"
            "Retry budget: 37\n"
            "Config path: configs/alpha/prod.yaml\n"
            "Feature state: enabled\n"
            'Approved quote: "Ship only after checksum match."\n',
        )

    def _detail_context_item(self, root: Path, workspace: str = "alpha"):
        response = mem.progressive_recall(
            "deploy ALPHA 4821 retry budget checksum",
            depth="detail",
            workspace=workspace,
            limit=12,
            max_bytes=12000,
            root=root,
            mode=mem.MODE_NATIVE,
        )
        return next(
            item
            for item in response["items"]
            if item["record_type"] == "indexed_record"
            and item.get("kind") == "context"
            and item["scope"] == f"workspace:{workspace}"
        )

    def _digest(self, root: Path, workspace: str, session_id: str):
        run_id = f"run-{session_id}"
        return mem.write_session_digest(
            session_id,
            "Alpha digest summary mentions deploy-ALPHA-4821 but is not the original transcript.",
            run_id=run_id,
            scope=f"workspace:{workspace}",
            topic="Alpha exact deployment evidence",
            significant_outcomes=["Deployment evidence captured"],
            unresolved_items=[],
            source_refs=[
                f"gateway:session:{session_id}",
                f"gateway:run:{run_id}",
            ],
            source_coverage=[f"gateway:run:{run_id}:messages:2-7"],
            source_fingerprint="sha256:" + "a" * 64,
            source_version="gateway-run-v1",
            provenance={"owner": "ai-verse-gateway", "kind": "completed_session"},
            completed_at="2026-09-14T12:00:00+00:00",
            effect_id=f"digest:{session_id}",
            root=root,
            mode=mem.MODE_NATIVE,
        )

    def test_exact_source_returns_authoritative_current_file_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._alpha_current(root)
            detail = self._detail_context_item(root)

            source = mem.progressive_recall(
                "deploy ALPHA 4821 retry budget checksum",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(source["status"], "ok")
            self.assertTrue(source["exact_evidence"])
            self.assertTrue(source["source_depth_available"])
            self.assertEqual(source["record_type"], "indexed_record")
            self.assertEqual(source["record_scope"], "workspace:alpha")
            self.assertEqual(
                source["evidence"]["source_version"],
                detail["evidence"]["source_version"],
            )
            self.assertTrue(source["provenance"]["scope_revalidated"])
            self.assertTrue(source["provenance"]["containment_revalidated"])
            self.assertTrue(source["provenance"]["version_revalidated"])
            self.assertLessEqual(stable_bytes(source), 6000)

            raw = source["source"]["content"]
            self.assertIn("Deployment ID: deploy-ALPHA-4821", raw)
            self.assertIn("Release date: 2026-09-21", raw)
            self.assertIn("Retry budget: 37", raw)
            self.assertIn("Config path: configs/alpha/prod.yaml", raw)
            self.assertIn("Feature state: enabled", raw)
            self.assertIn('"Ship only after checksum match."', raw)

    def test_changed_source_fails_closed_as_stale_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            current = self._alpha_current(root)
            detail = self._detail_context_item(root)

            current.write_text(
                current.read_text(encoding="utf-8").replace(
                    "Retry budget: 37",
                    "Retry budget: 41",
                ),
                encoding="utf-8",
            )

            stale = mem.progressive_recall(
                "retry budget",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(stale["status"], "stale")
            self.assertFalse(stale["exact_evidence"])
            self.assertEqual(stale["reason"], "source_version_mismatch")
            self.assertNotEqual(
                stale["evidence"]["expected_source_version"],
                stale["evidence"]["current_source_version"],
            )
            self.assertNotIn("source", stale)

    def test_deleted_source_returns_explicit_unavailable_without_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            current = self._alpha_current(root)
            detail = self._detail_context_item(root)
            current.unlink()

            missing = mem.progressive_recall(
                "deploy ALPHA 4821",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                root=root,
                mode=mem.MODE_NATIVE,
            )

            self.assertEqual(missing["status"], "unavailable")
            self.assertFalse(missing["exact_evidence"])
            self.assertIn(
                missing["reason"],
                {
                    "source_missing_or_no_longer_indexed",
                    "source_failed_containment_or_read_validation",
                },
            )
            self.assertNotIn("source", missing)

    def test_cross_workspace_evidence_is_rejected_even_with_known_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._write_current(
                root,
                "beta",
                "# Current Context\n\n"
                "## Exact deployment facts\n\n"
                "Deployment ID: deploy-ALPHA-4821\n"
                "Retry budget: 37\n"
                "Approved quote: checksum private beta.\n",
            )
            detail = self._detail_context_item(root, workspace="beta")

            with self.assertRaisesRegex(ValueError, "not authorized"):
                mem.progressive_recall(
                    "deploy ALPHA 4821",
                    depth="source",
                    workspace="alpha",
                    evidence_ref=detail,
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_tampered_path_pointer_is_rejected_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            self._alpha_current(root)
            detail = self._detail_context_item(root)
            tampered = json.loads(json.dumps(detail))
            tampered["evidence"]["path"] = "workspaces/beta/context/CURRENT.md"

            with self.assertRaisesRegex(ValueError, "path does not match"):
                mem.progressive_recall(
                    "deploy ALPHA 4821",
                    depth="source",
                    workspace="alpha",
                    evidence_ref=tampered,
                    root=root,
                    mode=mem.MODE_NATIVE,
                )

    def test_large_source_is_query_centered_and_hard_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            prefix = "irrelevant historical padding\n" * 500
            exact = (
                "EXACT-NEEDLE-991\n"
                "Critical release amount: 918273645\n"
                "Critical path: /srv/alpha/release/final.json\n"
            )
            suffix = "later irrelevant padding\n" * 500
            self._write_current(
                root,
                "alpha",
                "# Current Context\n\n" + prefix + exact + suffix,
            )

            detail_response = mem.progressive_recall(
                "EXACT NEEDLE 991 critical release amount",
                depth="detail",
                workspace="alpha",
                max_bytes=12000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            detail = next(
                item
                for item in detail_response["items"]
                if item["record_type"] == "indexed_record"
                and item.get("kind") == "context"
                and item["scope"] == "workspace:alpha"
            )

            source = mem.progressive_recall(
                "EXACT-NEEDLE-991",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                max_bytes=4096,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(source["status"], "ok")
            self.assertLessEqual(stable_bytes(source), 4096)
            self.assertTrue(source["source"]["content_truncated"])
            self.assertTrue(source["source"]["query_match"])
            self.assertIn("Critical release amount: 918273645", source["source"]["content"])
            self.assertIn(
                "Critical path: /srv/alpha/release/final.json",
                source["source"]["content"],
            )

    def test_atomic_memory_exact_source_uses_current_canonical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            memory_id, _, _ = mem.write_atomic(
                "License renewal date is 2027-02-13 and contract ID is CNT-88421.",
                "fact",
                "workspace:alpha",
                tags="contract,exact",
                source="exact-source-test",
                root=root,
                mode=mem.MODE_NATIVE,
            )
            detail_response = mem.progressive_recall(
                "license renewal contract CNT 88421",
                depth="detail",
                workspace="alpha",
                limit=8,
                max_bytes=10000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            detail = next(
                item
                for item in detail_response["items"]
                if item["record_type"] == "indexed_record" and item["id"] == memory_id
            )

            source = mem.progressive_recall(
                "CNT-88421",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(source["status"], "ok")
            self.assertIn("2027-02-13", source["source"]["content"])
            self.assertIn("CNT-88421", source["source"]["content"])

    def test_session_digest_returns_gateway_source_refs_not_summary_as_exact_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, _, _ = self._digest(root, "alpha", "sess-exact-digest")
            detail_response = mem.progressive_recall(
                "alpha exact deployment evidence",
                depth="detail",
                workspace="alpha",
                limit=8,
                max_bytes=10000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            detail = next(
                item
                for item in detail_response["items"]
                if item["record_type"] == "session_digest" and item["id"] == digest_id
            )

            source = mem.progressive_recall(
                "deploy ALPHA 4821",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                max_bytes=6000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(source["status"], "external_source_required")
            self.assertFalse(source["exact_evidence"])
            self.assertTrue(source["provenance"]["external_owner_required"])
            self.assertNotIn("source", source)
            self.assertIn(
                "gateway:session:sess-exact-digest",
                source["evidence"]["external_source_refs"],
            )
            self.assertEqual(
                source["reason"],
                "session_digest_is_navigation_not_original_transcript_evidence",
            )

    def test_changed_canonical_digest_is_stale_before_external_refs_are_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._native_root(Path(tmp))
            digest_id, digest_path, _ = self._digest(root, "alpha", "sess-stale-digest")
            detail_response = mem.progressive_recall(
                "alpha exact deployment evidence",
                depth="detail",
                workspace="alpha",
                limit=8,
                max_bytes=10000,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            detail = next(
                item
                for item in detail_response["items"]
                if item["record_type"] == "session_digest" and item["id"] == digest_id
            )

            digest_path.write_text(
                digest_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            stale = mem.progressive_recall(
                "deploy ALPHA 4821",
                depth="source",
                workspace="alpha",
                evidence_ref=detail,
                root=root,
                mode=mem.MODE_NATIVE,
            )
            self.assertEqual(stale["status"], "stale")
            self.assertEqual(stale["reason"], "canonical_digest_version_mismatch")
            self.assertFalse(stale["exact_evidence"])
            self.assertNotIn("external_source_refs", stale.get("evidence", {}))


if __name__ == "__main__":
    unittest.main()
