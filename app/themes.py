from PySide6.QtGui import QColor, QPalette


def apply_theme(window, dark):
    bg, panel, field, text, muted, border, accent, selected = (
        ("#151d27", "#1f2b39", "#263648", "#edf3f8", "#b1c1d2", "#52677c", "#73c6d0", "#344e65")
        if dark
        else (
            "#f5f7fa",
            "#e8eff5",
            "#ffffff",
            "#203244",
            "#52677b",
            "#a8bac8",
            "#287b89",
            "#c9e0eb",
        )
    )
    palette = QPalette()
    for role, color in (
        (QPalette.Window, bg),
        (QPalette.WindowText, text),
        (QPalette.Base, field),
        (QPalette.AlternateBase, panel),
        (QPalette.Text, text),
        (QPalette.Button, panel),
        (QPalette.ButtonText, text),
        (QPalette.ToolTipBase, field),
        (QPalette.ToolTipText, text),
        (QPalette.Highlight, selected),
        (QPalette.HighlightedText, text),
        (QPalette.Mid, muted),
        (QPalette.PlaceholderText, muted),
    ):
        palette.setColor(role, QColor(color))
    window.setPalette(palette)
    window.setAutoFillBackground(True)
    window.setStyleSheet(f"""
        QWidget {{ font-family:'Segoe UI'; font-size:13px; color:{text}; background-color:{bg}; }}
        QLabel, QSlider, QGroupBox {{ background:transparent; }}
        QWidget#sidebar QWidget {{ background:transparent; }}
        QWidget#sidebar {{ background:{panel}; border-radius:9px; }}
        QToolButton {{ background:transparent; border:0; border-radius:5px; padding:3px; }}
        QToolButton:hover, QToolButton:checked {{ background:{selected}; }}
        QWidget#sidebar QToolButton:hover {{ background:{selected}; border:1px solid {accent}; }}
        QWidget#sidebar QToolButton:pressed {{ background:{selected}; border:2px solid {accent}; }}
        QToolButton#tempoStep {{ border:1px solid {border}; border-radius:4px; }}
        QToolButton#tempoStep:hover {{ border:1px solid {accent}; background:{selected}; }}
        QToolButton#solo {{ border:1px solid {border}; }}
        QToolButton#solo:checked {{ background:#f2cc78; color:#302100; }}
        QGroupBox {{ border:1px solid {border}; border-radius:8px; margin-top:12px; padding-top:12px; }}
        QGroupBox::title {{ subcontrol-origin:margin; left:12px; padding:0 5px; }}
        QFrame#section {{ background:{panel}; border-radius:6px; }}
        QLineEdit, QDoubleSpinBox {{ border:1px solid {border}; padding:5px; border-radius:4px; background:{field}; color:{text}; selection-background-color:{selected}; }}
        QListWidget {{ background:transparent; border:0; outline:0; }}
        QListWidget::item:selected {{ background:{selected}; border-radius:7px; }}
        QPushButton {{ padding:6px 10px; border:1px solid {border}; border-radius:5px; background:{panel}; color:{text}; }}
        QPushButton:hover {{ background:{selected}; }}
        QSlider::groove:horizontal {{ height:5px; background:{border}; border-radius:2px; }}
        QSlider::sub-page:horizontal {{ background:{accent}; border-radius:2px; }}
        QSlider::handle:horizontal {{ background:{text}; border:1px solid {accent}; width:13px; margin:-5px 0; border-radius:6px; }}
        QScrollArea {{ border:0; background:transparent; }}
        QScrollBar#mainContentBar:vertical {{ background:transparent; width:12px; margin:0; }}
        QScrollBar#mainContentBar::handle:vertical {{ background:{border}; border-radius:5px; min-height:24px; }}
        QScrollBar#mainContentBar::handle:vertical:disabled {{ background:transparent; }}
        QScrollBar#mainContentBar::handle:vertical:hover {{ background:{accent}; }}
        QScrollBar#mainContentBar::add-line:vertical, QScrollBar#mainContentBar::sub-line:vertical {{ height:0; }}
        QScrollBar#mainContentBar::add-page:vertical, QScrollBar#mainContentBar::sub-page:vertical {{ background:transparent; }}
        QCheckBox {{ background:transparent; spacing:0; padding:0; margin:0; }}
        QCheckBox::indicator {{ width:17px; height:17px; border:1px solid {muted}; border-radius:3px; background:{field}; }}
        QCheckBox::indicator:checked {{ background:{accent}; border:1px solid {text}; border-radius:3px; }}
        QProgressBar {{ border:0; border-radius:3px; background:{border}; }}
        QProgressBar::chunk {{ background:{accent}; border-radius:3px; }}
        QToolTip {{ color:{text}; background:{field}; border:1px solid {border}; }}
    """)

    import re

    from PySide6.QtWidgets import QWidget

    for child in window.findChildren(QWidget):
        child.setPalette(palette)
        style = child.styleSheet()
        if style:
            style = re.sub(r"color:(?:palette\(mid\)|#b1c1d2|#52677b)", "color:" + muted, style)
            child.setStyleSheet(style)
    window.setPalette(palette)
