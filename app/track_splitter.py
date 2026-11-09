"""Track Splitter desktop window and application entry point."""

import json
import math
import sys
import time
import uuid
from pathlib import Path

from paths import ASSET_DIR, DATA_ROOT

if sys.stdout is None or sys.stderr is None:
    folder = DATA_ROOT / "library" / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    console_log = open(folder / "desktop.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = console_log
    if sys.stderr is None:
        sys.stderr = console_log
from audio_engine import Mixer
from icons import icon, metronome_icon
from icons import set_theme as set_icon_theme
from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QFontDatabase, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from separator import ROOT
from song_library import Library, atomic_json
from themes import apply_theme
from widgets import PendingSongRow, SongRow, WaveDotsButton, Waveform, clear_layout, stamp, tool
from workers import DrumWorker, ExportWorker, TempoWorker, Worker

AUDIO = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aiff", ".wma"}


class Window(QWidget):
    def __init__(self, root=ROOT):
        super().__init__()
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".tmp").mkdir(exist_ok=True)
        self.library = Library(self.root)
        self.mixer = Mixer()
        self.current = None
        self.source = None
        self.output = None
        self.worker = None
        self.export_worker = None
        self.pending = None
        self.pending_row = None
        self.export_feedback = "idle"
        self.export_feedback_until = 0.0
        self.export_feedback_style = None
        self.bpm_attempted_ids = set()
        self.tempo_worker = None
        self.tempo_edit_original = False
        self.tempo_animation_state = None
        self.base_bpm = None
        self.tempo_factor = 1.0
        self.tempo_started = 0.0
        self.tempo_kind = None
        self.drum_worker = None
        self.drums_expanded = False
        self.drum_toggle = None
        self.drum_started = 0.0
        self.sections = []
        self.draft = None
        self.restoring = False
        self.track_controls = {}
        self.section_controls = {}
        self.setWindowIcon(QIcon(str(ASSET_DIR / "track_splitter.ico")))
        self.setWindowTitle("Track Splitter")
        self.setAcceptDrops(True)
        try:
            self.preferences = json.loads((self.root / "library" / "preferences.json").read_text())
        except (OSError, ValueError):
            self.preferences = {}
        self.dark = self.preferences.get("theme", "dark") == "dark"
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(
            max(600, min(1040, screen.width() - 80)), max(360, min(740, screen.height() - 100))
        )
        self.setMinimumSize(600, 360)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(18)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(245)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        label = QLabel("Your songs")
        label.setStyleSheet("font-size:18px;font-weight:600;")
        header.addWidget(label)
        header.addStretch()
        self.add_song = tool("plus", "Add a new song")
        self.add_song.clicked.connect(self.browse)
        header.addWidget(self.add_song)
        side.addLayout(header)
        self.library_list = QListWidget()
        self.library_list.setSpacing(4)
        self.library_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.library_list.currentItemChanged.connect(self.song_changed)
        side.addWidget(self.library_list)
        side.addWidget(QLabel("Processed here. Ready to replay."))
        outer.addWidget(sidebar)
        self.content = QWidget()
        main = QVBoxLayout(self.content)
        main.setSpacing(10)
        main.setContentsMargins(0, 0, 8, 0)
        main.setSizeConstraint(QLayout.SetMinimumSize)
        self.content.setMinimumWidth(520)
        self.main_scroll = QScrollArea()
        self.main_scroll.setWidgetResizable(True)
        self.main_scroll.setFrameShape(QFrame.NoFrame)
        self.main_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.main_scroll.verticalScrollBar().setObjectName("mainContentBar")
        self.main_scroll.verticalScrollBar().rangeChanged.connect(
            lambda low, high: self.main_scroll.verticalScrollBar().setEnabled(high > low)
        )
        self.main_scroll.setWidget(self.content)
        outer.addWidget(self.main_scroll, 1)
        header = QHBoxLayout()
        self.title = QLabel("Track Splitter")
        self.title.setStyleSheet("font-size:23px;font-weight:600;")
        self.title.setWordWrap(True)
        header.addWidget(self.title, 1)
        self.saved = QLabel("")
        self.saved.setStyleSheet("color:palette(mid);font-size:11px;")
        header.addWidget(self.saved)
        self.theme_toggle = QPushButton()
        self.theme_toggle.clicked.connect(self.toggle_theme)
        header.addWidget(self.theme_toggle)
        main.addLayout(header)
        self.wave = Waveform()
        self.wave.seek.connect(self.seek)
        self.wave.rangeEdited.connect(self.handles_changed)
        main.addWidget(self.wave)
        self.timeline = QSlider(Qt.Horizontal)
        self.timeline.setRange(0, 0)
        self.timeline.valueChanged.connect(lambda value: self.seek(value / 1000))
        main.addWidget(self.timeline)
        transport = QGridLayout()
        transport.setContentsMargins(0, 0, 0, 0)
        left = QHBoxLayout()
        self.play = tool("play", "Play / pause", 28)
        self.play.clicked.connect(self.toggle_play)
        left.addWidget(self.play)
        self.clock = QLabel("0:00.0 / 0:00.0")
        left.addWidget(self.clock)
        left.addStretch()
        middle = QHBoxLayout()
        middle.setSpacing(7)
        self.master_icon = QLabel()
        self.master_icon.setFixedSize(26, 26)
        self.master_icon.setAccessibleName("Master volume")
        middle.addWidget(self.master_icon)
        self.master = QSlider(Qt.Horizontal)
        self.master.setRange(0, 100)
        self.master.setValue(75)
        self.master.setFixedWidth(125)
        self.master.valueChanged.connect(self.master_changed)
        self.master.setToolTip("Master volume")
        middle.addWidget(self.master)
        right = QHBoxLayout()
        right.setSpacing(4)
        right.addStretch()
        self.tempo_area = QWidget()
        self.tempo_area.setFixedSize(148, 58)
        tempo_row = QHBoxLayout(self.tempo_area)
        tempo_row.setContentsMargins(0, 0, 0, 0)
        tempo_row.setSpacing(4)
        self.tempo_icon = tool("metronome", "Reset to original BPM", 22)
        self.tempo_icon.clicked.connect(self.metronome_clicked)
        self.tempo_icon.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tempo_icon.customContextMenuRequested.connect(self.tempo_menu)
        tempo_row.addWidget(self.tempo_icon, alignment=Qt.AlignVCenter)
        tempo_column = QVBoxLayout()
        tempo_column.setContentsMargins(0, 0, 0, 0)
        tempo_column.setSpacing(2)
        self.tempo_value = QDoubleSpinBox()
        self.tempo_value.setRange(0, 450)
        self.tempo_value.setDecimals(0)
        self.tempo_value.setSingleStep(1)
        self.tempo_value.setSuffix("")
        self.tempo_value.setSpecialValueText("—")
        self.tempo_value.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.tempo_value.setFixedSize(64, 28)
        self.tempo_value.setAlignment(Qt.AlignCenter)
        self.tempo_value.setKeyboardTracking(False)
        self.tempo_value.editingFinished.connect(self.apply_tempo_value)
        self.tempo_value.setToolTip(
            "Click to edit practice BPM. Click the metronome to reset original tempo."
        )
        number_row = QHBoxLayout()
        number_row.setContentsMargins(0, 0, 0, 0)
        number_row.setSpacing(4)
        number_row.addWidget(self.tempo_value)
        self.tempo_unit = QLabel("BPM")
        self.tempo_unit.setFixedWidth(36)
        number_row.addWidget(self.tempo_unit)
        tempo_column.addLayout(number_row)
        steps = QHBoxLayout()
        steps.setContentsMargins(0, 0, 0, 0)
        steps.setSpacing(4)
        self.tempo_down = QToolButton()
        self.tempo_down.setObjectName("tempoStep")
        self.tempo_down.setText("−10")
        self.tempo_down.setFixedSize(50, 24)
        self.tempo_down.setToolTip("Decrease practice tempo by 10 BPM")
        self.tempo_down.setCursor(Qt.PointingHandCursor)
        self.tempo_down.clicked.connect(lambda: self.adjust_tempo(-10))
        steps.addWidget(self.tempo_down)
        self.tempo_up = QToolButton()
        self.tempo_up.setObjectName("tempoStep")
        self.tempo_up.setText("+10")
        self.tempo_up.setFixedSize(50, 24)
        self.tempo_up.setToolTip("Increase practice tempo by 10 BPM")
        self.tempo_up.setCursor(Qt.PointingHandCursor)
        self.tempo_up.clicked.connect(lambda: self.adjust_tempo(10))
        steps.addWidget(self.tempo_up)
        tempo_column.addLayout(steps)
        tempo_row.addLayout(tempo_column)
        right.addWidget(self.tempo_area)
        right.addSpacing(6)
        self.reset = tool("reset", "Reset mix", 22)
        self.reset.clicked.connect(self.reset_mix)
        right.addWidget(self.reset)
        self.export = tool("export", "Export mix", 22)
        self.export.clicked.connect(self.export_current)
        right.addWidget(self.export)
        transport.addLayout(left, 0, 0)
        transport.addLayout(middle, 0, 1, alignment=Qt.AlignCenter)
        transport.addLayout(right, 0, 2)
        for column in range(3):
            transport.setColumnStretch(column, 1)
        main.addLayout(transport)
        self.mix_group = QGroupBox("Tracks")
        mix = QVBoxLayout(self.mix_group)
        mix.setContentsMargins(12, 4, 12, 8)
        self.mix_layout = QGridLayout()
        self.mix_layout.setVerticalSpacing(0)
        mix.addLayout(self.mix_layout)
        main.addWidget(self.mix_group)
        self.sections_group = QGroupBox("Sections")
        sections_layout = QVBoxLayout(self.sections_group)
        sections_layout.setContentsMargins(10, 12, 10, 8)
        self.section_scroll = QScrollArea()
        self.section_scroll.setWidgetResizable(True)
        self.section_scroll.setFrameShape(QFrame.NoFrame)
        self.section_scroll.setMinimumHeight(80)
        section_body = QWidget()
        self.section_rows = QVBoxLayout(section_body)
        self.section_rows.setContentsMargins(0, 0, 0, 0)
        self.section_rows.setAlignment(Qt.AlignTop)
        self.section_scroll.setWidget(section_body)
        sections_layout.addWidget(self.section_scroll)
        self.editor = QFrame()
        self.editor.setObjectName("section")
        editor_layout = QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(10, 6, 10, 6)
        row = QHBoxLayout()
        self.section_name = QLineEdit()
        self.section_name.setPlaceholderText("Section name — Intro, Verse, Chorus…")
        row.addWidget(self.section_name, 1)
        self.check = tool("check", "Save section", 20)
        self.check.clicked.connect(self.commit_section)
        row.addWidget(self.check)
        cancel = tool("close", "Cancel section edit", 18)
        cancel.clicked.connect(self.cancel_draft)
        row.addWidget(cancel)
        editor_layout.addLayout(row)
        row = QHBoxLayout()
        self.a = QDoubleSpinBox()
        self.b = QDoubleSpinBox()
        for spin in (self.a, self.b):
            spin.setDecimals(2)
            spin.setSuffix(" s")
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setFixedWidth(92)
            spin.valueChanged.connect(self.editor_changed)
        row.addWidget(QLabel("A"))
        row.addWidget(self.a)
        row.addWidget(QLabel("B"))
        row.addWidget(self.b)
        self.editor_error = QLabel("Drag the two gold handles or enter times.")
        self.editor_error.setStyleSheet("color:palette(mid);font-size:11px;")
        row.addWidget(self.editor_error, 1)
        editor_layout.addLayout(row)
        self.editor.hide()
        sections_layout.addWidget(self.editor)
        self.add_section_button = QToolButton()
        self.add_section_button.setIcon(icon("plus", 18))
        self.add_section_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.add_section_button.clicked.connect(self.add_section)
        self.add_section_button.setAccessibleName("Add a new section")
        sections_layout.addWidget(self.add_section_button, alignment=Qt.AlignLeft)
        sections_layout.addStretch(1)
        main.addWidget(self.sections_group, 1)
        self.status = QLabel("Add a song with +, or drop an audio file here.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:palette(mid);font-size:12px;")
        main.addWidget(self.status)
        self.tempo_apply_timer = QTimer(self)
        self.tempo_apply_timer.setSingleShot(True)
        self.tempo_apply_timer.setInterval(350)
        self.tempo_apply_timer.timeout.connect(self.apply_queued_tempo)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(250)
        self.autosave.timeout.connect(lambda: self.save_current(False))
        self.position_save = QTimer(self)
        self.position_save.setInterval(5000)
        self.position_save.timeout.connect(lambda: self.save_current(False))
        self.position_save.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.shortcut = QShortcut(QKeySequence("Space"), self)
        self.shortcut.activated.connect(self.toggle_play)
        self.refresh_library()
        self.refresh_sections()
        self.set_ready(False)
        self.set_theme_mode()
        active = self.library.find(self.library.data.get("active"))
        if active is None and self.library.entries:
            active = self.library.entries[0]
        if active:
            try:
                self.activate(active)
            except Exception as exc:
                self.error(str(exc))

    def toggle_theme(self):
        self.dark = not self.dark
        self.set_theme_mode(True)

    def set_theme_mode(self, save=False):
        self.export_feedback_style = None
        set_icon_theme(self.dark)
        self.wave.dark = self.dark
        self.wave.update()
        self.theme_toggle.setText("Light mode" if self.dark else "Dark mode")
        self.tempo_icon.setIcon(icon("metronome", 22))
        self.update_master_icon()
        self.tempo_animation_state = None
        self.reset.setIcon(icon("reset", 22))
        self.add_song.setIcon(icon("plus", 24))
        self.export.setIcon(icon("export", 22))
        self.check.setIcon(icon("check", 20))
        self.add_section_button.setIcon(icon("plus", 18))
        # Refresh instrument and navigation icons after the palette changes.
        self.build_tracks()
        self.refresh_library()
        self.refresh_sections()
        self.tick()
        for button in self.editor.findChildren(QToolButton):
            if button.toolTip() == "Cancel section edit":
                button.setIcon(icon("close", 18))
        apply_theme(self, self.dark)
        if save:
            self.preferences["theme"] = "dark" if self.dark else "light"
            atomic_json(self.root / "library" / "preferences.json", self.preferences)

    def busy(self):
        return (
            (self.worker is not None and self.worker.isRunning())
            or (self.export_worker is not None and self.export_worker.isRunning())
            or (self.drum_worker is not None and self.drum_worker.isRunning())
            or (self.tempo_worker is not None and self.tempo_worker.isRunning())
        )

    def log(self, message):
        self.status.setText(message)
        folder = self.root / "library" / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "studio.log").open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")

    def error(self, message):
        self.log(message)
        QMessageBox.warning(self, "Track Splitter", message[-1400:])

    def set_ready(self, ready):
        for widget in (
            self.wave,
            self.timeline,
            self.play,
            self.master,
            self.master_icon,
            self.tempo_icon,
            self.tempo_value,
            self.tempo_down,
            self.tempo_up,
            self.reset,
            self.mix_group,
            self.sections_group,
        ):
            widget.setEnabled(ready)
        self.export.setEnabled(ready and not self.busy())

    def refresh_library(self):
        selected = self.current["id"] if self.current else None
        self.library_list.blockSignals(True)
        self.library_list.clear()
        for entry in self.library.entries:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, entry["id"])
            item.setSizeHint(QSize(215, 50))
            self.library_list.addItem(item)
            row = SongRow(entry["title"])
            row.picked.connect(lambda item=item: self.library_list.setCurrentItem(item))
            row.folder.connect(lambda checked=False, e=entry: self.open_folder(e))
            row.remove.connect(lambda checked=False, e=entry: self.delete_song(e))
            self.library_list.setItemWidget(item, row)
            if entry["id"] == selected:
                self.library_list.setCurrentItem(item)
        self.pending_row = None
        if self.pending:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, "pending")
            item.setFlags(Qt.ItemIsEnabled)
            item.setSizeHint(QSize(215, 110 if self.pending["state"] == "failed" else 78))
            self.library_list.addItem(item)
            self.pending_row = PendingSongRow(self.pending, self.dark)
            self.pending_row.retry.connect(self.retry_pending)
            self.pending_row.dismiss.connect(self.dismiss_pending)
            self.library_list.setItemWidget(item, self.pending_row)
            self.library_list.scrollToItem(item)
        self.library_list.blockSignals(False)

    def song_changed(self, item, previous):
        if item is None or self.busy():
            return
        entry = self.library.find(item.data(Qt.UserRole))
        if entry and (self.current is None or entry["id"] != self.current["id"]):
            try:
                self.activate(entry)
            except Exception as exc:
                self.refresh_library()
                self.error(str(exc))

    def activate(self, entry):
        self.tempo_apply_timer.stop()
        self.tempo_edit_original = False
        if not self.save_current():
            return False
        self.autosave.stop()
        folder = self.library.ensure_five_tracks(entry)
        report = json.loads((folder / "verification.json").read_text(encoding="utf-8-sig"))
        duration = report["stems"][0]["duration_seconds"]
        data = self.library.read_session(entry, duration)
        self.mixer.load(folder)
        if (folder / "drum tracks" / "verification.json").exists():
            try:
                self.attach_drum_tracks(folder / "drum tracks")
            except Exception as exc:
                self.log("Saved drum parts could not be loaded: " + str(exc))
        self.base_bpm = int(round(data["base_bpm"])) if data.get("base_bpm") else None
        self.tempo_factor = data.get("tempo_factor", 1.0)
        self.drums_expanded = bool(data.get("drums_expanded", False)) and bool(
            self.mixer.drum_children
        )
        self.restoring = True
        try:
            self.current = entry
            self.source = str(self.library.resolve(entry["source"]))
            self.output = str(folder)
            self.sections = [dict(s) for s in data.get("sections", [])]
            for name, settings in data.get("tracks", {}).items():
                if name in self.mixer.tracks:
                    self.mixer.configure(
                        name,
                        gain=settings.get("gain", 1),
                        mute=settings.get("mute", False),
                        solo=settings.get("solo", False),
                    )
            self.mixer.master = data.get("master", 0.75)
            self.master.setValue(round(self.mixer.master * 100))
            self.mixer.seek(data.get("position", 0))
            self.update_ranges()
            self.timeline.setRange(0, round(self.mixer.duration * 1000))
            self.cancel_draft()
            self.build_tracks()
            self.refresh_sections()
            self.wave.load(self.mixer)
            self.title.setText(entry["title"])
            self.setWindowTitle("Track Splitter — " + entry["title"])
            self.library.activate(entry)
            self.refresh_library()
            self.set_ready(True)
            self.tick()
        finally:
            self.restoring = False
        self.update_tempo_label()
        self.save_current()
        self.log("Ready. Space to play/pause. Select sections to loop them in song order.")
        if abs(self.tempo_factor - self.mixer.tempo_factor) > 1e-8 and not self.busy():
            self.start_tempo(self.tempo_factor)
        self.maybe_calculate_bpm()
        return True

    def schedule_save(self, *args):
        if self.current and not self.restoring:
            self.saved.setText("Saving…")
            self.autosave.start()

    def save_current(self, show_error=True):
        if not self.current or self.restoring:
            return True
        try:
            self.library.save_session(
                self.current,
                self.mixer,
                self.sections,
                drums_expanded=self.drums_expanded,
                base_bpm=self.base_bpm,
                tempo_factor=self.tempo_factor,
            )
            self.saved.setText("Saved automatically")
            return True
        except Exception as exc:
            self.saved.setText("Could not save")
            self.log("Autosave failed: " + str(exc))
            if show_error:
                QMessageBox.warning(self, "Could not save", str(exc))
            return False

    def browse(self):
        if self.busy():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add a song",
            str(self.root),
            "Audio (*.mp3 *.wav *.flac *.m4a *.ogg *.aac *.aiff *.wma)",
        )
        if path:
            self.import_song(path)

    def import_song(self, path):
        if self.busy():
            return
        path = Path(path).resolve()
        if not path.is_file() or path.suffix.lower() not in AUDIO:
            self.error("Choose a supported audio file.")
            return
        if not self.save_current():
            return
        existing = self.library.find_source(path)
        if existing:
            if self.activate(existing):
                self.pending = None
                self.refresh_library()
                self.log("Loaded existing separation. No new split needed.")
            return
        self.add_song.setEnabled(False)
        self.library_list.setEnabled(False)
        self.export.setEnabled(False)
        self.pending = dict(
            source=path, state="working", status="Preparing…", started=time.monotonic()
        )
        self.refresh_library()
        self.worker = Worker(str(path), self.root / "outputs")
        self.worker.status.connect(self.separation_status)
        self.worker.finished_ok.connect(self.complete)
        self.worker.failed.connect(self.separation_failed)
        self.worker.finished.connect(self.task_finished)
        self.worker.start()
        self.update_tempo_controls()
        self.log("Separating " + path.stem + " into five tracks…")

    def separation_status(self, message):
        self.log(message)
        if self.pending:
            self.pending["status"] = next(
                (
                    short
                    for prefix, short in [
                        ("Preparing", "Preparing…"),
                        ("Decoding", "Decoding audio…"),
                        ("Loading", "Loading model…"),
                        ("Separating", "Separating tracks…"),
                        ("Complete", "Opening song…"),
                    ]
                    if message.startswith(prefix)
                ),
                message,
            )
            if self.pending_row:
                self.pending_row.update_state(self.pending)

    def separation_failed(self, message):
        if self.pending:
            self.pending["state"] = "failed"
            self.refresh_library()
        self.error(message)

    def retry_pending(self):
        if self.pending and not self.busy():
            self.import_song(self.pending["source"])

    def dismiss_pending(self):
        if not self.busy():
            self.pending = None
            self.refresh_library()

    def complete(self, path):
        try:
            entry = self.library.register(path)
            if not self.activate(entry):
                raise RuntimeError(
                    "Could not open the separated song. Previous settings were kept."
                )
            self.pending = None
            self.refresh_library()
        except Exception as exc:
            self.separation_failed(str(exc))

    def task_finished(self):
        self.add_song.setEnabled(True)
        self.library_list.setEnabled(True)
        self.export.setEnabled(bool(self.output))
        self.build_tracks()
        self.play.setEnabled(bool(self.output))
        self.tempo_icon.setEnabled(bool(self.output))
        self.update_tempo_controls()
        if (
            self.output
            and abs(self.tempo_factor - self.mixer.tempo_factor) > 1e-8
            and not self.busy()
        ):
            self.start_tempo(self.tempo_factor)
        self.maybe_calculate_bpm()

    def open_folder(self, entry):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.library.resolve(entry["output"]))))

    def delete_song(self, entry):
        if self.busy():
            return
        answer = QMessageBox.question(
            self,
            "Delete song?",
            f"Remove “{entry['title']}” and its saved settings? Stem folders and mixes saved inside them will move to Track Splitter’s local trash. The original audio will be kept.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self.remove_entry(entry)
        except Exception as exc:
            self.error(str(exc))

    def remove_entry(self, entry):
        if self.current and self.current["id"] == entry["id"]:
            if not self.save_current():
                return
            self.mixer.close()
            self.autosave.stop()
            self.tempo_apply_timer.stop()
        self.library.remove(entry)
        if self.current and self.current["id"] == entry["id"]:
            self.current = None
            self.source = None
            self.output = None
            self.sections = []
            self.draft = None
            self.drums_expanded = False
            self.tempo_factor = 1.0
            self.base_bpm = None
            self.mixer = Mixer()
            self.update_tempo_label()
            self.wave.duration = 0
            self.wave.peaks = []
            self.wave.sections = []
            self.wave.draft = None
            self.wave.update()
            self.cancel_draft()
            self.refresh_sections()
            self.build_tracks()
            self.title.setText("Track Splitter")
            self.saved.clear()
            self.clock.setText("0:00.0 / 0:00.0")
            self.set_ready(False)
            if self.library.entries:
                self.activate(self.library.entries[0])
        self.refresh_library()
        self.log("Song removed. Original audio kept; generated files are in local trash.")

    def build_tracks(self):
        clear_layout(self.mix_layout)
        self.track_controls = {}
        if self.mixer.tracks:
            self.mix_layout.addWidget(QLabel("Solo"), 0, 4, alignment=Qt.AlignCenter)
        self.drum_toggle = None
        names = []
        for name in self.mixer.tracks:
            if name in self.mixer.drum_children:
                continue
            names.append(name)
            if name == "drums" and self.drums_expanded:
                names.extend(self.mixer.drum_children)
        for row, name in enumerate(names, 1):
            child = name in self.mixer.drum_children
            size = 22 if child else 28
            muted = name in self.mixer.muted
            button = tool(name, "Mute / unmute " + name, size)
            button.setCheckable(True)
            button.setChecked(muted)
            button.setIcon(icon(name, size, muted))
            display_button = QWidget()
            display_button.setFixedWidth(56)
            inset = QHBoxLayout(display_button)
            inset.setContentsMargins(14 if child else 0, 0, 0, 0)
            inset.setSpacing(0)
            inset.addWidget(button, alignment=Qt.AlignLeft)
            label = QLabel(name.capitalize())
            label.setMinimumWidth(65)
            if child:
                label.setIndent(12)
                label.setStyleSheet("font-size:12px;")
            if name == "drums":
                header = QWidget()
                head = QHBoxLayout(header)
                head.setContentsMargins(0, 0, 0, 0)
                head.setSpacing(2)
                head.addWidget(label)
                waiting = self.drum_worker is not None and self.drum_worker.isRunning()
                symbol = (
                    "up"
                    if self.drums_expanded
                    else ("down" if self.mixer.drum_children else "plus")
                )
                self.drum_toggle = (
                    WaveDotsButton()
                    if waiting
                    else tool(
                        symbol,
                        "Collapse drum tracks"
                        if self.drums_expanded
                        else (
                            "Expand drum tracks"
                            if self.mixer.drum_children
                            else "Split drum tracks"
                        ),
                        16,
                    )
                )
                self.drum_toggle.setEnabled(not self.busy())
                self.drum_toggle.clicked.connect(self.toggle_drums)
                head.addWidget(self.drum_toggle)
                label = header
            label.setFixedWidth(102)
            gain = QSlider(Qt.Horizontal)
            gain.setRange(0, 200)
            gain.setValue(round(self.mixer.gains[name] * 100))
            value = QLabel(f"{gain.value()}%")
            value.setFixedWidth(46)
            solo = QCheckBox()
            solo.setChecked(name in self.mixer.solo)
            solo.setFixedSize(22, 22)
            solo.setAccessibleName("Solo " + name)
            solo.setToolTip("Solo " + name)
            button.toggled.connect(
                lambda checked, n=name, b=button: self.toggle_mute(n, b, checked)
            )
            gain.valueChanged.connect(
                lambda v, n=name, l=value: (l.setText(f"{v}%"), self.track_changed(n, gain=v / 100))
            )
            solo.toggled.connect(lambda checked, n=name: self.track_changed(n, solo=checked))
            for col, widget in enumerate((display_button, label, gain, value, solo)):
                if col == 4:
                    self.mix_layout.addWidget(widget, row, col, alignment=Qt.AlignCenter)
                else:
                    self.mix_layout.addWidget(widget, row, col)
            self.track_controls[name] = (gain, button, solo)
        self.mix_layout.setColumnMinimumWidth(0, 56)
        self.mix_layout.setColumnMinimumWidth(1, 102)
        self.mix_layout.setColumnStretch(2, 1)

    def toggle_mute(self, name, button, checked):
        button.setIcon(icon(name, 22 if name in self.mixer.drum_children else 28, checked))
        button.setToolTip(("Unmute " if checked else "Mute ") + name)
        self.track_changed(name, mute=checked)

    def update_tempo_label(self):
        self.tempo_value.blockSignals(True)
        self.tempo_value.setValue(self.base_bpm * self.tempo_factor if self.base_bpm else 0)
        self.tempo_value.blockSignals(False)
        self.tempo_value.setToolTip(
            f"Click to edit practice BPM. Current speed: {self.tempo_factor * 100:.0f}%."
        )
        self.update_tempo_controls()

    def update_tempo_controls(self):
        ready = bool(self.output) and not self.busy()
        self.tempo_value.setEnabled(ready)
        self.tempo_icon.setEnabled(ready)
        self.tempo_down.setEnabled(
            ready
            and bool(self.base_bpm)
            and self.tempo_value.value() > math.ceil(self.base_bpm * 0.5)
        )
        self.tempo_up.setEnabled(
            ready
            and bool(self.base_bpm)
            and self.tempo_value.value() < math.floor(self.base_bpm * 1.5)
        )

    def tempo_menu(self, position):
        if not self.output or self.busy():
            return
        menu = QMenu(self)
        menu.addAction("Recalculate BPM", self.detect_bpm)
        menu.addAction("Edit original BPM", self.edit_original_bpm)
        menu.addAction("Original speed", lambda: self.start_tempo(1.0))
        menu.exec(self.tempo_icon.mapToGlobal(position))

    def edit_original_bpm(self):
        self.tempo_apply_timer.stop()
        self.tempo_edit_original = True
        self.tempo_value.setValue(self.base_bpm or 120)
        self.tempo_value.setToolTip(
            "Edit the original BPM, then press Enter. Practice speed stays unchanged."
        )
        self.tempo_value.setFocus()
        self.tempo_value.selectAll()

    def apply_tempo_value(self):
        if not self.output or self.busy():
            return
        value = self.tempo_value.value()
        if value <= 0:
            self.update_tempo_label()
            return
        if self.tempo_edit_original or not self.base_bpm:
            if not 30 <= value <= 300:
                self.log("Original BPM must be between 30 and 300.")
                self.update_tempo_label()
                return
            self.base_bpm = int(round(value))
            self.tempo_edit_original = False
            self.update_tempo_label()
            self.save_current()
            return
        factor = value / self.base_bpm
        if not 0.5 <= factor <= 1.5:
            self.log(
                f"Choose a practice tempo between {math.ceil(self.base_bpm * 0.5)} and {math.floor(self.base_bpm * 1.5)} BPM."
            )
            self.update_tempo_label()
            return
        self.tempo_factor = factor
        self.update_tempo_label()
        self.tempo_apply_timer.start()
        self.export.setEnabled(False)
        self.schedule_save()

    def adjust_tempo(self, amount):
        if not self.base_bpm or self.busy():
            return
        value = max(
            math.ceil(self.base_bpm * 0.5),
            min(math.floor(self.base_bpm * 1.5), self.tempo_value.value() + amount),
        )
        self.tempo_value.setValue(value)
        self.apply_tempo_value()

    def apply_queued_tempo(self):
        if self.output and not self.busy():
            self.start_tempo(self.tempo_factor)

    def begin_tempo_task(self, factor):
        self.tempo_apply_timer.stop()
        self.mixer.pause()
        self.tempo_kind = "estimate" if factor is None else "speed"
        self.tempo_started = time.monotonic()
        self.tempo_worker = TempoWorker(self.mixer, self.root / ".cache" / "practice-tempo", factor)
        self.tempo_worker.status.connect(self.log)
        self.tempo_worker.completed.connect(self.tempo_complete)
        self.tempo_worker.failed.connect(self.tempo_failed)
        self.tempo_worker.finished.connect(self.task_finished)
        self.add_song.setEnabled(False)
        self.library_list.setEnabled(False)
        self.export.setEnabled(False)
        self.play.setEnabled(False)
        self.tempo_icon.setEnabled(False)
        self.tempo_value.setEnabled(False)
        self.tempo_down.setEnabled(False)
        self.tempo_up.setEnabled(False)
        if self.drum_toggle:
            self.drum_toggle.setEnabled(False)
        self.tempo_worker.start()
        self.animate_tempo_icon()

    def metronome_clicked(self):
        if not self.output or self.busy():
            return
        if self.base_bpm:
            self.start_tempo(1.0)
            self.log(f"Original tempo restored: {self.base_bpm} BPM.")
        else:
            self.detect_bpm()

    def maybe_calculate_bpm(self):
        if (
            self.output
            and self.current
            and not self.base_bpm
            and self.current["id"] not in self.bpm_attempted_ids
            and not self.busy()
        ):
            self.detect_bpm()

    def detect_bpm(self):
        if not self.output or self.busy():
            return
        self.bpm_attempted_ids.add(self.current["id"])
        self.tempo_edit_original = False
        self.begin_tempo_task(None)

    def start_tempo(self, factor):
        if not self.output or self.busy():
            return
        self.tempo_apply_timer.stop()
        self.tempo_factor = factor
        if abs(factor - 1) < 1e-8:
            self.mixer.set_tempo_tracks()
            self.update_tempo_label()
            self.save_current()
            self.task_finished()
            return
        self.begin_tempo_task(factor)
        self.update_tempo_label()

    def tempo_complete(self, result):
        if result["kind"] == "estimate":
            bpm = int(round(result["bpm"])) if result["bpm"] else None
            if bpm:
                self.base_bpm = bpm
                self.update_tempo_label()
                self.save_current()
                self.log(
                    f"Estimated original tempo: {bpm} BPM. Edit the value or use −10 / +10 to practise."
                )
            else:
                self.log(
                    "Could not estimate reliably. Click the BPM value and enter the original BPM."
                )
        else:
            self.mixer.set_tempo_tracks(result["tracks"], result["factor"])
            self.tempo_factor = result["factor"]
            self.update_tempo_label()
            self.save_current()
            self.log(f"Practice speed ready: {self.tempo_factor * 100:.0f}%, with pitch preserved.")

    def tempo_failed(self, message):
        self.tempo_factor = self.mixer.tempo_factor
        self.update_tempo_label()
        self.error(message)

    def animate_tempo_icon(self):
        running = self.tempo_worker is not None and self.tempo_worker.isRunning()
        angle = round(math.sin((time.monotonic() - self.tempo_started) * 6) * 24) if running else 0
        state = (running, angle, self.dark, bool(self.base_bpm))
        if state == self.tempo_animation_state:
            return
        self.tempo_animation_state = state
        self.tempo_icon.setIcon(metronome_icon(22, angle))
        idle = (
            "Reset to original BPM (right-click to recalculate or edit)"
            if self.base_bpm
            else "Calculate original BPM"
        )
        self.tempo_icon.setToolTip(
            "Calculating tempo…"
            if running and self.tempo_kind == "estimate"
            else ("Preparing practice tempo…" if running else idle)
        )

    def attach_drum_tracks(self, folder):
        from drum_separator import sha256

        folder = Path(folder)
        report = json.loads((folder / "verification.json").read_text(encoding="utf-8"))
        if report.get("source_sha256") != sha256(folder.parent / "drums.wav"):
            raise ValueError("Saved drum parts do not match this drum stem.")
        self.mixer.load_drum_children(folder)

    def toggle_drums(self):
        if not self.output or self.busy():
            return
        if self.mixer.drum_children:
            self.drums_expanded = not self.drums_expanded
            self.build_tracks()
            self.schedule_save()
            return
        self.mixer.pause()
        self.drum_started = time.monotonic()
        self.drum_worker = DrumWorker(Path(self.output) / "drums.wav")
        self.drum_worker.status.connect(self.log)
        self.drum_worker.finished_ok.connect(self.drums_complete)
        self.drum_worker.failed.connect(self.error)
        self.drum_worker.finished.connect(self.task_finished)
        self.add_song.setEnabled(False)
        self.library_list.setEnabled(False)
        self.export.setEnabled(False)
        self.tempo_icon.setEnabled(False)
        self.drum_worker.start()
        self.build_tracks()
        self.update_tempo_controls()
        self.log("Splitting drums into kick, snare, cymbals and toms…")

    def drums_complete(self, path):
        try:
            self.attach_drum_tracks(path)
            self.drums_expanded = False
            self.build_tracks()
            self.save_current()
            self.log("Drum parts ready. Click the down arrow beside Drums to expand.")
        except Exception as exc:
            self.error(str(exc))

    def reset_mix(self):
        if not self.output:
            return
        with self.mixer.lock:
            for name in self.mixer.tracks:
                self.mixer.configure(name, gain=1, mute=False, solo=False)
            self.mixer.master = 0.75
        self.master.setValue(75)
        self.build_tracks()
        self.schedule_save()

    def track_changed(self, name, **settings):
        self.mixer.configure(name, **settings)
        self.schedule_save()

    def update_master_icon(self):
        value = self.master.value()
        name = (
            "volume_muted"
            if value == 0
            else (
                "volume_low" if value <= 33 else ("volume_medium" if value <= 66 else "volume_high")
            )
        )
        self.master_icon.setPixmap(icon(name, 24).pixmap(24, 24))
        self.master_icon.setToolTip(f"Master volume ({value}%)")

    def master_changed(self, value):
        self.update_master_icon()
        with self.mixer.lock:
            self.mixer.master = value / 100
        self.schedule_save()

    def toggle_play(self):
        if not self.output:
            return
        try:
            if self.mixer.playing:
                self.mixer.pause()
                self.schedule_save()
            else:
                self.mixer.play()
            self.tick()
        except Exception as exc:
            self.error("Audio output could not start: " + str(exc))

    def seek(self, seconds):
        if not self.output:
            return
        self.mixer.seek(seconds)
        self.schedule_save()
        self.tick()

    def tick(self):
        self.animate_tempo_icon()
        if self.tempo_worker is not None and self.tempo_worker.isRunning():
            seconds = int(time.monotonic() - self.tempo_started)
            phase = (
                "Estimating BPM" if self.tempo_kind == "estimate" else "Preparing practice tempo"
            )
            self.status.setText(f"{phase}… {seconds // 60}:{seconds % 60:02d}")
        if self.drum_worker is not None and self.drum_worker.isRunning():
            if isinstance(self.drum_toggle, WaveDotsButton):
                self.drum_toggle.update()
            seconds = int(time.monotonic() - self.drum_started)
            self.status.setText(f"Splitting drum tracks… {seconds // 60}:{seconds % 60:02d}")
        self.update_export_feedback()
        if self.pending_row and self.pending:
            self.pending_row.update_state(self.pending)
        playing = self.mixer.playing
        self.play.setIcon(icon("pause" if playing else "play", 28))
        self.play.setToolTip("Pause" if playing else "Play")
        if not self.output:
            return
        position = self.mixer.position / self.mixer.rate
        if not self.timeline.isSliderDown():
            self.timeline.blockSignals(True)
            self.timeline.setValue(round(position * 1000))
            self.timeline.blockSignals(False)
        self.clock.setText(stamp(position) + " / " + stamp(self.mixer.duration))
        self.wave.position = position
        self.wave.update()

    def refresh_sections(self):
        self.sections.sort(key=lambda section: section["start"])
        clear_layout(self.section_rows)
        self.section_controls = {}
        for section in self.sections:
            identity = section["id"]
            frame = QFrame()
            frame.setObjectName("section")
            row = QHBoxLayout(frame)
            row.setContentsMargins(8, 3, 5, 3)
            selected = QCheckBox()
            selected.setFixedSize(22, 22)
            selected.setChecked(section["enabled"])
            selected.setToolTip("Include " + section["name"] + " in the practice loop")
            selected.setAccessibleName("Loop " + section["name"])
            selected.toggled.connect(lambda value, i=identity: self.select_section(i, value))
            row.addWidget(selected)
            title = QPushButton(section["name"])
            title.setFlat(True)
            title.setStyleSheet("border:0;background:transparent;text-align:left;padding:3px;")
            title.clicked.connect(lambda checked=False, s=section: self.seek(s["start"]))
            row.addWidget(title, 1)
            times = QLabel(f"{section['start']:.2f} – {section['end']:.2f} s")
            times.setStyleSheet("font-size:12px;color:palette(mid);")
            row.addWidget(times)
            edit = tool("edit", "Edit " + section["name"], 18)
            edit.clicked.connect(lambda checked=False, i=identity: self.edit_section(i))
            row.addWidget(edit)
            trash = tool("trash", "Delete " + section["name"], 18)
            trash.clicked.connect(lambda checked=False, i=identity: self.delete_section(i))
            row.addWidget(trash)
            self.section_rows.addWidget(frame)
            self.section_controls[identity] = (selected, edit, trash, title)
        self.add_section_button.setText("Add new section" if not self.sections else "")
        self.section_scroll.setVisible(bool(self.sections))
        self.section_scroll.setFixedHeight(min(170, max(48, len(self.sections) * 46)))
        self.wave.sections = self.sections
        self.wave.update()

    def update_ranges(self):
        self.mixer.set_ranges([(s["start"], s["end"]) for s in self.sections if s["enabled"]])
        self.wave.sections = self.sections
        self.wave.update()

    def select_section(self, identity, value):
        section = next(s for s in self.sections if s["id"] == identity)
        section["enabled"] = value
        self.update_ranges()
        self.schedule_save()

    def add_section(self):
        if not self.output:
            return
        start = min(self.mixer.position / self.mixer.rate, max(0, self.mixer.duration - 15))
        self.begin_draft(
            dict(
                id=uuid.uuid4().hex,
                name="",
                start=round(start, 2),
                end=min(self.mixer.duration, round(start + 15, 2)),
                enabled=False,
            )
        )

    def edit_section(self, identity):
        self.begin_draft(dict(next(s for s in self.sections if s["id"] == identity)))

    def begin_draft(self, section):
        self.draft = dict(section)
        self.editor.show()
        self.add_section_button.hide()
        self.section_name.setText(section["name"])
        for spin, key in ((self.a, "start"), (self.b, "end")):
            spin.blockSignals(True)
            spin.setRange(0, self.mixer.duration)
            spin.setValue(section[key])
            spin.blockSignals(False)
        self.wave.draft = self.draft
        self.wave.update()
        self.section_name.setFocus()
        self.editor_error.setText("Drag the gold handles or enter times.")
        self.editor_error.setStyleSheet("color:palette(mid);font-size:11px;")

    def editor_changed(self, *args):
        if not self.draft:
            return
        self.draft["start"] = self.a.value()
        self.draft["end"] = self.b.value()
        self.wave.draft = self.draft
        self.wave.update()

    def handles_changed(self, start, end):
        for spin, value in ((self.a, start), (self.b, end)):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self.editor_changed()

    def commit_section(self):
        if not self.draft:
            return
        name = self.section_name.text().strip()
        start = self.a.value()
        end = min(self.b.value(), self.mixer.duration)
        if not name or not 0 <= start < end <= self.mixer.duration:
            self.editor_error.setText("Enter a name and set B after A.")
            self.editor_error.setStyleSheet("color:#e18174;font-size:11px;")
            return
        section = dict(self.draft, name=name, start=start, end=end)
        self.sections = [s for s in self.sections if s["id"] != section["id"]] + [section]
        self.cancel_draft()
        self.refresh_sections()
        self.update_ranges()
        self.schedule_save()

    def cancel_draft(self):
        self.draft = None
        self.wave.draft = None
        self.wave.dragging = None
        self.wave.update()
        self.editor.hide()
        self.add_section_button.show()

    def delete_section(self, identity):
        self.sections = [s for s in self.sections if s["id"] != identity]
        if self.draft and self.draft["id"] == identity:
            self.cancel_draft()
        self.refresh_sections()
        self.update_ranges()
        self.schedule_save()

    def show_export_feedback(self, state):
        self.export_feedback = state
        self.export_feedback_until = time.monotonic() + 2 if state != "working" else 0
        self.export_feedback_style = None
        self.update_export_feedback()
        self.export.repaint()

    def update_export_feedback(self):
        if (
            self.export_feedback in ("success", "failed")
            and time.monotonic() >= self.export_feedback_until
        ):
            self.export_feedback = "idle"
        state = self.export_feedback
        pulse = int(time.monotonic() * 3) % 2 if state == "working" else 0
        signature = (state, pulse, self.dark)
        if signature == self.export_feedback_style:
            return
        self.export_feedback_style = signature
        colors = {
            "working": (("#28566c" if pulse else "#1f3545"), "#77cbd4")
            if self.dark
            else (("#b9e3ed" if pulse else "#e0eff3"), "#287b89"),
            "success": ("#205346", "#82ddb6") if self.dark else ("#d0f1de", "#267b54"),
            "failed": ("#603d3b", "#eea49c") if self.dark else ("#f8dbd5", "#a8463c"),
        }
        self.export.setIcon(icon("check" if state == "success" else "export", 22))
        self.export.setToolTip(
            {
                "idle": "Export mix",
                "working": "Exporting mix…",
                "success": "Mix exported",
                "failed": "Export failed",
            }.get(state, "Export mix")
        )
        if state == "idle":
            self.export.setStyleSheet("")
        else:
            background, border = colors[state]
            self.export.setStyleSheet(
                f"QToolButton {{ background:{background}; border:1px solid {border}; border-radius:6px; }}"
            )

    def export_complete(self, path):
        self.show_export_feedback("success")
        self.log("Mix saved: " + path)

    def export_failed(self, message):
        self.show_export_feedback("failed")
        self.error(message)

    def export_current(self):
        if not self.output or self.busy() or self.tempo_apply_timer.isActive():
            return
        self.show_export_feedback("working")
        self.export_worker = ExportWorker(
            self.mixer, Path(self.output), self.current["title"] + "_exported"
        )
        self.export.setEnabled(False)
        self.add_song.setEnabled(False)
        self.library_list.setEnabled(False)
        self.export_worker.status.connect(self.log)
        self.export_worker.finished_ok.connect(self.export_complete)
        self.export_worker.failed.connect(self.export_failed)
        self.export_worker.finished.connect(self.task_finished)
        self.export_worker.start()
        self.update_tempo_controls()
        self.log("Exporting the full song with the current mix settings…")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self.busy():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.import_song(urls[0].toLocalFile())

    def closeEvent(self, event):
        if self.busy():
            QMessageBox.information(
                self, "Working", "Please wait for the current task to finish before closing."
            )
            event.ignore()
            return
        if not self.save_current():
            event.ignore()
            return
        self.tempo_apply_timer.stop()
        self.autosave.stop()
        self.position_save.stop()
        self.timer.stop()
        self.mixer.close()
        event.accept()


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    from version import VERSION

    if sys.platform == "win32":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TrackSplitter.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("Track Splitter")
    app.setApplicationVersion(VERSION)
    app.setWindowIcon(QIcon(str(ASSET_DIR / "track_splitter.ico")))
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Segoe UI", 10))
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from diagnostics import run

        report = Path(sys.argv[2]) if len(sys.argv) > 2 else DATA_ROOT / "diagnostics.json"
        sys.exit(run(report, models="--models" in sys.argv[3:]))
    try:
        window = Window()
    except Exception as exc:
        QMessageBox.critical(None, "Could not open Track Splitter", str(exc))
        sys.exit(1)
    window.show()
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
        if target.suffix.lower() in AUDIO:
            window.import_song(target)
    sys.exit(app.exec())
