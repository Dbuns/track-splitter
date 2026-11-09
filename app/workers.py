"""Background separation, tempo and export jobs."""

import traceback

from mix_export import export_mix, snapshot
from PySide6.QtCore import QThread, Signal
from separator import separate


class Worker(QThread):
    status = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, source, output_root=None):
        super().__init__()
        self.source = source
        self.output_root = output_root

    def run(self):
        try:
            self.finished_ok.emit(
                str(separate(self.source, self.status.emit, "htdemucs_6s", self.output_root))
            )
        except Exception:
            self.failed.emit(traceback.format_exc())


class TempoWorker(QThread):
    status = Signal(str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, mixer, cache, factor=None):
        super().__init__()
        with mixer.lock:
            self.tracks = dict(mixer.tracks)
            self.rate = mixer.rate
        self.cache = cache
        self.factor = factor

    def run(self):
        try:
            from tempo_backend import estimate_bpm, prepare_tempo

            if self.factor is None:
                audio = self.tracks.get("drums", next(iter(self.tracks.values())))
                self.completed.emit(dict(kind="estimate", bpm=estimate_bpm(audio, self.rate)))
            else:
                tracks = prepare_tempo(
                    self.tracks, self.rate, self.factor, self.cache, self.status.emit
                )
                self.completed.emit(dict(kind="speed", factor=self.factor, tracks=tracks))
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.tracks.clear()


class DrumWorker(QThread):
    status = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, source):
        super().__init__()
        self.source = source

    def run(self):
        try:
            from drum_separator import separate_drums

            self.finished_ok.emit(str(separate_drums(self.source, self.status.emit)))
        except Exception:
            self.failed.emit(traceback.format_exc())


class ExportWorker(QThread):
    status = Signal(str)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, mixer, folder, name):
        super().__init__()
        self.mix = snapshot(mixer)
        self.folder = folder
        self.name = name

    def run(self):
        try:
            self.finished_ok.emit(
                str(export_mix(self.mix, self.folder, self.name, self.status.emit))
            )
        except Exception:
            self.failed.emit(traceback.format_exc())
