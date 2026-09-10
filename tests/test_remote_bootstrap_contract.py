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


if __name__ == "__main__":
    unittest.main()
