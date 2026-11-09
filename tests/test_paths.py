# ruff: noqa: I001
from bootstrap import ROOT

import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


def load_paths():
    spec = importlib.util.spec_from_file_location("isolated_paths", ROOT / "app/paths.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimePathTests(unittest.TestCase):
    def test_source_keeps_existing_project_data(self):
        with patch.dict(os.environ):
            os.environ.pop("TRACK_SPLITTER_DATA_DIR", None)
            paths = load_paths()
            self.assertEqual(paths.DATA_ROOT, ROOT)
            self.assertEqual(paths.ASSET_DIR, ROOT / "assets")

    def test_frozen_app_keeps_writes_outside_bundle(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as tmp:
            base = Path(tmp)
            with (
                patch.object(sys, "frozen", True, create=True),
                patch.object(sys, "_MEIPASS", str(base / "read-only-bundle"), create=True),
                patch.dict(os.environ, {"TRACK_SPLITTER_DATA_DIR": str(base / "user-data")}),
            ):
                paths = load_paths()
                paths.configure_runtime()
                self.assertEqual(paths.ASSET_DIR, base / "read-only-bundle/assets")
                self.assertTrue((base / "user-data/.tmp").is_dir())
                self.assertFalse((base / "read-only-bundle").exists())
                self.assertEqual(Path(os.environ["TORCH_HOME"]), base / "user-data/.cache/torch")

    def test_windows_binary_uses_per_user_local_appdata(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(ROOT / ".tmp/bundle"), create=True),
            patch.object(sys, "platform", "win32"),
            patch.dict(os.environ, {"LOCALAPPDATA": str(ROOT / ".tmp/profile")}),
        ):
            os.environ.pop("TRACK_SPLITTER_DATA_DIR", None)
            paths = load_paths()
            self.assertEqual(paths.DATA_ROOT, ROOT / ".tmp/profile/TrackSplitter")


if __name__ == "__main__":
    unittest.main()
