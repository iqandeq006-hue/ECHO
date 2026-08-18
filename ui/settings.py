import logging
import os
import sys
import pyperclip
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QFrame,
    QComboBox, QCheckBox, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QSize, QRectF
from PyQt5.QtGui import QFont, QKeySequence, QPainter, QColor, QPen

from ui import glass

logger = logging.getLogger(__name__)

# Canonical Whisper model names (see openai-whisper / faster-whisper available_models()).
_ALL_WHISPER_MODELS = [
    "tiny", "tiny.en",
    "base", "base.en",
    "small", "small.en",
    "medium", "medium.en",
    "large-v1", "large-v2", "large-v3",
    "large-v3-turbo",
    "distil-small.en", "distil-medium.en",
    "distil-large-v2", "distil-large-v3",
]


def _get_bundled_models_dir():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.dirname(__file__))
    candidate = os.path.join(base, 'models')
    os.makedirs(candidate, exist_ok=True)
    return candidate


def _bundled_model_names():
    bundled_dir = _get_bundled_models_dir()
    if not bundled_dir:
        return None
    try:
        names = set()
        for item in os.listdir(bundled_dir):
            item_path = os.path.join(bundled_dir, item)
            if os.path.isdir(item_path):
                has_config = os.path.isfile(os.path.join(item_path, "config.json"))
                has_weights = (
                    os.path.isfile(os.path.join(item_path, "model.bin")) or
                    os.path.isfile(os.path.join(item_path, "model.safetensors"))
                )
                if has_config and has_weights:
                    names.add(item)
        return names
    except OSError:
        return None


if getattr(sys, 'frozen', False):
    _bundled = _bundled_model_names()
    WHISPER_MODELS = (
        [m for m in _ALL_WHISPER_MODELS if m in _bundled]
        if _bundled else _ALL_WHISPER_MODELS
    )
    if not WHISPER_MODELS:
        WHISPER_MODELS = _ALL_WHISPER_MODELS
else:
    WHISPER_MODELS = _ALL_WHISPER_MODELS

GLASS_STYLE = f"""
    QWidget {{
        background: #000000;
        color: #ffffff;
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
        font-weight: 400;
    }}
    /* settingsPanel's fill/border/corner shape is hand-painted as a true
       squircle in SquirclePanel.paintEvent — no QSS background/border/
       radius here, or it would draw a competing rectangular layer under
       the squircle and show through at the corners. */
    QLabel {{
        color: #ffffff;
        background: transparent;
        font-weight: 400;
    }}
    QLabel#sectionLabel {{
        color: rgba(255, 255, 255, 0.22);
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 2.5px;
    }}
    QLabel#windowTitle {{
        font-size: 17px;
        font-weight: 800;
        letter-spacing: -0.3px;
        color: #ffffff;
    }}
    QPushButton {{
        background: rgba(255, 255, 255, 0.06);
        border: 1px solid rgba(255, 255, 255, 0.10);
        border-radius: {glass.RADIUS_BUTTON}px;
        padding: 9px 16px;
        color: rgba(255, 255, 255, 0.60);
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.18);
        color: rgba(255, 255, 255, 0.85);
    }}
    QPushButton:pressed {{
        background: rgba(255, 255, 255, 0.04);
    }}
    QPushButton#primaryBtn {{
        background: #ffffff;
        border: none;
        color: #000000;
        font-weight: 800;
    }}
    QPushButton#primaryBtn:hover {{
        background: rgba(255, 255, 255, 0.90);
    }}
    QPushButton#primaryBtn:pressed {{
        background: rgba(255, 255, 255, 0.75);
    }}
    QPushButton#hotkeyChip {{
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: 7px;
        padding: 5px 12px;
        color: #ffffff;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.3px;
    }}
    QPushButton#hotkeyChip:hover {{
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.22);
    }}
    QPushButton#hotkeyChip[recording="true"] {{
        background: rgba(255, 255, 255, 0.14);
        border: 1px solid rgba(255, 255, 255, 0.32);
        color: #ffffff;
    }}
    QPushButton#copyRowBtn {{
        background: rgba(255, 255, 255, 0.10);
        border: 1px solid rgba(255, 255, 255, 0.18);
        border-radius: 6px;
        padding: 3px 10px;
        color: #ffffff;
        font-size: 11px;
        font-weight: 700;
    }}
    QPushButton#copyRowBtn:hover {{
        background: rgba(255, 255, 255, 0.22);
        border: 1px solid rgba(255, 255, 255, 0.35);
    }}
    QListWidget {{
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 10px;
        color: rgba(255, 255, 255, 0.85);
        padding: 6px;
        font-weight: 400;
    }}
    QListWidget::item {{
        border-radius: 7px;
        padding: 2px 4px;
    }}
    QListWidget::item:selected {{
        background: rgba(255, 255, 255, 0.08);
    }}
    QComboBox {{
        background: rgba(255, 255, 255, 0.07);
        border: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: {glass.RADIUS_BUTTON}px;
        padding: 6px 10px;
        color: #ffffff;
        min-width: 120px;
        font-weight: 700;
        font-size: 11px;
    }}
    QComboBox:hover {{
        background: rgba(255, 255, 255, 0.12);
        border: 1px solid rgba(255, 255, 255, 0.22);
    }}
    QComboBox QAbstractItemView {{
        background: #000000;
        color: rgba(255, 255, 255, 0.80);
        border: 1px solid rgba(255, 255, 255, 0.12);
        selection-background-color: rgba(255, 255, 255, 0.10);
        outline: none;
        font-weight: 600;
    }}
    QCheckBox {{
        color: rgba(255, 255, 255, 0.80);
        spacing: 8px;
        font-weight: 500;
    }}
    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border-radius: 4px;
        border: 1px solid rgba(255, 255, 255, 0.22);
        background: rgba(255, 255, 255, 0.05);
    }}
    QCheckBox::indicator:checked {{
        background: #ffffff;
        border: 1px solid #ffffff;
    }}
"""

_KEY_DISPLAY = {
    "ctrl": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
    "cmd": "Cmd",
    "win": "Win",
    "space": "Space",
    "enter": "Enter",
    "tab": "Tab",
    "esc": "Esc",
}


def hotkey_to_display(raw: str) -> str:
    raw = raw.replace("<", "").replace(">", "")
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    words = [_KEY_DISPLAY.get(p.lower(), p.upper()) for p in parts]
    return " + ".join(words)


def display_to_hotkey(display: str) -> str:
    parts = [p.strip() for p in display.split("+") if p.strip()]
    return "+".join(p.lower() for p in parts)


class HistoryRowWidget(QWidget):
    """Custom history row widget with fixed Copy button on the right (Feature 5.2)."""

    def __init__(self, timestamp: str, text: str, parent=None):
        super().__init__(parent)
        self.full_text = text

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        # Label showing timestamp and text
        self.label = QLabel(f"<span style='color: rgba(255,255,255,0.4); font-size:11px;'>{timestamp}</span> &nbsp; {text}")
        self.label.setTextFormat(Qt.RichText)
        self.label.setTextInteractionFlags(Qt.NoTextInteraction)
        self.label.setWordWrap(False)
        self.label.setToolTip(text)
        layout.addWidget(self.label, stretch=1)

        # Dedicated fixed Copy button
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.setObjectName("copyRowBtn")
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy)
        layout.addWidget(self.copy_btn, stretch=0, alignment=Qt.AlignRight)

    def _on_copy(self):
        try:
            pyperclip.copy(self.full_text)
            self.copy_btn.setText("Copied!")
            QTimer.singleShot(1000, lambda: self.copy_btn.setText("Copy"))
        except Exception:
            logger.exception("Failed to copy history text")


class HotkeyCaptureButton(QPushButton):
    def __init__(self, initial_display: str, on_captured, on_capture_start=None, on_capture_end=None, parent=None):
        super().__init__(initial_display, parent)
        self.setObjectName("hotkeyChip")
        self.setCursor(Qt.PointingHandCursor)
        self._capturing = False
        self._on_captured = on_captured
        self._on_capture_start = on_capture_start
        self._on_capture_end = on_capture_end
        self._modifiers = set()
        self.clicked.connect(self._begin_capture)

    def _begin_capture(self):
        if self._capturing:
            return
        self._capturing = True
        self._modifiers = set()
        self.setProperty("recording", "true")
        self.setText("Press keys\u2026")
        self.setStyleSheet(self.styleSheet())
        self.grabKeyboard()
        if self._on_capture_start:
            try:
                self._on_capture_start()
            except Exception:
                logger.exception("on_capture_start callback failed")

    def keyPressEvent(self, event):
        if not self._capturing:
            return super().keyPressEvent(event)

        key = event.key()
        mod_names = {
            Qt.Key_Control: "ctrl",
            Qt.Key_Alt: "alt",
            Qt.Key_Shift: "shift",
            Qt.Key_Meta: "win",
        }
        if key in mod_names:
            self._modifiers.add(mod_names[key])
            return

        text = event.text()
        key_name = text.upper() if text and text.isprintable() and text.strip() else QKeySequence(key).toString()
        if not key_name:
            return

        combo_parts = list(self._modifiers) + [key_name.lower()]
        new_hotkey = "+".join(combo_parts)

        self._capturing = False
        self.releaseKeyboard()
        self.setProperty("recording", "false")
        self.setText(hotkey_to_display(new_hotkey))
        self.setStyleSheet(self.styleSheet())
        if self._on_capture_end:
            try:
                self._on_capture_end()
            except Exception:
                logger.exception("on_capture_end callback failed")
        self._on_captured(new_hotkey)

    def keyReleaseEvent(self, event):
        if not self._capturing:
            return super().keyReleaseEvent(event)


class SquirclePanel(QWidget):
    """A true superellipse-shaped panel (continuous corner curvature, not
    circular-arc rounded corners) with a soft layered drop shadow.

    Used as the visible "card" inside a larger transparent, frameless,
    click-through-at-the-edges window. The extra transparent margin around
    this panel (glass.SHADOW_MARGIN) is what gives QGraphicsDropShadowEffect
    room to actually render its blur — without that margin the shadow gets
    clipped at the window edge and silently disappears.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setXOffset(0)
        shadow.setYOffset(14)
        shadow.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(shadow)

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
        # Fixed pixel corner radius (not a whole-panel superellipse) — reads
        # as a genuine squircle regardless of the panel's tall aspect ratio.
        path = glass.squircle_path(rect, radius=glass.SQUIRCLE_RADIUS, n=4.0)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 255))
        painter.drawPath(path)

        painter.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

        painter.end()


class SettingsWindow(QWidget):
    def __init__(self, config, history, on_hotkey_changed=None,
                 on_model_changed=None, on_sound_toggled=None,
                 on_hotkey_capture_start=None, on_hotkey_capture_end=None):
        super().__init__()
        self.config = config
        self.history = history
        self.on_hotkey_changed = on_hotkey_changed
        self.on_model_changed = on_model_changed
        self.on_sound_toggled = on_sound_toggled
        self.on_hotkey_capture_start = on_hotkey_capture_start
        self.on_hotkey_capture_end = on_hotkey_capture_end
        self._pending_hotkey = self.config.get("hotkey", "ctrl+shift+s")
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Settings")
        # Feature 5.3: Increased default size for better layout and spacing.
        # The window itself is now the panel size PLUS shadow margin on all
        # sides — the panel keeps the original 460x640 visual size, the
        # window is just the transparent canvas the shadow bleeds into.
        panel_w, panel_h = 460, 640
        margin = glass.SHADOW_MARGIN
        self.setFixedSize(panel_w + margin * 2, panel_h + margin * 2)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)

        window_layout = QVBoxLayout(self)
        window_layout.setContentsMargins(margin, margin, margin, margin)
        window_layout.setSpacing(0)

        self._panel = SquirclePanel()
        self._panel.setObjectName("settingsPanel")
        self._panel.setFixedSize(panel_w, panel_h)
        self._panel.setStyleSheet(GLASS_STYLE)
        window_layout.addWidget(self._panel)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 16)
        title = QLabel("Settings")
        title.setObjectName("windowTitle")
        title.setFont(QFont(glass.QFONT_FAMILY, 17))
        header_layout.addWidget(title)
        outer.addWidget(header)

        divider1 = self._divider()
        outer.addWidget(divider1)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 8)
        body_layout.setSpacing(14)

        trigger_label = QLabel("TRIGGER")
        trigger_label.setObjectName("sectionLabel")
        body_layout.addWidget(trigger_label)

        hotkey_row = QHBoxLayout()
        lbl_hk = QLabel("Hotkey")
        lbl_hk.setFont(QFont(glass.QFONT_FAMILY, 12))
        hotkey_row.addWidget(lbl_hk)
        hotkey_row.addStretch()
        self.hotkey_btn = HotkeyCaptureButton(
            hotkey_to_display(self._pending_hotkey),
            on_captured=self._on_hotkey_captured,
            on_capture_start=self.on_hotkey_capture_start,
            on_capture_end=self.on_hotkey_capture_end,
        )
        hotkey_row.addWidget(self.hotkey_btn)
        body_layout.addLayout(hotkey_row)

        body_layout.addSpacing(6)

        voice_label = QLabel("VOICE")
        voice_label.setObjectName("sectionLabel")
        body_layout.addWidget(voice_label)

        model_row = QHBoxLayout()
        lbl_mod = QLabel("Whisper model")
        lbl_mod.setFont(QFont(glass.QFONT_FAMILY, 12))
        model_row.addWidget(lbl_mod)
        model_row.addStretch()
        self.model_combo = QComboBox()
        self.model_combo.addItems(WHISPER_MODELS)
        current_model = self.config.get("model", "tiny")
        if current_model not in WHISPER_MODELS:
            logger.warning("Unrecognized Whisper model '%s' in config; adding as a custom entry", current_model)
            self.model_combo.addItem(current_model)
        self.model_combo.setCurrentText(current_model)
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo)
        body_layout.addLayout(model_row)

        body_layout.addSpacing(4)

        self.sound_checkbox = QCheckBox("Play sound cues")
        self.sound_checkbox.setFont(QFont(glass.QFONT_FAMILY, 12))
        self.sound_checkbox.setChecked(bool(self.config.get("sound_enabled", True)))
        self.sound_checkbox.toggled.connect(self._on_sound_toggled)
        body_layout.addWidget(self.sound_checkbox)

        body_layout.addSpacing(6)

        history_label = QLabel("HISTORY")
        history_label.setObjectName("sectionLabel")
        body_layout.addWidget(history_label)

        self.history_list = QListWidget()
        self.history_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._load_history()
        body_layout.addWidget(self.history_list)

        outer.addWidget(body)

        divider2 = self._divider()
        outer.addWidget(divider2)

        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 16, 24, 20)

        clear_btn = QPushButton("Clear history")
        clear_btn.clicked.connect(self._clear_history)
        footer_layout.addWidget(clear_btn)
        footer_layout.addStretch()

        done_btn = QPushButton("Done")
        done_btn.setObjectName("primaryBtn")
        done_btn.clicked.connect(self._save_and_close)
        footer_layout.addWidget(done_btn)

        outer.addWidget(footer)

        self._panel.setLayout(outer)

    def _divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("background: rgba(255,255,255,0.10); max-height: 1px; border: none;")
        return line

    def _on_hotkey_captured(self, new_hotkey: str):
        self._pending_hotkey = new_hotkey

    def _on_model_changed(self, new_model: str):
        old_model = self.config.get("model", "tiny")
        if new_model == old_model:
            return
        self.config.set("model", new_model)
        self.config.save()
        if self.on_model_changed:
            try:
                self.on_model_changed(new_model)
            except Exception:
                logger.exception("Failed to apply new Whisper model live")

    def _on_sound_toggled(self, checked: bool):
        self.config.set("sound_enabled", checked)
        self.config.save()
        if self.on_sound_toggled:
            try:
                self.on_sound_toggled(checked)
            except Exception:
                logger.exception("Failed to apply sound toggle live")

    def _save_and_close(self):
        old_hotkey = self.config.get("hotkey", "ctrl+shift+s")
        self.config.set("hotkey", self._pending_hotkey)
        self.config.save()
        if self._pending_hotkey != old_hotkey and self.on_hotkey_changed:
            try:
                self.on_hotkey_changed(self._pending_hotkey)
            except Exception:
                logger.exception("Failed to apply new hotkey live")
        self.hide()

    def _load_history(self):
        self.history_list.clear()
        for entry in self.history.load():
            item = QListWidgetItem(self.history_list)
            row_widget = HistoryRowWidget(entry['timestamp'], entry['text'])
            item.setSizeHint(QSize(0, 36))
            self.history_list.setItemWidget(item, row_widget)

    def _clear_history(self):
        self.history.clear()
        self.history_list.clear()

    def focus_history(self):
        self.history_list.setFocus()
        if self.history_list.count() > 0:
            self.history_list.setCurrentRow(0)

    def show(self):
        self._load_history()
        self._pending_hotkey = self.config.get("hotkey", "ctrl+shift+s")
        self.hotkey_btn.setText(hotkey_to_display(self._pending_hotkey))

        current_model = self.config.get("model", "tiny")
        if self.model_combo.findText(current_model) < 0:
            self.model_combo.addItem(current_model)
        self.model_combo.blockSignals(True)
        self.model_combo.setCurrentText(current_model)
        self.model_combo.blockSignals(False)

        self.sound_checkbox.blockSignals(True)
        self.sound_checkbox.setChecked(bool(self.config.get("sound_enabled", True)))
        self.sound_checkbox.blockSignals(False)

        super().show()
