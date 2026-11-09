# ruff: noqa: I001
from bootstrap import ROOT

import hashlib
import os
import tempfile
import time
from pathlib import Path


os.environ["QT_QPA_PLATFORM"] = "offscreen"
from unittest.mock import patch

import numpy as np
import soundfile as sf
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from song_library import atomic_json
from track_splitter import Window

app = QApplication([])
QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
app.setFont(QFont("Segoe UI", 10))


def wait_worker(window):
    loop = QEventLoop()
    poll = QTimer()
    deadline = QTimer()
    deadline.setSingleShot(True)
    poll.timeout.connect(lambda: loop.quit() if not window.busy() else None)
    deadline.timeout.connect(loop.quit)
    poll.start(50)
    deadline.start(30000)
    loop.exec()
    poll.stop()
    deadline.stop()
    QTest.qWait(100)
    assert not window.busy(), "Worker timed out"


with tempfile.TemporaryDirectory(prefix="studio_ui_", dir=ROOT / ".tmp") as temporary:
    root = Path(temporary)
    audio = (
        np.column_stack(
            [np.sin(np.arange(441000) * 0.02), np.sin(np.arange(441000) * 0.03)]
        ).astype("float32")
        * 0.03
    )
    for number in (1, 2):
        source = root / f"Test song {number}.wav"
        sf.write(source, audio * number, 44100, subtype="FLOAT")
        output = root / "outputs" / f"song{number}"
        output.mkdir(parents=True)
        names = ("vocals", "drums", "bass", "guitar", "other", "piano")
        for name in names:
            sf.write(output / (name + ".wav"), audio, 44100, subtype="FLOAT")
        atomic_json(
            output / "verification.json",
            dict(
                source=str(source),
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                stems=[dict(stem=n, duration_seconds=10) for n in names],
            ),
        )
    w = Window(root)
    w.show()
    app.processEvents()
    errors = []
    w.error = errors.append
    wait_worker(w)
    assert (
        len(w.library.entries) == 2
        and len(w.mixer.tracks) == 5
        and ("piano" not in w.track_controls)
    )
    assert not hasattr(w, "stop") and (not hasattr(w, "save")) and (not hasattr(w, "loop_check"))
    first = w.current["id"]
    original = w.library.resolve(w.current["source"])
    original_bytes = original.read_bytes()
    w.track_controls["vocals"][0].setValue(170)
    w.track_controls["drums"][1].click()
    w.track_controls["bass"][2].click()
    w.master.setValue(12)
    w.reset.click()
    assert (
        all((value == 1 for value in w.mixer.gains.values()))
        and (not w.mixer.muted)
        and (not w.mixer.solo)
        and (w.master.value() == 75)
    )
    w.track_controls["guitar"][1].click()
    w.track_controls["bass"][2].click()
    w.track_controls["guitar"][0].setValue(68)
    assert "guitar" in w.mixer.muted and "bass" in w.mixer.solo
    w.add_section_button.click()
    assert w.draft is not None and w.wave.draft is not None
    w.check.click()
    assert len(w.sections) == 0, "Unnamed draft must not save"
    w.section_name.setText("Intro")
    w.a.setValue(0.5)
    w.b.setValue(2)
    w.check.click()
    intro = w.sections[0]["id"]
    assert not w.editor.isVisible()
    w.add_section_button.click()
    w.section_name.setText("Verse")
    w.a.setValue(5)
    w.b.setValue(7)
    w.check.click()
    verse = next((s["id"] for s in w.sections if s["name"] == "Verse"))
    w.section_controls[intro][0].click()
    w.section_controls[verse][0].click()
    assert w.mixer.ranges == [(22050, 88200), (220500, 308700)]
    w.section_controls[intro][1].click()
    w.section_name.setText("Opening")
    w.a.setValue(1)
    w.b.setValue(3)
    assert w.wave.draft["start"] == 1 and w.wave.draft["end"] == 3
    QTest.mousePress(w.wave, Qt.LeftButton, pos=QPoint(round(w.wave.x(3)), 40))
    assert w.wave.dragging == "end"
    QTest.mouseMove(w.wave, QPoint(round(w.wave.x(4)), 40))
    QTest.mouseRelease(w.wave, Qt.LeftButton, pos=QPoint(round(w.wave.x(4)), 40))
    assert abs(w.b.value() - 4) < 0.04
    w.check.click()
    assert w.sections[0]["name"] == "Opening" and w.sections[0]["enabled"]
    QTest.qWait(350)
    saved = w.library.read_session(w.current, 10)
    assert saved["tracks"]["guitar"]["gain"] == 0.68 and saved["tracks"]["guitar"]["mute"]
    assert len(saved["sections"]) == 2 and saved["sections"][0]["name"] == "Opening"
    w.section_controls[verse][0].click()
    assert len(w.mixer.ranges) == 1
    w.section_controls[intro][0].click()
    assert not w.mixer.ranges
    w.section_controls[verse][2].click()
    assert len(w.sections) == 1
    w.timeline.setValue(3456)
    assert abs(w.mixer.position / w.mixer.rate - 3.456) < 0.0001
    w.import_song(original)
    assert w.worker is None and len(w.library.entries) == 2
    w.master.setValue(0)
    w.play.click()
    QTest.qWait(350)
    assert w.mixer.playing
    w.play.click()
    assert not w.mixer.playing
    w.master.setValue(60)
    second = next((e for e in w.library.entries if e["id"] != first))
    w.activate(second)
    wait_worker(w)
    w.close()
    app.processEvents()
    w = Window(root)
    w.show()
    app.processEvents()
    w.error = errors.append
    wait_worker(w)
    assert w.current["id"] == second["id"]
    w.activate(w.library.find(first))
    wait_worker(w)
    assert len(w.sections) == 1 and w.sections[0]["name"] == "Opening"
    assert w.track_controls["guitar"][1].isChecked() and w.track_controls["bass"][2].isChecked()
    assert w.track_controls["guitar"][0].value() == 68 and w.master.value() == 60
    w.export.click()
    assert w.export_feedback == "working"
    feedback = []
    w.export_worker.finished_ok.connect(lambda path: feedback.append(w.export_feedback))
    wait_worker(w)
    assert not errors, errors
    assert "success" in feedback, "Successful export must show confirmation before it expires"
    w.export_feedback_until = time.monotonic() - 1
    w.update_export_feedback()
    assert w.export_feedback == "idle" and w.export.toolTip() == "Export mix"
    files = list(Path(w.output).glob("*_exported_*.wav"))
    assert len(files) == 1
    assert files[0].parent == Path(w.output)
    info = sf.info(files[0])
    assert info.frames == 441000 and info.subtype == "PCM_24"
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        w.delete_song(w.current)
    assert len(w.library.entries) == 2
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        w.delete_song(w.current)
    assert len(w.library.entries) == 1 and w.current["id"] == second["id"]
    assert original.read_bytes() == original_bytes and list(
        (root / ".trash").glob("*/restore.json")
    )
    w.close()
    app.processEvents()
print(
    "PASS: reset mix; song-folder export naming; five-track icons/mute/solo; draft validation; two-way waveform handles; section add/edit/delete; multi-selection loops; autosave; song switch/restart; duplicate import reuse; real muted audio; WAV export; delete confirmation and original preservation."
)
