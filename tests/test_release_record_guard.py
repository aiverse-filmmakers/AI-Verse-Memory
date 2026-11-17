import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_release_record.py"
V = "1.2.3"


def record(revision, version=V, run_ci="111", run_acc="222"):
    def ev(run):
        return {"kind": "k", "status": "pass", "revision": revision, "run_id": run, "url": "u"}
    return {
        "schema_version": "ai-verse.component-release/v1",
        "component_id": "ai-verse-memory",
        "version": version,
        "revision": revision,
        "release_status": "accepted",
        "evidence": {"ci": [ev(run_ci)], "acceptance": [ev(run_acc)]},
    }


@unittest.skipIf(sys.platform == "win32", "builds throwaway git repos with a POSIX temp layout; Windows is covered by the Ubuntu run")
class ReleaseRecordGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git("init", "-q")

    def git(self, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid")
        return subprocess.run(["git", "-C", str(self.repo), *args], env=env, capture_output=True, text=True, check=True).stdout.strip()

    def write_holders(self, version):
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "manifest.json").write_text(json.dumps({"name": "m", "version": version}, indent=2) + "\n")
        (self.repo / "SKILL.md").write_text("---\nname: m\nversion: %s\n---\n" % version)
        (self.repo / "scripts" / "memory_engine.py").write_text('VERSION = "%s"\n' % version)
        (self.repo / "scripts" / "install_engine.py").write_text('VERSION = "%s"\n' % version)
        (self.repo / "README.md").write_text("Current development version: **%s**. Pinned.\n" % version)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def check(self, rec=None, raw=None, strict=True, summary=None):
        (self.repo / "release").mkdir(exist_ok=True)
        path = self.repo / "release" / "component-release.json"
        path.write_text(raw if raw is not None else json.dumps(rec))
        cmd = [sys.executable, "-I", str(SCRIPT), "--repo", str(self.repo)] + (["--strict"] if strict else [])
        env = dict(os.environ)
        env.pop("RELEASE_GUARD_STRICT", None)
        if summary:
            env["GITHUB_STEP_SUMMARY"] = str(summary)
        return subprocess.run(cmd, capture_output=True, text=True, env=env)

    def test_agreeing_record_passes(self):
        self.write_holders(V)
        sha = self.commit()
        proc = self.check(record(sha))
        self.assertEqual(proc.returncode, 0, proc.stdout)

    def test_reads_code_at_accepted_commit_not_head(self):
        self.write_holders(V)
        sha = self.commit()
        self.write_holders("9.9.9")  # head drifts, accepted commit is still fine
        self.commit("later")
        self.assertEqual(self.check(record(sha)).returncode, 0)

    def test_holder_disagreeing_at_accepted_commit_fails(self):
        self.write_holders(V)
        (self.repo / "scripts" / "install_engine.py").write_text('VERSION = "0.0.1"\n')
        sha = self.commit()
        proc = self.check(record(sha))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("scripts/install_engine.py says 0.0.1", proc.stdout)

    def test_fixed_at_head_but_wrong_at_accepted_commit_still_fails(self):
        self.write_holders("0.0.1")
        sha = self.commit()
        self.write_holders(V)
        self.commit("fix later")
        self.assertEqual(self.check(record(sha)).returncode, 1)

    def test_missing_commit_fails(self):
        self.write_holders(V)
        self.commit()
        proc = self.check(record("a" * 40))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not exist", proc.stdout)

    def test_same_run_id_twice_fails(self):
        self.write_holders(V)
        sha = self.commit()
        proc = self.check(record(sha, run_ci="777", run_acc="777"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("listed twice", proc.stdout)

    def test_malformed_records_fail_without_traceback(self):
        self.write_holders(V)
        self.commit()
        for raw in ("not json", "[]", json.dumps({"schema_version": "x"}),
                    json.dumps(dict(record("b" * 40), revision="short"))):
            proc = self.check(raw=raw)
            self.assertEqual(proc.returncode, 1, raw)
            self.assertNotIn("Traceback", proc.stderr)

    def test_default_mode_warns_loudly_and_exits_zero(self):
        self.write_holders("0.0.1")
        sha = self.commit()
        summary = self.repo / "summary.md"
        proc = self.check(record(sha, run_ci="9", run_acc="9"), strict=False, summary=summary)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("::warning", proc.stdout)
        self.assertIn("manifest.json says 0.0.1", proc.stdout)
        text = summary.read_text()
        self.assertIn("listed twice", text)
        self.assertIn("scripts/memory_engine.py says 0.0.1", text)

    def test_default_mode_malformed_json_only_warns(self):
        self.write_holders(V)
        self.commit()
        proc = self.check(raw="not json", strict=False)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("::warning", proc.stdout)

    def test_strict_env_var_blocks(self):
        self.write_holders("0.0.1")
        sha = self.commit()
        self.check(record(sha), strict=False)
        env = dict(os.environ, RELEASE_GUARD_STRICT="1")
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", str(self.repo)],
                              capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 1)

    def test_far_ahead_only_warns(self):
        self.write_holders(V)
        sha = self.commit()
        for i in range(51):
            (self.repo / "f.txt").write_text(str(i))
            self.commit("c%d" % i)
        proc = self.check(record(sha))
        self.assertEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("::warning", proc.stdout)
        self.assertIn("51 commits", proc.stdout)


if __name__ == "__main__":
    unittest.main()
