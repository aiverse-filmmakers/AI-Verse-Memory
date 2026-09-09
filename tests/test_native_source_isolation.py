import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("ai_verse_memory_source_isolation", ROOT / "scripts" / "memory.py")
mem = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mem)


SOURCE_KINDS = (
    "memory",
    "profile",
    "context",
    "decision",
    "memory_summary",
    "workspace_manifest",
)


class NativeSourceIsolationAcceptanceTests(unittest.TestCase):
    def _make_root(self, base: Path) -> Path:
        root = base / "ai-verse-os"
        root.mkdir()
        (root / "AI-VERSE.yaml").write_text(
            'schema_version: "2.0"\narchitecture: unified-workspace\npaths:\n  operator: operator/\n  workspaces: workspaces/\n',
            encoding="utf-8",
        )
        for path in (
            "operator/profile",
            "operator/context",
            "operator/memory/atomic",
            "operator/decisions",
            "workspaces/alpha/context",
            "workspaces/alpha/memory/atomic",
            "workspaces/alpha/decisions",
            "workspaces/beta/context",
            "workspaces/beta/memory/atomic",
            "workspaces/beta/decisions",
            "runtime",
        ):
            (root / path).mkdir(parents=True, exist_ok=True)
        for wid in ("alpha", "beta"):
            (root / f"workspaces/{wid}/WORKSPACE.yaml").write_text(
                f"id: {wid}\nname: {wid.title()}\ntype: test\nstatus: active\npurpose: source isolation test\n",
                encoding="utf-8",
            )
        mem.ensure_layout(root, mem.MODE_NATIVE)
        return root

    def _write_atomic(self, path: Path, mem_id: str, scope: str, token: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"id: {mem_id}\n"
            "type: fact\n"
            f"scope: {scope}\n"
            "status: active\n"
            "importance: 3\n"
            "confidence: 1\n"
            "created_at: 2026-09-09T00:00:00+00:00\n"
            "updated_at: 2026-09-09T00:00:00+00:00\n"
            "---\n\n"
            f"# Memory\n\n{token}\n",
            encoding="utf-8",
        )

    def _source_spec(self, root: Path, kind: str, token: str):
        if kind == "profile":
            source = root / "operator/profile/preferences.md"
            cross = root / "workspaces/alpha/context/preferences.md"
            source_parent = root / "operator/profile"
            cross_parent = root / "workspaces/alpha/context"
            scope = "operator"
            workspace = None
            source.write_text(f"# Preferences\n\n{token}\n", encoding="utf-8")
            cross.write_text(f"# Alpha context\n\n{token}\n", encoding="utf-8")
        elif kind == "context":
            source = root / "workspaces/beta/context/CURRENT.md"
            cross = root / "workspaces/alpha/context/CURRENT.md"
            source_parent = root / "workspaces/beta/context"
            cross_parent = root / "workspaces/alpha/context"
            scope = "workspace:beta"
            workspace = "beta"
            source.write_text(f"# Beta current\n\n{token}\n", encoding="utf-8")
            cross.write_text(f"# Alpha current\n\n{token}\n", encoding="utf-8")
        elif kind == "decision":
            source = root / "workspaces/beta/decisions/log.md"
            cross = root / "workspaces/alpha/decisions/log.md"
            source_parent = root / "workspaces/beta/decisions"
            cross_parent = root / "workspaces/alpha/decisions"
            scope = "workspace:beta"
            workspace = "beta"
            source.write_text(f"# Beta decisions\n\n{token}\n", encoding="utf-8")
            cross.write_text(f"# Alpha decisions\n\n{token}\n", encoding="utf-8")
        elif kind == "memory_summary":
            source = root / "workspaces/beta/memory/SUMMARY.md"
            cross = root / "workspaces/alpha/memory/SUMMARY.md"
            source_parent = root / "workspaces/beta/memory"
            cross_parent = root / "workspaces/alpha/memory"
            scope = "workspace:beta"
            workspace = "beta"
            source.write_text(f"# Beta summary\n\n{token}\n", encoding="utf-8")
            cross.write_text(f"# Alpha summary\n\n{token}\n", encoding="utf-8")
        elif kind == "workspace_manifest":
            source = root / "workspaces/beta/WORKSPACE.yaml"
            cross = root / "workspaces/alpha/WORKSPACE.yaml"
            source_parent = root / "workspaces/beta"
            cross_parent = root / "workspaces/alpha"
            scope = "workspace:beta"
            workspace = "beta"
            source.write_text(
                f"id: beta\nname: Beta\ntype: test\nstatus: active\npurpose: {token}\n",
                encoding="utf-8",
            )
            cross.write_text(
                f"id: alpha\nname: Alpha\ntype: test\nstatus: active\npurpose: {token}\n",
                encoding="utf-8",
            )
        elif kind == "memory":
            source = root / "workspaces/beta/memory/atomic/2026/09/mem-source.md"
            cross = root / "workspaces/alpha/memory/atomic/2026/09/mem-source.md"
            source_parent = root / "workspaces/beta/memory/atomic"
            cross_parent = root / "workspaces/alpha/memory/atomic"
            scope = "workspace:beta"
            workspace = "beta"
            self._write_atomic(source, "mem-source", "workspace:beta", token)
            self._write_atomic(cross, "mem-source", "workspace:alpha", token)
        else:
            raise AssertionError(kind)

        return {
            "source": source,
            "cross": cross,
            "source_parent": source_parent,
            "cross_parent": cross_parent,
            "scope": scope,
            "workspace": workspace,
            "relative": source.relative_to(root).as_posix(),
        }

    def _recall(self, root: Path, token: str, spec):
        if spec["workspace"]:
            return mem.recall(token, workspace=spec["workspace"], root=root, mode=mem.MODE_NATIVE)
        return mem.recall(token, scope="operator", root=root, mode=mem.MODE_NATIVE)

    def _assert_existing_row_then_reject(self, root: Path, token: str, spec) -> None:
        mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)
        conn, _ = mem.connect_db(root, mem.MODE_NATIVE)
        row = conn.execute("SELECT id FROM items WHERE path=?", (spec["relative"],)).fetchone()
        conn.close()
        self.assertIsNotNone(row, spec["relative"])
        row_id = row["id"]

        recalled = self._recall(root, token, spec)
        self.assertNotIn(row_id, {item["id"] for item in recalled})

        conn, _ = mem.connect_db(root, mem.MODE_NATIVE)
        stale = conn.execute("SELECT id FROM items WHERE id=?", (row_id,)).fetchone()
        conn.close()
        self.assertIsNone(stale, f"invalid cached row was not purged: {spec['relative']}")

        mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)
        conn, _ = mem.connect_db(root, mem.MODE_NATIVE)
        reindexed = conn.execute("SELECT id FROM items WHERE path=?", (spec["relative"],)).fetchone()
        conn.close()
        self.assertIsNone(reindexed, f"invalid source was reindexed: {spec['relative']}")

    def _replace_file_with_symlink(self, source: Path, target: Path) -> None:
        source.unlink()
        try:
            source.symlink_to(target)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlinks unavailable: {exc}")

    def _replace_parent_with_symlink(self, source_parent: Path, target_parent: Path) -> None:
        shutil.rmtree(source_parent)
        try:
            source_parent.symlink_to(target_parent, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")

    def test_file_symlinks_cannot_cross_scope_or_escape_root_for_any_source_kind(self):
        for kind in SOURCE_KINDS:
            for target_type in ("cross_scope", "outside_root"):
                with self.subTest(kind=kind, target_type=target_type), tempfile.TemporaryDirectory() as temp:
                    base = Path(temp)
                    root = self._make_root(base)
                    token = f"file symlink isolation {kind} {target_type}"
                    spec = self._source_spec(root, kind, token)
                    mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)

                    if target_type == "cross_scope":
                        target = spec["cross"]
                    else:
                        target = base / f"outside-{kind}{spec['source'].suffix or '.txt'}"
                        target.write_text(token + "\n", encoding="utf-8")
                    self._replace_file_with_symlink(spec["source"], target)
                    self._assert_existing_row_then_reject(root, token, spec)

    def test_parent_directory_symlinks_cannot_cross_scope_or_escape_root_for_any_source_kind(self):
        for kind in SOURCE_KINDS:
            for target_type in ("cross_scope", "outside_root"):
                with self.subTest(kind=kind, target_type=target_type), tempfile.TemporaryDirectory() as temp:
                    base = Path(temp)
                    root = self._make_root(base)
                    token = f"parent symlink isolation {kind} {target_type}"
                    spec = self._source_spec(root, kind, token)
                    mem.rebuild(silent=True, root=root, mode=mem.MODE_NATIVE)

                    if target_type == "cross_scope":
                        target_parent = spec["cross_parent"]
                    else:
                        target_parent = base / f"outside-parent-{kind}"
                        target_parent.mkdir(parents=True)
                        remainder = spec["source"].relative_to(spec["source_parent"])
                        target_file = target_parent / remainder
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        if kind == "memory":
                            self._write_atomic(target_file, "mem-source", "workspace:beta", token)
                        else:
                            target_file.write_text(token + "\n", encoding="utf-8")

                    self._replace_parent_with_symlink(spec["source_parent"], target_parent)
                    self._assert_existing_row_then_reject(root, token, spec)


if __name__ == "__main__":
    unittest.main()
