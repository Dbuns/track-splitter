# ruff: noqa: I001
from bootstrap import ROOT

import os
import tempfile
from pathlib import Path


os.environ["QT_QPA_PLATFORM"] = "offscreen"
from unittest.mock import patch

import numpy as np
import soundfile as sf
import track_splitter
from drum_separator import sha256
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from song_library import atomic_json
from track_splitter import TempoWorker, Window

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
app.setFont(QFont("Segoe UI", 10))


def wait(w):
    loop = QEventLoop()
    poll = QTimer()
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(
        lambda: loop.quit() if not w.busy() and (not w.tempo_apply_timer.isActive()) else None
    )
    deadline.timeout.connect(loop.quit)
    poll.start(30)
    deadline.start(45000)
    loop.exec()
    poll.stop()
    deadline.stop()
    QTest.qWait(100)
    assert not w.busy() and (not w.tempo_apply_timer.isActive())


class SlowEstimate(TempoWorker):
    def run(self):
        self.msleep(500)
        super().run()


with tempfile.TemporaryDirectory(prefix="inline_tempo_", dir=ROOT / ".tmp") as temporary:
    root = Path(temporary)
    rate = 44100
    frames = rate * 8
    pulse = np.zeros(frames, dtype="float32")
    click = np.hanning(900).astype("float32") * np.sin(np.arange(900) * 0.6) * 0.05
    for i in range(0, frames - len(click), rate // 2):
        pulse[i : i + len(click)] += click
    audio = np.column_stack((pulse, pulse))
    source = root / "Inline tempo test.wav"
    sf.write(source, audio, rate, subtype="FLOAT")
    folder = root / "outputs" / "song"
    folder.mkdir(parents=True)
    names = ("vocals", "drums", "bass", "guitar", "other")
    for name in names:
        sf.write(folder / (name + ".wav"), audio, rate, subtype="FLOAT")
    atomic_json(
        folder / "verification.json",
        dict(
            source=str(source),
            source_sha256=sha256(source),
            stems=[dict(stem=n, duration_seconds=8) for n in names],
        ),
    )
    w = Window(root)
    w.resize(1120, 800)
    w.show()
    errors = []
    w.error = errors.append
    app.processEvents()
    wait(w)
    assert w.base_bpm == 120 and w.tempo_value.text() == "120"
    assert (
        isinstance(w.base_bpm, int)
        and w.tempo_unit.text() == "BPM"
        and (w.tempo_value.suffix() == "")
    )
    with patch.object(track_splitter, "TempoWorker", SlowEstimate):
        w.detect_bpm()
        assert w.busy() and (not w.findChildren(QDialog))
        start = w.tempo_started
        with patch("track_splitter.time.monotonic", return_value=start + 0.05):
            w.animate_tempo_icon()
            first = w.tempo_icon.icon().pixmap(22, 22).toImage()
        with patch("track_splitter.time.monotonic", return_value=start + 0.4):
            w.animate_tempo_icon()
            second = w.tempo_icon.icon().pixmap(22, 22).toImage()
        assert first != second
        wait(w)
    assert not errors, errors
    assert abs(w.base_bpm - 120) < 3 and w.tempo_value.value() > 0
    w.edit_original_bpm()
    w.tempo_value.setValue(120)
    w.apply_tempo_value()
    reference = (
        w.reset.mapTo(w.content, QPoint()),
        w.master.mapTo(w.content, QPoint()),
        w.tempo_area.size(),
    )
    w.tempo_value.setFocus()
    w.tempo_value.selectAll()
    QTest.keyClicks(w.tempo_value, "96")
    QTest.keyClick(w.tempo_value, Qt.Key_Return)
    wait(w)
    assert not errors, errors
    assert w.mixer.tempo_factor == 0.8 and w.tempo_value.value() == 96
    worker = w.tempo_worker
    w.tempo_up.click()
    assert w.tempo_value.value() == 106
    w.tempo_up.click()
    assert w.tempo_value.value() == 116
    w.tempo_down.click()
    assert w.tempo_value.value() == 106 and w.tempo_worker is worker
    wait(w)
    assert abs(w.mixer.tempo_factor - 106 / 120) < 1e-08
    assert reference == (
        w.reset.mapTo(w.content, QPoint()),
        w.master.mapTo(w.content, QPoint()),
        w.tempo_area.size(),
    )
    w.tempo_value.setValue(96)
    w.apply_tempo_value()
    wait(w)
    w.sections = [dict(id="loop", name="Practice", start=0.5, end=1.5, enabled=True)]
    w.refresh_sections()
    w.update_ranges()
    w.seek(0.5)
    w.mixer.playing = True
    w.mixer.render(rate * 2)
    w.mixer.pause()
    assert abs(w.mixer.position / rate - 1.1) < 2 / rate
    for dark, name in ((True, "dark"), (False, "light")):
        w.dark = dark
        w.set_theme_mode()
        app.processEvents()
        w.grab().save(str(ROOT / ".tmp" / "test-results" / f"inline-tempo-{name}.png"))
    w.save_current()
    w.close()
    app.processEvents()
    w = Window(root)
    w.error = errors.append
    w.show()
    wait(w)
    assert w.mixer.tempo_factor == 0.8 and w.base_bpm == 120 and (w.tempo_value.value() == 96)
    w.export.click()
    if w.busy():
        assert not w.tempo_value.isEnabled() and (not w.tempo_up.isEnabled())
    wait(w)
    assert w.tempo_value.isEnabled()
    exports = list(folder.glob("*_exported_*.wav"))
    assert len(exports) == 1
    assert sf.info(exports[0]).frames == round(frames / 0.8)
    w.tempo_icon.click()
    assert w.mixer.tempo_factor == 1 and w.tempo_value.value() == 120
    w.close()
    app.processEvents()
    flat = root / "outputs" / "flat"
    flat.mkdir()
    silence = np.zeros((44100, 2), dtype="float32")
    flat_source = root / "No beat.wav"
    sf.write(flat_source, silence, rate, subtype="FLOAT")
    for name in names:
        sf.write(flat / (name + ".wav"), silence, rate, subtype="FLOAT")
    atomic_json(
        flat / "verification.json",
        dict(
            source=str(flat_source),
            source_sha256=sha256(flat_source),
            stems=[dict(stem=n, duration_seconds=1) for n in names],
        ),
    )
    w = Window(root)
    w.error = errors.append
    wait(w)
    entry = w.library.register(flat)
    w.activate(entry)
    wait(w)
    attempted = w.tempo_worker
    QTest.qWait(250)
    assert w.tempo_worker is attempted and w.base_bpm is None and (not w.busy())
    w.tempo_value.setValue(149.2)
    w.apply_tempo_value()
    assert w.base_bpm == 149 and w.tempo_value.text() == "149"
    session = w.library.resolve(entry["session"])
    w.save_current()
    w.close()
    app.processEvents()
    saved = __import__("json").loads(session.read_text())
    saved["base_bpm"] = 149.2
    atomic_json(session, saved)
    w = Window(root)
    assert w.base_bpm == 149 and w.tempo_value.text() == "149" and (w.tempo_worker is None)
    w.close()
    app.processEvents()
print(
    "PASS: auto-load estimation; integer BPM; one attempt on no beat; saved fractional BPM rounded; inline calculation; pendulum animation; editable BPM; debounced +/-10; fixed layout; source-time loops; saved tempo; tempo-aware export."
)
