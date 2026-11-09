# ruff: noqa: I001
from bootstrap import ROOT

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from audio_engine import Mixer
from song_library import Library, atomic_json, validate_session


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        self.root = Path(self.temp.name)
        self.source = self.root / "Original song.wav"
        sf.write(self.source, np.full((100, 2), 0.05, dtype="float32"), 100, subtype="FLOAT")
        self.original = self.source.read_bytes()
        self.fingerprint = hashlib.sha256(self.original).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def run_folder(self, name, guitar=False, source=None):
        folder = self.root / "outputs" / name
        folder.mkdir(parents=True)
        names = ["vocals", "drums", "bass", "other"] + (["guitar", "piano"] if guitar else [])
        for stem in names:
            sf.write(
                folder / (stem + ".wav"),
                np.full((100, 2), 0.05, dtype="float32"),
                100,
                subtype="FLOAT",
            )
        atomic_json(
            folder / "verification.json",
            dict(
                source=str(source or self.source),
                source_sha256=self.fingerprint,
                stems=[dict(stem=n, duration_seconds=1) for n in names],
            ),
        )
        return folder

    def test_discovery_groups_repeated_runs_and_prefers_guitar(self):
        old = self.run_folder("old")
        best = self.run_folder("best", True)
        library = Library(self.root)
        self.assertEqual(len(library.entries), 1)
        entry = library.entries[0]
        self.assertEqual(library.resolve(entry["output"]), best)
        self.assertEqual(len(entry["runs"]), 2)
        copy = self.root / "renamed.wav"
        copy.write_bytes(self.original)
        self.assertEqual(library.find_source(copy)["id"], entry["id"])
        self.assertTrue(old.exists())

    def test_legacy_sections_and_loop_migrate_to_autosaved_session(self):
        folder = self.run_folder("six", True)
        atomic_json(
            self.root / "old.wavesplit",
            dict(
                version=1,
                source=self.source.name,
                output="outputs/six",
                master=0.6,
                position=0.2,
                tracks={},
                markers=[dict(time=0, name="Intro"), dict(time=0.4, name="Verse")],
                loop=dict(start=0, end=0.4, enabled=True),
            ),
        )
        library = Library(self.root)
        entry = library.entries[0]
        data = library.read_session(entry, 1)
        self.assertEqual(len(data["sections"]), 2)
        self.assertEqual(data["sections"][1]["end"], 1)
        self.assertTrue(data["sections"][0]["enabled"])
        mixer = Mixer()
        mixer.load(folder)
        mixer.configure("guitar", mute=True)
        library.save_session(entry, mixer, data["sections"])
        restored = Library(self.root).read_session(entry, 1)
        self.assertTrue(restored["tracks"]["guitar"]["mute"])
        self.assertNotIn("piano", restored["tracks"])
        mixer.close()

    def test_delete_moves_generated_runs_and_session_but_keeps_original(self):
        folder = self.run_folder("six", True)
        library = Library(self.root)
        entry = library.entries[0]
        mixer = Mixer()
        mixer.load(folder)
        library.save_session(entry, mixer, [])
        mixer.close()
        trash = library.remove(entry)
        self.assertFalse(folder.exists())
        self.assertFalse(library.entries)
        self.assertTrue((trash / "restore.json").exists())
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertFalse(Library(self.root).entries, "Deleted runs must not be rediscovered")

    def test_original_inside_output_folder_blocks_deletion(self):
        folder = self.run_folder("danger", True)
        source = folder / "original.wav"
        source.write_bytes(self.original)
        report = json.loads((folder / "verification.json").read_text())
        report["source"] = str(source)
        atomic_json(folder / "verification.json", report)
        library = Library(self.root)
        with self.assertRaises(ValueError):
            library.remove(library.entries[0])
        self.assertTrue(source.exists())
        self.assertEqual(len(library.entries), 1)

    def test_failed_delete_rolls_back_moved_files(self):
        from unittest.mock import patch

        folder = self.run_folder("six", True)
        library = Library(self.root)
        entry = library.entries[0]
        with patch.object(library, "save", side_effect=OSError("simulated save failure")):
            with self.assertRaises(OSError):
                library.remove(entry)
        self.assertTrue(folder.exists())
        self.assertEqual(len(library.entries), 1)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_five_file_migration_sums_piano_and_preserves_earlier_audio(self):
        folder = self.run_folder("six", True)
        library = Library(self.root)
        entry = library.entries[0]
        original_other = (folder / "other.wav").read_bytes()
        destination = library.ensure_five_tracks(entry)
        self.assertEqual(len(list(destination.glob("*.wav"))), 5)
        self.assertFalse((destination / "piano.wav").exists())
        other, rate = sf.read(destination / "other.wav")
        np.testing.assert_allclose(other, 0.1, atol=1e-07)
        self.assertEqual((folder / "other.wav").read_bytes(), original_other)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(library.ensure_five_tracks(entry), destination)

    def test_invalid_session_rejected(self):
        with self.assertRaises(ValueError):
            validate_session(dict(version=2, sections=[dict(name="x", start=0.7, end=0.2)]), 1)
        with self.assertRaises(ValueError):
            validate_session(dict(version=2, master=float("nan")), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
