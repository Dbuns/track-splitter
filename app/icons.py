"""Theme-aware image icons with proportional scaling."""

from paths import ASSET_DIR
from PySide6.QtCore import QByteArray, QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

INSTRUMENTS = ("vocals", "drums", "bass", "guitar", "other", "kick", "snare", "toms", "cymbals")
CONTROLS = (
    "reset",
    "export",
    "folder",
    "plus",
    "check",
    "edit",
    "trash",
    "volume_muted",
    "volume_low",
    "volume_medium",
    "volume_high",
)
PATHS = {
    "down": '<path d="m7 12 9 9 9-9"/>',
    "up": '<path d="m7 21 9-9 9 9"/>',
    "close": '<path d="m8 8 16 16M24 8 8 24"/>',
    "play": '<path d="m10 5 18 11-18 11z" fill="currentColor" stroke="none"/>',
    "pause": '<path d="M8 5h6v22H8zM19 5h6v22h-6z" fill="currentColor" stroke="none"/>',
}
_CACHE = {}
_DARK = True


def set_theme(dark):
    global _DARK
    _DARK = dark
    _CACHE.clear()


def _render(svg, size):
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def _svg(body, color):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">' + body + "</svg>"
    ).replace("currentColor", color)


def metronome_icon(size=22, angle=0):
    color = "#edf3f8" if _DARK else "#203244"
    # The body stays fixed while the pendulum rotates around its lower pivot.
    body = (
        '<path d="M8 27 13 5h6l5 22ZM6 29h20"/>'
        f'<g transform="rotate({angle:.1f} 16 24)"><path d="M16 24V7"/>'
        '<circle cx="16" cy="18" r="1.8"/></g>'
    )
    return _render(_svg(body, color), size)


def icon(name, size=24, muted=False):
    key = (name, size, muted)
    if key in _CACHE:
        return _CACHE[key]
    if name == "metronome":
        result = metronome_icon(size)
    else:
        color = (
            ("#8293a4" if muted else "#edf3f8") if _DARK else ("#687989" if muted else "#203244")
        )
        if name in INSTRUMENTS or name in CONTROLS:
            source = QPixmap(str(ASSET_DIR / "icons" / (name + ".png")))
            if source.isNull():
                raise ValueError("Missing icon image: " + name)
            tinted = QPixmap(source.size())
            tinted.fill(Qt.transparent)
            painter = QPainter(tinted)
            painter.drawPixmap(0, 0, source)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(tinted.rect(), QColor(color))
            painter.end()
            fitted = tinted.scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            canvas = QPixmap(size * 2, size * 2)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            painter.drawPixmap(
                QPoint(
                    (canvas.width() - fitted.width()) // 2, (canvas.height() - fitted.height()) // 2
                ),
                fitted,
            )
            if muted:
                painter.setPen(QPen(QColor("#ad5b54"), 2.5))
                painter.drawLine(3, size * 2 - 3, size * 2 - 3, 3)
            painter.end()
            canvas.setDevicePixelRatio(2)
            result = QIcon(canvas)
            _CACHE[key] = result
            return result
        else:
            svg = _svg(PATHS[name], color)
        if muted:
            svg = svg.replace(
                "</svg>", '<path d="m3 29 26-26" stroke="#ad5b54" stroke-width="2.5"/></svg>'
            )
        result = _render(svg, size)
    _CACHE[key] = result
    return result
