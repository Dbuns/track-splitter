# ruff: noqa: I001
from bootstrap import ROOT

import os
import tempfile
from pathlib import Path


os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
import soundfile as sf
from drum_separator import NAMES, sha256, verify_tracks
from unittest.mock import patch
from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from song_library import atomic_json
from track_splitter import Window

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
app.setFont(QFont("Segoe UI", 10))


def wait(w):
    loop = QEventLoop()
    poll = QTimer()
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if not w.busy() else None)
    deadline.timeout.connect(loop.quit)
    poll.start(50)
    deadline.start(30000)
    loop.exec()
    poll.stop()
    deadline.stop()
    QTest.qWait(100)
    assert not w.busy()


with (
    tempfile.TemporaryDirectory(prefix="nested_drums_", dir=ROOT / ".tmp") as temporary,
    patch("drum_separator.MODEL", Path(temporary) / "cached-model.th"),
):
    model_path = Path(temporary) / "cached-model.th"
    model_path.write_bytes(
        b"Synthetic model identity for cache validation; not used for inference."
    )
    root = Path(temporary)
    w = Window(root)
    errors = []
    w.error = errors.append
    source = root / "Drum workflow test.wav"
    audio = np.full((44100, 2), 0.03, dtype="float32")
    sf.write(source, audio, 44100, subtype="FLOAT")
    folder = root / "outputs" / "song"
    folder.mkdir(parents=True)
    for name in ("vocals", "drums", "bass", "guitar", "other"):
        sf.write(folder / (name + ".wav"), audio, 44100, subtype="FLOAT")
    atomic_json(
        folder / "verification.json",
        dict(
            source=str(source),
            source_sha256=sha256(source),
            stems=[
                dict(stem=n, duration_seconds=1)
                for n in ("vocals", "drums", "bass", "guitar", "other")
            ],
        ),
    )
    entry = w.library.register(folder)
    w.activate(entry)
    w.resize(1040, 800)
    w.show()
    app.processEvents()
    wait(w)
    assert w.drum_toggle.toolTip() == "Split drum tracks" and len(w.track_controls) == 5
    parts = folder / "drum tracks"
    parts.mkdir()
    for name, value in zip(NAMES, (0.01, 0.02, 0.03, 0.04)):
        sf.write(
            parts / (name + ".wav"),
            np.full((44100, 2), value, dtype="float32"),
            44100,
            subtype="FLOAT",
        )
    atomic_json(
        parts / "verification.json",
        dict(
            source_sha256=sha256(folder / "drums.wav"),
            model_sha256=sha256(model_path),
            tracks=verify_tracks(parts, 44100, 44100),
        ),
    )
    w.drum_toggle.click()
    wait(w)
    assert not errors, errors
    assert (
        w.mixer.drum_children == NAMES and (not w.drums_expanded) and (len(w.track_controls) == 5)
    )
    assert w.drum_toggle.toolTip() == "Expand drum tracks"
    worker = w.drum_worker

    def main_geometry():
        result = {}
        for name in ("vocals", "drums", "bass", "guitar", "other"):
            row = list(w.track_controls).index(name) + 1
            label = w.mix_layout.itemAtPosition(row, 1).widget()
            slider = w.track_controls[name][0]
            result[name] = (
                label.mapTo(w.content, QPoint()).x(),
                slider.mapTo(w.content, QPoint()).x(),
                slider.width(),
            )
        return result

    app.processEvents()
    collapsed = main_geometry()
    w.drum_toggle.click()
    app.processEvents()
    QTest.qWait(50)
    assert main_geometry() == collapsed, (collapsed, main_geometry())
    assert w.drums_expanded and list(w.track_controls) == [
        "vocals",
        "drums",
        "kick",
        "snare",
        "cymbals",
        "toms",
        "bass",
        "guitar",
        "other",
    ]
    app.processEvents()
    parent_x = w.track_controls["drums"][1].mapTo(w.mix_group, QPoint()).x()
    child_x = w.track_controls["kick"][1].mapTo(w.mix_group, QPoint()).x()
    assert child_x > parent_x + 5
    w.track_controls["kick"][0].setValue(37)
    w.track_controls["kick"][1].click()
    w.track_controls["snare"][2].click()
    w.reset.click()
    assert (
        all((g == 1 for g in w.mixer.gains.values())) and (not w.mixer.muted) and (not w.mixer.solo)
    )
    w.track_controls["kick"][0].setValue(44)
    w.track_controls["snare"][2].click()
    w.track_controls["drums"][0].setValue(80)
    w.drum_toggle.click()
    assert not w.drums_expanded and len(w.track_controls) == 5
    assert w.mixer.gains["kick"] == 0.44 and "snare" in w.mixer.solo
    w.drum_toggle.click()
    assert w.drums_expanded and w.drum_worker is worker
    assert (
        w.tempo_value.text() == "—"
        and w.tempo_unit.text() == "BPM"
        and ("Calculate original BPM" in w.tempo_icon.toolTip())
    ), (w.base_bpm, w.tempo_value.text(), w.tempo_icon.toolTip())
    for dark, name in ((True, "dark"), (False, "light")):
        w.dark = dark
        w.set_theme_mode()
        app.processEvents()
        w.grab().save(str(ROOT / ".tmp" / "test-results" / f"nested-drums-{name}.png"))
    assert w.save_current()
    w.close()
    app.processEvents()
    w = Window(root)
    w.error = errors.append
    wait(w)
    assert w.drums_expanded and len(w.track_controls) == 9
    assert (
        w.mixer.gains["kick"] == 0.44
        and w.mixer.gains["drums"] == 0.8
        and ("snare" in w.mixer.solo)
    )
    w.export.click()
    wait(w)
    assert not errors, errors
    exports = list(folder.glob("*_exported_*.wav"))
    assert len(exports) == 1
    data, rate = sf.read(exports[0], always_2d=True)
    assert data.shape == (44100, 2) and rate == 44100
    np.testing.assert_allclose(data, 0.02 * 0.8 * 0.75, atol=2e-07)
    w.master.setValue(0)
    w.play.click()
    QTest.qWait(250)
    assert w.mixer.playing
    w.play.click()
    w.close()
    app.processEvents()
print(
    "PASS: + worker/cache -> down arrow -> expanded indented controls -> collapse; child mute/solo/reset; saved levels/expansion; exact nested export; real muted playback; BPM control; both themes."
)
