# ruff: noqa: I001
from bootstrap import ROOT

import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import drum_separator


class DrumModelDownloadTests(unittest.TestCase):
    def test_verified_model_is_installed_atomically(self):
        data = b"model fixture bytes"
        expected = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as tmp:
            destination = Path(tmp) / "models/drums.th"

            def download(**kwargs):
                target = Path(kwargs["output"])
                target.write_bytes(data)
                self.assertFalse(destination.exists())
                return str(target)

            with (
                patch.object(drum_separator, "MODEL", destination),
                patch.object(drum_separator, "MODEL_SHA256", expected),
                patch.dict(sys.modules, {"gdown": SimpleNamespace(download=download)}),
            ):
                drum_separator.download_model(lambda message: None)
            self.assertEqual(destination.read_bytes(), data)
            self.assertEqual(list(destination.parent.glob("*.download")), [])

    def test_bad_download_does_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as tmp:
            destination = Path(tmp) / "drums.th"
            destination.write_bytes(b"existing")

            def download(**kwargs):
                target = Path(kwargs["output"])
                target.write_bytes(b"corrupt download")
                return str(target)

            with (
                patch.object(drum_separator, "MODEL", destination),
                patch.dict(sys.modules, {"gdown": SimpleNamespace(download=download)}),
                self.assertRaises(ValueError),
            ):
                drum_separator.download_model(lambda message: None)
            self.assertEqual(destination.read_bytes(), b"existing")
            self.assertEqual(list(destination.parent.glob("*.download")), [])

    def test_interrupted_download_leaves_no_cached_model(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".tmp") as tmp:
            destination = Path(tmp) / "drums.th"
            with (
                patch.object(drum_separator, "MODEL", destination),
                patch.dict(
                    sys.modules, {"gdown": SimpleNamespace(download=Mock(return_value=None))}
                ),
                self.assertRaises(ValueError),
            ):
                drum_separator.download_model(lambda message: None)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
