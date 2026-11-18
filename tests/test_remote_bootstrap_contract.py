import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RemoteBootstrapContractTests(unittest.TestCase):
    def test_shell_bootstrap_fetches_all_installer_modules(self):
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        for name in ("install.py", "install_engine.py", "os_compat.py"):
            self.assertIn(name, text)

    def test_powershell_bootstrap_fetches_all_installer_modules(self):
        text = (ROOT / "install.ps1").read_text(encoding="utf-8")
        for name in ("install.py", "install_engine.py", "os_compat.py"):
            self.assertIn(name, text)

    def test_bootstraps_use_accepted_release_not_moving_main(self):
        for name in ("install.sh", "install.ps1"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("release/component-release.json", text, name)
            self.assertIn("AI_VERSE_MEMORY_RELEASE_REF", text, name)
            self.assertNotRegex(text, r"AI-Verse-Memory/main/scripts", name)
        engine = (ROOT / "scripts" / "install_engine.py").read_text(encoding="utf-8")
        self.assertIn("release/component-release.json", engine)
        self.assertNotIn('"main"', engine.replace('DESCRIPTOR_REF = "main"', ""))
        self.assertNotIn("or \"main\"", engine)

    def test_release_descriptor_names_an_accepted_commit(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import install_engine
        finally:
            sys.path.pop(0)
        text = (ROOT / "release" / "component-release.json").read_text(encoding="utf-8")
        revision = json.loads(text)["revision"]
        self.assertRegex(revision, r"^[0-9a-f]{40}$")
        self.assertEqual(install_engine.accepted_revision(text), revision)
        with self.assertRaises(RuntimeError):
            install_engine.accepted_revision(json.dumps({"revision": revision, "release_status": "candidate"}))
        with self.assertRaises(RuntimeError):
            install_engine.accepted_revision(json.dumps({"revision": "main", "release_status": "accepted"}))

    def test_engine_url_follows_accepted_revision_with_dev_overrides(self):
        import os
        from unittest import mock
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import install_engine
        finally:
            sys.path.pop(0)
        revision = json.loads((ROOT / "release" / "component-release.json").read_text(encoding="utf-8"))["revision"]
        with mock.patch.dict(os.environ, {"AI_VERSE_MEMORY_RELEASE_REF": revision}, clear=False):
            os.environ.pop("AI_VERSE_MEMORY_BASE_URL", None)
            install_engine._RESOLVED_BASE_URL = None
            self.assertTrue(install_engine.resolve_base_url().endswith("/" + revision))
        with mock.patch.dict(os.environ, {"AI_VERSE_MEMORY_BASE_URL": "http://x.test/base/"}):
            self.assertEqual(install_engine.resolve_base_url(), "http://x.test/base")
        install_engine._RESOLVED_BASE_URL = None


STUB = """#!/bin/sh
# stub curl: args -fsSL URL -o FILE
URL="$2"; OUT="$4"
case "$MODE" in
  down) exit 22 ;;
  *) printf '%s' "$BODY" > "$OUT" ;;
esac
echo "$URL" >> "$STUBLOG"
"""


@unittest.skipIf(sys.platform == "win32", "install.sh stub curl tests need a POSIX shell; Windows uses install.ps1")
class BootstrapRunTests(unittest.TestCase):
    def run_sh(self, mode, body=""):
        import os, subprocess, tempfile
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "bin").mkdir()
            stub = d / "bin" / "curl"
            stub.write_text(STUB, encoding="utf-8")
            stub.chmod(0o755)
            target = d / "target"
            target.mkdir()
            script = d / "install.sh"  # not in a checkout, so it takes the remote path
            script.write_text((ROOT / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
            env = dict(os.environ, PATH=f"{d / 'bin'}:{os.environ['PATH']}", MODE=mode, BODY=body,
                       STUBLOG=str(d / "log"), AI_VERSE_MEMORY_TARGET=str(target), TMPDIR=str(d))
            env.pop("AI_VERSE_MEMORY_RELEASE_REF", None)
            proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            installed = [p.name for p in target.iterdir()]
            log = (d / "log").read_text(encoding="utf-8") if (d / "log").exists() else ""
            return proc, installed, log

    def assert_refused(self, mode, body, message):
        proc, installed, log = self.run_sh(mode, body)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(message, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertEqual(installed, [])
        self.assertNotIn("/main/scripts", log)

    def test_unreachable(self):
        self.assert_refused("down", "", "Check your internet connection")

    def test_not_json(self):
        self.assert_refused("ok", "<html>", "release file is not valid")

    def test_not_accepted(self):
        self.assert_refused("ok", json.dumps({"release_status": "candidate", "revision": "a" * 40}), "No accepted release")

    def test_bad_revision(self):
        for rev in ("main", "A" * 40, "abc"):
            self.assert_refused("ok", json.dumps({"release_status": "accepted", "revision": rev}), "does not name a valid release")

    def test_engine_fails_plainly_without_fallback(self):
        import contextlib, io
        from unittest import mock
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import install_engine
        finally:
            sys.path.pop(0)
        install_engine._RESOLVED_BASE_URL = None
        err = io.StringIO()
        with mock.patch.dict("os.environ", {"AI_VERSE_MEMORY_RELEASE_REF": "", "AI_VERSE_MEMORY_BASE_URL": ""}), \
                mock.patch("urllib.request.urlopen", side_effect=OSError("down")), \
                contextlib.redirect_stderr(err), self.assertRaises(SystemExit) as cm:
            install_engine.resolve_base_url()
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("internet connection", err.getvalue())
        self.assertIsNone(install_engine._RESOLVED_BASE_URL)


if __name__ == "__main__":
    unittest.main()
