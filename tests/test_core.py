# ruff: noqa: I001
from bootstrap import ROOT

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
from audio_engine import Mixer
from mix_export import export_mix, snapshot


class MixerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        self.root = Path(self.temp.name)
        self.stems = self.root / "stems"
        self.stems.mkdir()
        self.vocals = np.array(
            [[0.1, 0.2], [0.2, 0.3], [0.3, 0.4], [0.4, 0.5], [0.5, 0.6]], dtype="float32"
        )
        self.drums = np.full((5, 2), 0.1, dtype="float32")
        sf.write(self.stems / "vocals.wav", self.vocals, 10, subtype="FLOAT")
        sf.write(self.stems / "drums.wav", self.drums, 10, subtype="FLOAT")
        self.mixer = Mixer()
        self.mixer.load(self.stems)
        self.mixer.master = 1

    def tearDown(self):
        self.mixer.close()
        self.temp.cleanup()

    def test_shared_clock_and_end_padding(self):
        self.mixer.playing = True
        rendered = self.mixer.render(8)
        np.testing.assert_allclose(rendered[:5], self.vocals + self.drums)
        np.testing.assert_array_equal(rendered[5:], 0)
        self.assertEqual(self.mixer.position, 5)
        self.assertFalse(self.mixer.playing)

    def test_mute_solo_gain_and_master(self):
        self.mixer.configure("vocals", gain=0.5, solo=True)
        self.mixer.master = 0.5
        self.mixer.playing = True
        np.testing.assert_allclose(self.mixer.render(2), self.vocals[:2] * 0.25)
        self.mixer.configure("vocals", mute=True)
        np.testing.assert_array_equal(self.mixer.render(2), 0)
        self.mixer.solo.clear()
        self.mixer.seek(0)
        np.testing.assert_allclose(self.mixer.render(2), self.drums[:2] * 0.5)

    def test_loop_wraps_multiple_times_in_one_callback(self):
        self.mixer.configure("drums", mute=True)
        self.mixer.set_loop(0.1, 0.3, True)
        self.mixer.seek(0.4)
        self.mixer.playing = True
        expected = self.vocals[[1, 2, 1, 2, 1, 2, 1]]
        np.testing.assert_allclose(self.mixer.render(7), expected)
        self.assertEqual(self.mixer.position, 2)
        self.assertTrue(self.mixer.playing)

    def test_pause_seek_stop_and_invalid_loop(self):
        self.mixer.seek(-10)
        self.assertEqual(self.mixer.position, 0)
        self.mixer.seek(100)
        self.assertEqual(self.mixer.position, 5)
        self.mixer.pause()
        np.testing.assert_array_equal(self.mixer.render(3), 0)
        with self.assertRaises(ValueError):
            self.mixer.set_loop(0.3, 0.1, True)
        self.mixer.set_loop(0.1, 0.4, True)
        self.mixer.stop()
        self.assertEqual(self.mixer.position, 1)

    def test_clipping_protection(self):
        self.mixer.configure("vocals", gain=2)
        self.mixer.configure("drums", gain=2)
        self.mixer.playing = True
        result = self.mixer.render(5)
        self.assertLessEqual(float(result.max()), 1)
        self.assertGreater(self.mixer.peak, 1)

    def test_mismatched_stem_rejected_without_replacing_session(self):
        sf.write(self.stems / "bass.wav", np.ones((3, 2), dtype="float32"), 10)
        with self.assertRaises(ValueError):
            self.mixer.load(self.stems)
        self.assertEqual(self.mixer.frames, 5)
        self.assertNotIn("bass", self.mixer.tracks)

    def test_export_snapshot_matches_mix_and_preserves_live_state(self):
        self.mixer.configure("vocals", gain=0.4)
        self.mixer.configure("drums", mute=True)
        self.mixer.master = 0.5
        self.mixer.seek(0.2)
        self.mixer.set_loop(0.1, 0.3, True)
        copy = snapshot(self.mixer)
        path = export_mix(copy, self.root / "exports", "test")
        audio, rate = sf.read(path, always_2d=True)
        self.assertEqual(rate, 10)
        np.testing.assert_allclose(audio, self.vocals * 0.2, atol=2e-07)
        self.assertEqual(self.mixer.position, 2)
        self.assertEqual(self.mixer.loop, (1, 3))
        self.assertFalse(self.mixer.playing)
        second = export_mix(snapshot(self.mixer), self.root / "exports", "test")
        self.assertNotEqual(path, second)

    def test_selected_sections_skip_gaps_and_wrap_in_song_order(self):
        self.mixer.configure("drums", mute=True)
        self.mixer.set_ranges([(0.3, 0.5), (0, 0.1)])
        self.mixer.playing = True
        np.testing.assert_allclose(self.mixer.render(8), self.vocals[[0, 3, 4, 0, 3, 4, 0, 3]])
        self.mixer.set_ranges([(0, 0.1)])
        np.testing.assert_allclose(self.mixer.render(3), self.vocals[[0, 0, 0]])
        self.mixer.set_ranges([])
        self.mixer.seek(0.1)
        np.testing.assert_allclose(self.mixer.render(3), self.vocals[[1, 2, 3]])

    def test_overlapping_sections_play_each_whole_range(self):
        self.mixer.configure("drums", mute=True)
        self.mixer.set_ranges([(0, 0.3), (0.2, 0.5)])
        self.mixer.playing = True
        np.testing.assert_allclose(self.mixer.render(6), self.vocals[[0, 1, 2, 2, 3, 4]])
        with self.assertRaises(ValueError):
            self.mixer.set_ranges([(0, float("nan"))])
        with self.assertRaises(ValueError):
            self.mixer.set_ranges([(0.2, 0.2)])

    def test_legacy_piano_merges_into_other_once(self):
        piano = np.full((5, 2), 0.07, dtype="float32")
        other = np.full((5, 2), 0.12, dtype="float32")
        sf.write(self.stems / "piano.wav", piano, 10, subtype="FLOAT")
        sf.write(self.stems / "other.wav", other, 10, subtype="FLOAT")
        self.mixer.load(self.stems)
        self.assertNotIn("piano", self.mixer.tracks)
        np.testing.assert_allclose(self.mixer.tracks["other"], piano + other)
        self.mixer.load(self.stems)
        np.testing.assert_allclose(self.mixer.tracks["other"], piano + other)


if __name__ == "__main__":
    unittest.main(verbosity=2)
