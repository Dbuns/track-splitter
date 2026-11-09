# ruff: noqa: I001
from bootstrap import ROOT

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from audio_engine import DRUM_CHILDREN, Mixer
from mix_export import export_mix, snapshot


class DrumBusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        self.root = Path(self.temp.name)
        self.song = self.root / "song"
        self.song.mkdir()
        self.parts = self.song / "drum tracks"
        self.parts.mkdir()
        for name, value in (("vocals", 0.1), ("drums", 0.5)):
            sf.write(
                self.song / (name + ".wav"),
                np.full((8, 2), value, dtype="float32"),
                100,
                subtype="FLOAT",
            )
        for name, value in zip(DRUM_CHILDREN, (0.01, 0.02, 0.03, 0.04)):
            sf.write(
                self.parts / (name + ".wav"),
                np.full((8, 2), value, dtype="float32"),
                100,
                subtype="FLOAT",
            )
        self.mix = Mixer()
        self.mix.load(self.song)
        self.mix.load_drum_children(self.parts)
        self.mix.master = 1
        self.mix.playing = True

    def tearDown(self):
        self.mix.close()
        self.temp.cleanup()

    def expect(self, value):
        np.testing.assert_allclose(self.mix.render(1), value, atol=1e-07)

    def test_replaces_parent_without_double_playback(self):
        self.expect(0.2)

    def test_parent_gain_and_child_gain_multiply(self):
        self.mix.configure("drums", gain=0.5)
        self.mix.configure("kick", gain=2)
        self.expect(0.155)

    def test_parent_mute_blocks_whole_kit(self):
        self.mix.configure("drums", mute=True)
        self.expect(0.1)

    def test_child_mute_changes_only_that_part(self):
        self.mix.configure("kick", mute=True)
        self.expect(0.19)

    def test_child_solo_is_global(self):
        self.mix.configure("kick", solo=True)
        self.expect(0.01)

    def test_parent_solo_includes_kit(self):
        self.mix.configure("drums", solo=True)
        self.expect(0.1)

    def test_main_and_child_solos_combine(self):
        self.mix.configure("vocals", solo=True)
        self.mix.configure("snare", solo=True)
        self.expect(0.12)

    def test_muted_parent_overrides_child_solo(self):
        self.mix.configure("drums", mute=True)
        self.mix.configure("kick", solo=True)
        self.expect(0)

    def test_export_uses_child_bus_and_ignores_practice_loop(self):
        self.mix.configure("kick", solo=True)
        self.mix.set_ranges([(0.01, 0.02)])
        path = export_mix(snapshot(self.mix), self.root / "exports", "nested")
        audio, rate = sf.read(path, always_2d=True)
        self.assertEqual(audio.shape, (8, 2))
        self.assertEqual(rate, 100)
        np.testing.assert_allclose(audio, 0.01, atol=2e-07)

    def test_invalid_parts_do_not_replace_loaded_bus(self):
        sf.write(self.parts / "snare.wav", np.zeros((3, 2)), 100)
        before = self.mix.tracks["snare"]
        with self.assertRaises(ValueError):
            self.mix.load_drum_children(self.parts)
        self.assertIs(self.mix.tracks["snare"], before)

    def test_loading_another_song_clears_children(self):
        self.mix.load(self.song)
        self.assertFalse(self.mix.drum_children)
        self.assertNotIn("kick", self.mix.tracks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
