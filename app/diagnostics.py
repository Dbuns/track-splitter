"""Opt-in executable diagnostics using generated audio and an isolated library."""

import json
import tempfile
import time
import traceback
from pathlib import Path

from paths import ASSET_DIR, DATA_ROOT


def run(report_path, models=False):
    report_path = Path(report_path).resolve()
    result = {"ok": False, "model_inference": models, "checks": []}
    started = time.perf_counter()
    try:
        import imageio_ffmpeg
        import numpy as np
        import soundfile as sf
        import torch
        from audio_engine import Mixer
        from drum_separator import separate_drums, sha256
        from mix_export import export_mix, snapshot
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
        from separator import separate
        from song_library import Library, atomic_json
        from tempo_backend import estimate_bpm, prepare_tempo
        from track_splitter import Window

        app = QApplication.instance() or QApplication([])
        assert not QIcon(str(ASSET_DIR / "track_splitter.ico")).isNull()
        result["checks"].append("bundled app icon")
        result["ffmpeg"] = imageio_ffmpeg.get_ffmpeg_version()
        result["torch"] = torch.__version__
        with tempfile.TemporaryDirectory(prefix="executable-check-", dir=DATA_ROOT / ".tmp") as tmp:
            root = Path(tmp)
            rate, seconds = 44100, 8
            t = np.arange(rate * seconds) / rate
            pulse = np.zeros(len(t), dtype="float32")
            beat = (np.hanning(1800) * np.sin(np.arange(1800) * 0.6) * 0.15).astype("float32")
            for offset in range(0, len(t) - len(beat), rate // 2):
                pulse[offset : offset + len(beat)] += beat
            mono = (0.04 * np.sin(2 * np.pi * 220 * t) + pulse).astype("float32")
            audio = np.column_stack((mono, mono))
            source = root / "Generated practice audio.wav"
            sf.write(source, audio, rate, subtype="FLOAT")
            original_hash = sha256(source)
            if models:
                folder = separate(source, model_name="htdemucs_6s", output_root=root / "outputs")
                parts = separate_drums(folder / "drums.wav")
                result["checks"].append("real five-stem Demucs and four-stem drumsep inference")
            else:
                folder = root / "outputs/song"
                folder.mkdir(parents=True)
                names = ("vocals", "drums", "bass", "guitar", "other")
                for name in names:
                    sf.write(folder / (name + ".wav"), audio / 5, rate, subtype="FLOAT")
                atomic_json(
                    folder / "verification.json",
                    dict(
                        source=str(source),
                        source_sha256=original_hash,
                        stems=[dict(stem=n, duration_seconds=seconds) for n in names],
                    ),
                )
                parts = None
            library = Library(root)
            entry = library.entries[0]
            atomic_json(
                library.resolve(entry["session"]),
                dict(
                    version=2,
                    base_bpm=120,
                    tempo_factor=1,
                    sections=[],
                ),
            )
            mixer = Mixer()
            mixer.load(folder)
            if parts:
                mixer.load_drum_children(parts)
                assert len(mixer.tracks) == 9
            assert estimate_bpm(audio, rate) is not None
            prepared = prepare_tempo(mixer.tracks, rate, 0.8, root / "tempo-cache")
            mixer.set_tempo_tracks(prepared, 0.8)
            mixer.master = 0.5
            mixer.playing = True
            assert np.isfinite(mixer.render(1024)).all()
            mixer.pause()
            exported = export_mix(snapshot(mixer), folder, "diagnostic_export")
            assert sf.info(exported).frames == round(rate * seconds / 0.8)
            mixer.master = 0
            mixer.play()
            time.sleep(0.15)
            mixer.pause()
            mixer.close()
            result["checks"].append("muted PortAudio output stream")
            result["checks"].append("tempo, FFmpeg, shared mixing and WAV export")
            window = Window(root)
            window.show()
            app.processEvents()
            assert window.current and len(window.track_controls) == 5
            if parts:
                window.drum_toggle.click()
                app.processEvents()
                assert len(window.track_controls) == 9
            window.track_controls["vocals"][0].setValue(42)
            window.reset.click()
            assert all(v == 1 for v in window.mixer.gains.values())
            for dark in (True, False):
                window.dark = dark
                window.set_theme_mode()
                app.processEvents()
                assert not window.grab().isNull()
            window.close()
            app.processEvents()
            assert sha256(source) == original_hash
            result["checks"].append(
                "desktop startup, both themes, nested controls, reset and autosave"
            )
        result["ok"] = True
    except Exception:
        result["error"] = traceback.format_exc()
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
