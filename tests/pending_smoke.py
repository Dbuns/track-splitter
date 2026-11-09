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
from PySide6.QtCore import QEventLoop, QThread, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from song_library import atomic_json

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
app.setFont(QFont("Segoe UI", 10))


def wait(window):
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if not window.busy() else None)
    timeout.timeout.connect(loop.quit)
    poll.start(20)
    timeout.start(5000)
    loop.exec()
    poll.stop()
    timeout.stop()
    app.processEvents()
    assert not window.busy()


with tempfile.TemporaryDirectory(prefix="pending_ui_", dir=ROOT / ".tmp") as temporary:
    root = Path(temporary)
    source = root / "New song.wav"
    sf.write(source, np.full((44100, 2), 0.01, dtype="float32"), 44100, subtype="FLOAT")
    w = track_splitter.Window(root)
    errors = []
    w.error = errors.append
    w.show()
    app.processEvents()
    output = root / "outputs" / "new_song"
    output.mkdir(parents=True)
    names = ("vocals", "drums", "bass", "guitar", "other")
    for name in names:
        sf.write(
            output / (name + ".wav"),
            np.full((44100, 2), 0.01, dtype="float32"),
            44100,
            subtype="FLOAT",
        )
    atomic_json(
        output / "verification.json",
        dict(
            source=str(source),
            source_sha256="fixture",
            stems=[dict(stem=n, duration_seconds=1) for n in names],
        ),
    )
    state = {"fail": True}

    class FakeWorker(QThread):
        status = Signal(str)
        finished_ok = Signal(str)
        failed = Signal(str)

        def __init__(self, *args):
            super().__init__()

        def run(self):
            self.status.emit("Separating five tracks…")
            self.msleep(300)
            if state["fail"]:
                self.failed.emit("Simulated model error")
            else:
                self.finished_ok.emit(str(output))

    with patch.object(track_splitter, "Worker", FakeWorker):
        w.import_song(source)
        assert w.pending and w.pending_row and (w.library_list.count() == 1)
        assert w.pending_row.bar.minimum() == w.pending_row.bar.maximum() == 0
        for dark, name in ((True, "dark"), (False, "light")):
            w.dark = dark
            w.set_theme_mode()
            app.processEvents()
            w.grab().save(str(ROOT / ".tmp" / "test-results" / f"pending-{name}.png"))
        wait(w)
        assert errors == ["Simulated model error"]
        assert w.pending["state"] == "failed" and (not w.pending_row.bar.isVisible())
        QTest.qWait(100)
        w.grab().save(str(ROOT / ".tmp" / "test-results" / "pending-failed.png"))
        assert w.pending_row.retry_button.isVisible() and w.add_song.isEnabled(), (
            w.pending_row.isVisible(),
            w.pending_row.retry_button.isHidden(),
            w.add_song.isEnabled(),
            w.library_list.isEnabled(),
            w.pending_row.geometry(),
        )
        w.grab().save(str(ROOT / ".tmp" / "test-results" / "pending-failed.png"))
        state["fail"] = False
        w.pending_row.retry_button.click()
        wait(w)
        assert w.pending is None and w.pending_row is None and (len(w.library.entries) == 1)
        assert w.output == str(output) and w.library_list.count() == 1
        assert set(w.track_controls) == set(names)
    w.close()
    app.processEvents()
print(
    "PASS: immediate pending row; indeterminate progress; dark/light rendering; error state; Retry; successful replacement by ready song without duplicate entries."
)
