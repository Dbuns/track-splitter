# ruff: noqa: I001
from bootstrap import ROOT

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf
from audio_engine import Mixer
from mix_export import export_mix, snapshot
from tempo_backend import estimate_bpm, prepare_tempo


class TempoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".tmp")
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_click_track_bpm(self):
        rate = 22050
        for bpm in (90, 120, 180):
            audio = np.zeros(rate * 16, dtype="float32")
            click = np.hanning(450).astype("float32") * np.sin(np.arange(450) * 0.6)
            for i in range(0, len(audio) - len(click), round(rate * 60 / bpm)):
                audio[i : i + len(click)] += click
            result = estimate_bpm(audio, rate)
            self.assertIsNotNone(result)
            self.assertLess(abs(result - bpm), 3, (bpm, result))

    def test_silence_has_no_bpm(self):
        self.assertIsNone(estimate_bpm(np.zeros((441000, 2), dtype="float32"), 44100))

    def test_pitch_duration_and_shared_channel_alignment(self):
        rate = 22050
        tone = (np.sin(2 * np.pi * 440 * np.arange(rate * 2) / rate) * 0.03).astype("float32")
        tracks = {
            "vocals": np.column_stack((tone, tone)),
            "drums": np.column_stack((tone * 2, tone * 3)),
        }
        out = prepare_tempo(tracks, rate, 0.8, self.root / "cache")
        self.assertEqual(out["vocals"].shape, (round(len(tone) / 0.8), 2))
        np.testing.assert_allclose(out["drums"][:, 0], out["vocals"][:, 0] * 2, atol=1e-06)
        y = out["vocals"][:, 0]
        frequency = np.fft.rfftfreq(len(y), 1 / rate)[np.argmax(np.abs(np.fft.rfft(y)))]
        self.assertLess(abs(frequency - 440), 2)
        fast = prepare_tempo(tracks, rate, 1.25, self.root / "cache")
        self.assertEqual(len(fast["vocals"]), round(len(tone) / 1.25))
        y = fast["vocals"][:, 0]
        frequency = np.fft.rfftfreq(len(y), 1 / rate)[np.argmax(np.abs(np.fft.rfft(y)))]
        self.assertLess(abs(frequency - 440), 2)
        with patch(
            "tempo_backend.subprocess.run", side_effect=AssertionError("Cache should avoid FFmpeg")
        ):
            again = prepare_tempo(tracks, rate, 0.8, self.root / "cache")
            np.testing.assert_array_equal(out["vocals"], again["vocals"])

    def mixer(self):
        m = Mixer()
        m.rate = 100
        m.frames = 8
        a = np.arange(8, dtype="float32")[:, None] * 0.01
        m.tracks = {"vocals": np.repeat(a, 2, axis=1)}
        m.gains = {"vocals": 1}
        m.master = 1
        prepared = {"vocals": np.repeat(m.tracks["vocals"], 2, axis=0)}
        m.set_tempo_tracks(prepared, 0.5)
        m.playing = True
        return (m, prepared)

    def test_source_position_seek_and_loop_at_slow_speed(self):
        m, prepared = self.mixer()
        m.render(6)
        self.assertEqual(m.position, 3)
        m.seek(0.04)
        self.assertEqual(m._tempo.position, 8)
        m.set_ranges([(0.02, 0.05)])
        m.seek(0.02)
        np.testing.assert_allclose(m.render(8), prepared["vocals"][[4, 5, 6, 7, 8, 9, 4, 5]])
        self.assertEqual(m.position, 3)

    def test_original_speed_restores_source_tracks(self):
        m, _ = self.mixer()
        m.seek(0.03)
        m.set_tempo_tracks()
        self.assertEqual(m.tempo_factor, 1)
        np.testing.assert_allclose(m.render(2), m.tracks["vocals"][3:5])

    def test_export_uses_practice_speed_without_changing_live_clock(self):
        m, prepared = self.mixer()
        m.seek(0.03)
        path = export_mix(snapshot(m), self.root / "exports", "slow")
        data, rate = sf.read(path, always_2d=True)
        self.assertEqual(data.shape, (16, 2))
        self.assertEqual(rate, 100)
        np.testing.assert_allclose(data, prepared["vocals"], atol=2e-07)
        self.assertEqual(m.position, 3)

    def test_nested_drums_export_at_changed_speed(self):
        m = Mixer()
        m.rate = 100
        m.frames = 8
        m.master = 0.5
        values = {
            "vocals": 0.1,
            "drums": 0.5,
            "kick": 0.01,
            "snare": 0.02,
            "cymbals": 0.03,
            "toms": 0.04,
        }
        m.tracks = {n: np.full((8, 2), v, dtype="float32") for n, v in values.items()}
        m.gains = {n: 1 for n in values}
        m.drum_children = ("kick", "snare", "cymbals", "toms")
        m.gains["drums"] = 0.8
        m.solo = {"snare"}
        m.set_tempo_tracks({n: np.repeat(a, 2, axis=0) for n, a in m.tracks.items()}, 0.5)
        path = export_mix(snapshot(m), self.root / "exports", "slow-drums")
        data, rate = sf.read(path, always_2d=True)
        self.assertEqual(data.shape, (16, 2))
        np.testing.assert_allclose(data, 0.02 * 0.8 * 0.5, atol=2e-07)

    def test_invalid_factor_rejected(self):
        with self.assertRaises(ValueError):
            prepare_tempo({"x": np.zeros((100, 2))}, 100, 0.2, self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
