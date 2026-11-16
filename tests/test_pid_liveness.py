import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MODULES = {
    "public_beta": _load("pid_liveness_public_beta", "public_beta.py"),
    "install_engine": _load("pid_liveness_install_engine", "install_engine.py"),
}


class PidLivenessTests(unittest.TestCase):
    def test_windows_branch_never_calls_os_kill(self):
        for name, module in MODULES.items():
            for open_result, exit_code, expected in ((1234, 259, True), (1234, 0, False), (0, None, False)):
                with self.subTest(module=name, handle=open_result, code=exit_code):
                    fake_windll_cls = mock.Mock()
                    k32 = fake_windll_cls.return_value
                    k32.OpenProcess.return_value = open_result

                    def get_exit(handle, ref, _code=exit_code):
                        ref._obj.value = _code
                        return 1

                    k32.GetExitCodeProcess.side_effect = get_exit
                    with mock.patch.object(module.sys, "platform", "win32"), \
                         mock.patch("ctypes.WinDLL", fake_windll_cls, create=True), \
                         mock.patch("ctypes.get_last_error", return_value=87, create=True), \
                         mock.patch.object(module.os, "kill", side_effect=AssertionError("os.kill must not run on Windows")) as kill:
                        self.assertIs(module._pid_alive(4321), expected)
                        kill.assert_not_called()
                    fake_windll_cls.assert_called_once_with("kernel32", use_last_error=True)
                    k32.OpenProcess.assert_called_once_with(0x1000, False, 4321)
                    if open_result:
                        k32.CloseHandle.assert_called_once_with(open_result)

    def test_windows_access_denied_means_alive(self):
        for name, module in MODULES.items():
            with self.subTest(module=name):
                windll_cls = mock.Mock()
                windll_cls.return_value.OpenProcess.return_value = 0
                with mock.patch.object(module.sys, "platform", "win32"), \
                     mock.patch("ctypes.WinDLL", windll_cls, create=True), \
                     mock.patch("ctypes.get_last_error", return_value=5, create=True), \
                     mock.patch.object(module.os, "kill", side_effect=AssertionError("os.kill")):
                    self.assertTrue(module._pid_alive(4321))

    @unittest.skipIf(sys.platform == "win32", "POSIX only")
    def test_posix_live_and_dead_pids(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        dead_pid = proc.pid
        for name, module in MODULES.items():
            with self.subTest(module=name):
                self.assertTrue(module._pid_alive(os.getpid()))
                self.assertFalse(module._pid_alive(dead_pid))
                self.assertFalse(module._pid_alive(0))
                self.assertFalse(module._pid_alive(-5))
                with mock.patch.object(module.os, "kill", side_effect=PermissionError):
                    self.assertTrue(module._pid_alive(99999))
                with mock.patch.object(module.os, "kill", side_effect=ProcessLookupError):
                    self.assertFalse(module._pid_alive(99999))


if __name__ == "__main__":
    unittest.main()
