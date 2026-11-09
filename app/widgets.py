"""Reusable waveform, song rows and compact mixer controls."""

import math
import time

import numpy as np
from icons import icon
from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def stamp(seconds):
    seconds = max(0, seconds)
    return f"{int(seconds) // 60}:{int(seconds) % 60:02d}.{int(seconds * 10) % 10}"


def tool(name, tip, size=24):
    button = QToolButton()
    button.setIcon(icon(name, size))
    button.setIconSize(QSize(size, size))
    button.setToolTip(tip)
    button.setAccessibleName(tip)
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedSize(size + 16, size + 16)
    return button


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()


class Waveform(QWidget):
    seek = Signal(float)
    rangeEdited = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(160)
        self.setCursor(Qt.PointingHandCursor)
        self.duration = 0
        self.position = 0
        self.peaks = []
        self.sections = []
        self.draft = None
        self.dragging = None
        self.dark = True

    def load(self, mixer):
        count = min(1400, mixer.frames)
        edges = np.linspace(0, mixer.frames, count + 1, dtype=int)
        mono = np.zeros(mixer.frames, dtype="float32")
        for name, data in mixer.tracks.items():
            if name not in mixer.drum_children:
                mono += data.mean(axis=1)
        peaks = np.array([float(np.max(np.abs(mono[a:b]))) for a, b in zip(edges[:-1], edges[1:])])
        self.peaks = peaks / max(float(peaks.max(initial=0)), 1e-8)
        self.duration = mixer.duration
        self.update()

    def x(self, seconds):
        return seconds / max(self.duration, 1e-8) * (self.width() - 1)

    def seconds(self, x):
        return max(0, min(self.duration, x / max(1, self.width() - 1) * self.duration))

    def paintEvent(self, event):
        bg, wave, ink, selected, unselected, handle = (
            ("#152536", "#69bfc3", "#c8d7e3", "#27585d", "#20364a", "#f2c76c")
            if self.dark
            else ("#e8eff5", "#287b89", "#203244", "#bcdedc", "#d7e3ed", "#986000")
        )
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(bg))
        w, h = self.width(), self.height()
        if not self.duration:
            p.setPen(QColor(ink))
            p.drawText(self.rect(), Qt.AlignCenter, "Add a song to start practising")
            return
        for section in self.sections:
            a, b = self.x(section["start"]), self.x(section["end"])
            p.fillRect(
                int(a),
                24,
                max(1, int(b - a)),
                h - 45,
                QColor(selected if section["enabled"] else unselected),
            )
        p.setPen(QColor(wave))
        for i, peak in enumerate(self.peaks):
            x = int(i / max(1, len(self.peaks) - 1) * (w - 1))
            amplitude = int(peak * (h * 0.29))
            p.drawLine(x, h // 2 - amplitude, x, h // 2 + amplitude)
        for section in self.sections:
            x = int(self.x(section["start"]))
            p.setPen(QColor(ink))
            p.drawLine(x, 24, x, h - 20)
            p.drawText(min(x + 5, max(0, w - 95)), 17, section["name"][:18])
        x = int(self.x(self.position))
        p.setPen(QPen(QColor("#ffffff" if self.dark else "#203244"), 2))
        p.drawLine(x, 24, x, h - 20)
        if not self.draft:
            p.setPen(QColor(ink))
            p.drawText(8, h - 5, "0:00")
            p.drawText(max(0, w - 58), h - 5, stamp(self.duration))
        if self.draft:
            for name in ("start", "end"):
                seconds = self.draft[name]
                x = int(self.x(seconds))
                p.setPen(QPen(QColor(handle), 3))
                p.drawLine(x, 22, x, h - 21)
                p.setBrush(QColor(handle))
                p.drawRoundedRect(max(0, min(w - 12, x - 6)), 24, 12, 16, 3, 3)
                p.setPen(QColor(handle))
                label = ("A " if name == "start" else "B ") + f"{seconds:.2f}s"
                p.drawText(max(2, min(w - 92, x + 9)), h - 6 if name == "start" else 17, label)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.duration:
            return
        if self.draft:
            closest = min(
                ("start", "end"),
                key=lambda key: abs(self.x(self.draft[key]) - event.position().x()),
            )
            if abs(self.x(self.draft[closest]) - event.position().x()) <= 14:
                self.dragging = closest
                self.setCursor(Qt.SizeHorCursor)
                return
        self.seek.emit(self.seconds(event.position().x()))

    def mouseMoveEvent(self, event):
        if not self.dragging or not self.draft:
            return
        value = self.seconds(event.position().x())
        if self.dragging == "start":
            self.draft["start"] = max(0, min(value, self.draft["end"] - 0.01))
        else:
            self.draft["end"] = min(self.duration, max(value, self.draft["start"] + 0.01))
        self.rangeEdited.emit(self.draft["start"], self.draft["end"])
        self.update()

    def mouseReleaseEvent(self, event):
        self.dragging = None
        self.setCursor(Qt.PointingHandCursor)


class WaveDotsButton(QToolButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(32, 32)
        self.setToolTip("Splitting drum tracks…")
        self.setAccessibleName("Splitting drum tracks")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.palette().windowText().color())
        phase = time.monotonic() * 5
        for index in range(3):
            x = self.width() / 2 + (index - 1) * 7
            y = self.height() / 2 - 3 * math.sin(phase - index * 2 * math.pi / 3)
            painter.drawEllipse(QPointF(x, y), 1.7, 1.7)


class ScrollingTitle(QWidget):
    def __init__(self, text):
        super().__init__()
        self.text = text
        self.offset = 0.0
        self.direction = 1
        self.pause_until = time.monotonic() + 1
        self.setFixedHeight(26)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.advance)
        self.timer.start()

    def sizeHint(self):
        return QSize(120, 26)

    def resizeEvent(self, event):
        self.offset = 0.0
        self.direction = 1
        self.pause_until = time.monotonic() + 1
        super().resizeEvent(event)

    def advance(self):
        if not self.isVisible():
            return
        limit = max(0, self.fontMetrics().horizontalAdvance(self.text) - self.width())
        if not limit:
            if self.offset:
                self.offset = 0.0
                self.update()
            return
        if time.monotonic() < self.pause_until:
            return
        self.offset = max(0, min(limit, self.offset + self.direction * 0.8))
        if self.offset in (0, limit):
            self.direction *= -1
            self.pause_until = time.monotonic() + 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setClipRect(self.rect())
        painter.setPen(self.palette().windowText().color())
        metrics = self.fontMetrics()
        baseline = (self.height() - metrics.height()) / 2 + metrics.ascent()
        painter.drawText(QPointF(-self.offset, baseline), self.text)


class SongRow(QWidget):
    picked = Signal()
    folder = Signal()
    remove = Signal()

    def __init__(self, title):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(3)
        self.title_label = ScrollingTitle(title)
        layout.addWidget(self.title_label, 1)
        row = layout
        folder = tool("folder", "Open stem folder", 17)
        folder.clicked.connect(self.folder.emit)
        remove = tool("trash", "Delete song", 17)
        remove.clicked.connect(self.remove.emit)
        row.addWidget(folder)
        row.addWidget(remove)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.picked.emit()


class PendingSongRow(QWidget):
    retry = Signal()
    dismiss = Signal()

    def __init__(self, pending, dark=True):
        super().__init__()
        muted = "#b1c1d2" if dark else "#52677b"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignTop)
        title = ScrollingTitle(pending["source"].stem)
        title.setStyleSheet("color:" + muted + ";")
        layout.addWidget(title)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("font-size:11px;color:" + muted + ";")
        layout.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        layout.addWidget(self.bar)
        controls = QHBoxLayout()
        self.retry_button = QPushButton("Retry")
        self.retry_button.clicked.connect(self.retry.emit)
        controls.addWidget(self.retry_button)
        self.dismiss_button = tool("close", "Dismiss failed import", 16)
        self.dismiss_button.clicked.connect(self.dismiss.emit)
        controls.addWidget(self.dismiss_button)
        layout.addLayout(controls)
        self.update_state(pending)

    def update_state(self, pending):
        failed = pending["state"] == "failed"
        self.bar.setVisible(not failed)
        self.retry_button.setVisible(failed)
        self.dismiss_button.setVisible(failed)
        seconds = int(time.monotonic() - pending["started"])
        self.message.setText(
            "Could not separate. Retry when ready."
            if failed
            else pending["status"] + f"  {seconds // 60}:{seconds % 60:02d}"
        )
