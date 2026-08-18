from PyQt5.QtWidgets import QWidget, QVBoxLayout, QTextEdit, QPushButton, QLabel, QGraphicsDropShadowEffect
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor
import pyperclip

from ui import glass

FALLBACK_STYLE = f"""
    QWidget {{
        background: #000000;
        color: #ffffff;
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
        font-weight: 400;
        border-radius: {glass.RADIUS_PANEL}px;
        border: 1px solid rgba(255, 255, 255, 0.12);
    }}
    QLabel {{
        background: transparent;
        color: rgba(255, 255, 255, 0.60);
        border: none;
        font-weight: 400;
    }}
    QTextEdit {{
        background: rgba(255, 255, 255, 0.04);
        color: #ffffff;
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: {glass.RADIUS_CONTROL}px;
        padding: 10px;
        selection-background-color: rgba(255, 255, 255, 0.20);
        font-weight: 400;
    }}
    QPushButton#primaryBtn {{
        background: #ffffff;
        border: none;
        border-radius: {glass.RADIUS_BUTTON}px;
        padding: 9px 16px;
        color: #000000;
        font-weight: 800;
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
    }}
    QPushButton#primaryBtn:hover {{
        background: rgba(255, 255, 255, 0.90);
    }}
    QPushButton#primaryBtn:pressed {{
        background: rgba(255, 255, 255, 0.75);
    }}
"""


class PasteFallbackWindow(QWidget):
    """Genuine last-resort window: only shown if the overlay itself fails
    to display the transcript for some reason. Styled to match the same
    glass language as everything else so it never feels like a different
    app bolted on."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Overlay — Paste Failed")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(FALLBACK_STYLE)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(38)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 135))
        self.setGraphicsEffect(shadow)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        self.label = QLabel("Couldn't paste automatically. Here's your transcript:")
        self.label.setFont(QFont(glass.QFONT_FAMILY, 10))
        layout.addWidget(self.label)

        self.text_edit = QTextEdit()
        self.text_edit.setFont(QFont(glass.QFONT_FAMILY, 11))
        self.text_edit.setReadOnly(True)
        layout.addWidget(self.text_edit)

        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setObjectName("primaryBtn")
        self.copy_btn.setFont(QFont(glass.QFONT_FAMILY, 10, QFont.Bold))
        self.copy_btn.clicked.connect(self._on_copy)
        layout.addWidget(self.copy_btn)

        self.setLayout(layout)
        self.resize(400, 220)

    def show_transcript(self, text: str):
        self.text_edit.setPlainText(text)
        self.show()
        self.activateWindow()

    def _on_copy(self):
        pyperclip.copy(self.text_edit.toPlainText())
        self.close()
