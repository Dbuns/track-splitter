# ruff: noqa: I001
from bootstrap import ROOT

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "win32", "Windows batch scripts")
class WindowsLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ("Setup_Track_Splitter.bat", "Start_Track_Splitter.bat"):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / "bin").mkdir()
        self.env = os.environ.copy()
        self.env["PATH"] = (
            str(self.root / "bin") + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
        )

    def run_script(self, name):
        return subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", name],
            cwd=self.root,
            env=self.env,
            input="\n\n",
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_missing_python_gives_specific_install_instructions(self):
        for name in ("py", "python"):
            (self.root / "bin" / (name + ".bat")).write_text("@exit /b 1\n")
        result = self.run_script("Setup_Track_Splitter.bat")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("64-bit Python 3.12", result.stdout)
        self.assertIn("python.org/downloads/windows", result.stdout)
        self.assertFalse((self.root / ".venv").exists())

    def test_selects_py312_before_default_python(self):
        (self.root / "bin/py.bat").write_text(
            '@echo off\necho %*>>selected.txt\nif "%2"=="-c" exit /b 0\nexit /b 23\n'
        )
        (self.root / "bin/python.bat").write_text("@echo default>>wrong-python.txt\nexit /b 1\n")
        result = self.run_script("Setup_Track_Splitter.bat")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("-3.12 -m venv .venv", (self.root / "selected.txt").read_text())
        self.assertFalse((self.root / "wrong-python.txt").exists())
        self.assertIn("Setup did not complete", result.stdout)

    def test_launcher_reports_missing_environment(self):
        result = self.run_script("Start_Track_Splitter.bat")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Run Setup_Track_Splitter.bat", result.stdout)

    def test_launcher_reports_partial_environment_before_opening_app(self):
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", str(self.root / ".venv")],
            check=True,
            capture_output=True,
        )
        (self.root / "app").mkdir()
        for name in ("check_environment.py", "requirements.txt"):
            shutil.copy2(ROOT / "app" / name, self.root / "app" / name)
        (self.root / "app/track_splitter.py").write_text(
            'from pathlib import Path\nPath("unexpected-launch").touch()\n'
        )
        result = self.run_script("Start_Track_Splitter.bat")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("setup is incomplete", result.stdout)
        self.assertIn("Missing dependency", result.stdout)
        self.assertFalse((self.root / "unexpected-launch").exists())


if __name__ == "__main__":
    unittest.main()
