import ctypes
import math
import platform
import time
import logging
from PyQt5.QtWidgets import QWidget, QTextEdit, QPushButton, QLabel, QApplication
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import QFont, QColor, QPainter, QPen, QPainterPath, QCursor, QFontDatabase
import pyperclip

from ui import glass
from core.shell_watcher import ShellWatcher

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sizes
# ---------------------------------------------------------------------------
HUD_W, HUD_H           = 64, 20
HUD_HOVER_W, HOVER_H   = 76, 20
RECORDING_W, RECORDING_H = 148, 36
PROCESSING_D           = 32          # circle diameter during processing
PROCESSING_W           = PROCESSING_D
PROCESSING_H           = PROCESSING_D
MESSAGE_H              = 34
CARD_W                 = 320
CARD_MIN_H             = 110
CARD_MAX_H             = 200
TEXT_MAX_H             = 96
BOTTOM_MARGIN          = 18

FIGTREE = glass.QFONT_FAMILY

TEXT_STYLE = """
    QTextEdit {
        background: transparent;
        color: #ffffff;
        border: none;
        padding: 0;
        selection-background-color: rgba(255, 255, 255, 0.20);
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
        font-weight: 400;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 4px;
        margin: 2px 0px;
    }
    QScrollBar::handle:vertical {
        background: rgba(255, 255, 255, 0.20);
        border-radius: 2px;
        min-height: 18px;
    }
    QScrollBar::handle:vertical:hover {
        background: rgba(255, 255, 255, 0.40);
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

MESSAGE_LABEL_STYLE = """
    QLabel {
        background: transparent;
        color: #ffffff;
        border: none;
        font-family: 'Inter', 'Figtree', 'Segoe UI', system-ui, sans-serif;
        font-weight: 700;
    }
"""


class IslandSurface(QWidget):
    """Custom-painted overlay for all states (including Boot State & Card Timer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "idle"
        self.caption = ""

        # boot state (Feature 6 & 7)
        self.boot_dot_phase = 0.0
        self.boot_glow_alpha = 0.0

        # recording
        self.wave_mirror_phase = 0.0

        # processing — spinning arcs
        self.spin_angle = 0.0          # degrees, counts up
        self.morph_t = 0.0             # 0..1  pill → circle morph
        self.morph_done = False

        # transcript card timer (Feature 8)
        self.card_progress = 1.0       # 1.0 -> 0.0 for 8s timer hairline

        # done flash
        self.done_alpha = 0.0          # 0..1 fade for "Done" label

        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_mode(self, mode: str, caption: str = ""):
        self.mode = mode
        self.caption = caption
        if mode == "boot":
            self.boot_dot_phase = 0.0
        elif mode == "processing":
            self.spin_angle = 0.0
            self.morph_t = 0.0
            self.morph_done = False
        if mode != "done":
            self.done_alpha = 0.0
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setClipRect(self.rect())

        if self.mode == "boot":
            self._paint_boot(painter)
        elif self.mode == "idle":
            self._paint_idle(painter)
        elif self.mode == "recording":
            self._paint_recording(painter)
        elif self.mode == "processing":
            self._paint_processing(painter)
        elif self.mode == "done":
            self._paint_done(painter)
        elif self.mode == "card":
            self._paint_card(painter)
        elif self.mode in {"no_speech", "error"}:
            self._paint_message(painter)
        else:
            self._paint_idle(painter)
        painter.end()

    # ── shared shell ────────────────────────────────────────────────────────

    def _pill_shell(self, painter, rect, radius, border_alpha=56, bg=True):
        """Plain pitch-black pill with a white border."""
        painter.save()
        painter.setPen(Qt.NoPen)
        if bg:
            painter.setBrush(QColor(0, 0, 0, 255))
            painter.drawRoundedRect(rect, radius, radius)
        pen = QPen(QColor(255, 255, 255, border_alpha), 1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        painter.restore()

    # ── boot state (Feature 6 & 7) ──────────────────────────────────────────

    def _paint_boot(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        r = rect.height() / 2.0
        border_a = int(min(255, 56 + self.boot_glow_alpha * 190))
        self._pill_shell(painter, rect, r, border_alpha=border_a)

        # Three horizontally aligned dots with sequential pulse animation
        dot_count = 3
        gap = 8.0
        dot_r = 2.0
        total_w = (dot_count - 1) * gap
        cx = rect.center().x()
        cy = rect.center().y()
        start_x = cx - total_w / 2.0

        painter.save()
        painter.setPen(Qt.NoPen)
        for i in range(dot_count):
            # Sequential pulse wave
            val = (math.sin(self.boot_dot_phase * 2.5 + i * 0.95) + 1.0) / 2.0
            alpha = int(90 + val * 165)
            x = start_x + i * gap
            dot_rect = QRectF(x - dot_r, cy - dot_r, dot_r * 2.0, dot_r * 2.0)
            painter.setBrush(QColor(255, 255, 255, alpha))
            painter.drawEllipse(dot_rect)
        painter.restore()

    # ── idle ────────────────────────────────────────────────────────────────

    def _paint_idle(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        r = rect.height() / 2.0
        border_a = int(min(255, 56 + self.boot_glow_alpha * 190))
        self._pill_shell(painter, rect, r, border_alpha=border_a)

    # ── recording: animated waveform ────────────────────────────────────────

    def _paint_recording(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        r = rect.height() / 2.0
        self._pill_shell(painter, rect, r, border_alpha=72)
        self._paint_waveform(painter, rect)

    def _paint_waveform(self, painter, rect):
        bar_count = 9
        mid = bar_count // 2
        gap = 7.0
        total_w = (bar_count - 1) * gap
        start_x = rect.center().x() - total_w / 2.0
        center_y = rect.center().y()
        max_h = rect.height() * 0.62

        painter.save()
        painter.setPen(Qt.NoPen)
        for i in range(bar_count):
            dist = abs(i - mid)
            base_fraction = max(0.18, 1.0 - dist * 0.16)
            wobble = (math.sin(self.wave_mirror_phase * 2.4 + dist * 0.9 + i * 0.5) + 1.0) / 2.0
            fraction = base_fraction * (0.45 + 0.55 * wobble)
            h = max(2.5, max_h * fraction)
            x = start_x + i * gap
            bar_rect = QRectF(x - 1.5, center_y - h / 2.0, 3.0, h)
            painter.setBrush(QColor(255, 255, 255, 220))
            painter.drawRoundedRect(bar_rect, 1.5, 1.5)
        painter.restore()

    # ── processing: pill morphs to circle, three arcs spin CCW ─────────────

    def _paint_processing(self, painter):
        t = min(1.0, self.morph_t)
        ease = t * t * (3.0 - 2.0 * t)          # smoothstep

        # interpolate size: pill → circle
        pill_w = float(RECORDING_W - 2)
        pill_h = float(RECORDING_H - 2)
        circ_d = float(PROCESSING_D - 2)

        cur_w = pill_w + (circ_d - pill_w) * ease
        cur_h = pill_h + (circ_d - pill_h) * ease

        cx = self.width() / 2.0
        cy = self.height() / 2.0
        rect = QRectF(cx - cur_w / 2.0, cy - cur_h / 2.0, cur_w, cur_h)
        r = rect.height() / 2.0

        # black fill
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 255))
        painter.drawRoundedRect(rect, r, r)
        painter.restore()

        if ease < 0.95:
            # still morphing — just draw faint border
            border_a = int(56 + (0 - 56) * ease)
            painter.save()
            painter.setPen(QPen(QColor(255, 255, 255, border_a), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), r, r)
            painter.restore()
        else:
            # fully a circle — paint three spinning arcs
            self._paint_spin_arcs(painter, cx, cy, circ_d / 2.0 - 1.0)

    def _paint_spin_arcs(self, painter, cx, cy, radius):
        """Three arc segments rotating counter-clockwise, evenly spaced."""
        arc_span = 100          # degrees each arc covers
        gap_span = 20           # gap between arcs
        alphas = [255, 140, 60] # bright → mid → dim

        painter.save()
        for i, alpha in enumerate(alphas):
            start_deg = self.spin_angle + i * (arc_span + gap_span)
            start_qt = int(start_deg * 16)
            span_qt  = int(arc_span * 16)

            pen = QPen(QColor(255, 255, 255, alpha), 2.0)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)

            r = radius
            arc_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawArc(arc_rect, start_qt, span_qt)
        painter.restore()

    # ── done flash ───────────────────────────────────────────────────────────

    def _paint_done(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        r = rect.height() / 2.0
        self._pill_shell(painter, rect, r, border_alpha=int(56 * self.done_alpha))

        painter.save()
        a = int(255 * self.done_alpha)
        painter.setPen(QColor(255, 255, 255, a))
        font = QFont(FIGTREE, 12)
        font.setWeight(QFont.Bold)
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, "Done")
        painter.restore()

    # ── transcript card (Feature 8) ─────────────────────────────────────────

    def _paint_card(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        self._pill_shell(painter, rect, glass.RADIUS_CARD, border_alpha=40)

        # Feature 8: Hairline bottom timer border decreasing smoothly over 8s duration
        if self.card_progress > 0.0:
            painter.save()
            line_w = rect.width() * min(1.0, max(0.0, self.card_progress))
            if line_w > 0:
                x_start = rect.left() + (rect.width() - line_w) / 2.0
                y = rect.bottom() - 0.5
                pen = QPen(QColor(255, 255, 255, 220), 1.0)
                painter.setPen(pen)
                painter.drawLine(QPointF(x_start, y), QPointF(x_start + line_w, y))
            painter.restore()

    # ── message states ────────────────────────────────────────────────────────

    def _paint_message(self, painter):
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        r = rect.height() / 2.0
        is_error = self.mode == "error"
        border_a = 100 if is_error else 56
        self._pill_shell(painter, rect, r, border_alpha=border_a)


class OverlayIndicator(QWidget):
    signal_request_idle = pyqtSignal()

    def __init__(self, sound_cues=None):
        super().__init__()
        self._mode = "boot"
        self._near = False
        self._geometry_animation = None
        self._pending_transcript = None
        self._processing_finished = False
        self._processing_failed_kind = None
        self._paste_succeeded = False
        self._outcome_signaled = False
        self._card_start_time = 0.0
        self.sound_cues = sound_cues

        self._build_ui()

        # Features 1 & 2: ShellWatcher for taskbar tracking and continuous topmost re-assertion
        self.shell_watcher = ShellWatcher(
            target_hwnd_func=lambda: int(self.winId()) if self.winId() else 0,
            parent=self
        )
        self.shell_watcher.position_changed.connect(self._position_bottom_center)

        self._revert_timer = QTimer(self)
        self._revert_timer.setSingleShot(True)
        self._revert_timer.timeout.connect(self._idle)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_transcript)

        # 60 FPS
        self._motion_timer = QTimer(self)
        self._motion_timer.setInterval(16)
        self._motion_timer.timeout.connect(self._tick)
        self._motion_timer.start()

        self._cursor_timer = QTimer(self)
        self._cursor_timer.setInterval(120)
        self._cursor_timer.timeout.connect(self._check_cursor)
        self._cursor_timer.start()

    # ── construction ─────────────────────────────────────────────────────────

    def _target_size_for_mode(self, mode):
        sizes = {
            "boot":       (HUD_W, HUD_H),
            "idle":       (HUD_W, HUD_H),
            "recording":  (RECORDING_W, RECORDING_H),
            "processing": (PROCESSING_W, PROCESSING_H),
        }
        if mode in sizes:
            return sizes[mode]
        if mode == "done":
            return (self._measure_message_width("Done"), MESSAGE_H)
        if mode == "no_speech":
            return (self._measure_message_width("No speech detected"), MESSAGE_H)
        if mode == "error":
            return (self._measure_message_width("Couldn\u2019t transcribe"), MESSAGE_H)
        return (HUD_W, HUD_H)

    def _measure_message_width(self, text):
        from PyQt5.QtGui import QFontMetrics
        font = QFont(FIGTREE, 12)
        font.setWeight(QFont.Bold)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(text)
        return max(120, text_w + 44)

    def _transcript_height_for_text(self, text):
        chars_per_line = 34
        wrapped_lines = sum(max(1, (len(line) + chars_per_line - 1) // chars_per_line)
                            for line in (text.splitlines() or [""]))
        pad = 16 * 2
        button_row_h = 30 + 8
        line_h = 17
        safety_buffer = 10
        estimated = pad + button_row_h + wrapped_lines * line_h + safety_buffer
        return max(CARD_MIN_H, min(CARD_MAX_H, estimated))

    def _build_ui(self):
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
            Qt.Tool | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setStyleSheet("QWidget { background: transparent; }")

        if platform.system() == "Windows":
            try:
                hwnd = int(self.winId())
                GWL_EXSTYLE = -20
                WS_EX_NOACTIVATE = 0x08000000
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
            except Exception:
                logger.exception("Failed to set Windows window style")

        self.surface = IslandSurface(self)

        self.text_edit = QTextEdit(self)
        self.text_edit.setReadOnly(True)
        font = QFont(FIGTREE, 11)
        font.setWeight(QFont.Normal)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet(TEXT_STYLE)
        self.text_edit.document().setDocumentMargin(0)
        self.text_edit.setFrameStyle(0)
        self.text_edit.hide()

        self.message_label = QLabel(self)
        font_msg = QFont(FIGTREE, 12)
        font_msg.setWeight(QFont.Bold)
        self.message_label.setFont(font_msg)
        self.message_label.setStyleSheet(MESSAGE_LABEL_STYLE)
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.hide()

        self.copy_btn = QPushButton(self)
        self.copy_btn.setIcon(self._make_text_icon("copy"))
        self.copy_btn.setStyleSheet(glass.GLASS_PRIMARY_BUTTON_STYLE)
        self.copy_btn.clicked.connect(self._on_copy)
        self.copy_btn.hide()

        self.close_btn = QPushButton(self)
        self.close_btn.setIcon(self._make_text_icon("close"))
        self.close_btn.setStyleSheet(glass.GLASS_BUTTON_STYLE)
        self.close_btn.clicked.connect(self._hide_transcript)
        self.close_btn.hide()

        self.resize(*self._target_size_for_mode("boot"))
        self._position_bottom_center()
        self._layout_children()
        self._set_mode("boot")

    def _make_text_icon(self, kind):
        from PyQt5.QtGui import QIcon, QPixmap, QPainter as _P
        pix = QPixmap(16, 16)
        pix.fill(Qt.transparent)
        p = _P(pix)
        p.setRenderHint(_P.Antialiasing, True)
        if kind == "copy":
            pen = QPen(QColor(0, 0, 0, 230), 1.4)
        else:
            pen = QPen(QColor(255, 255, 255, 180), 1.4)
        p.setPen(pen)
        from PyQt5.QtCore import QRectF as _R, QPointF as _PF
        if kind == "copy":
            p.drawRoundedRect(_R(3, 2, 9, 11), 1.5, 1.5)
            p.drawRoundedRect(_R(5, 4, 9, 11), 1.5, 1.5)
        else:
            p.drawLine(_PF(3, 3), _PF(13, 13))
            p.drawLine(_PF(13, 3), _PF(3, 13))
        p.end()
        return QIcon(pix)

    # ── geometry (Feature 1: Adaptive Taskbar Position) ──────────────────────

    def _target_rect(self, width, height):
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        avail = screen.availableGeometry()
        bottom_y = avail.bottom() + 1

        # Check real-time taskbar rect from ShellWatcher (auto-hide, visible, sliding)
        if hasattr(self, "shell_watcher") and self.shell_watcher:
            tb_top = self.shell_watcher.get_taskbar_top_for_screen(screen)
            if tb_top is not None and tb_top > 0:
                bottom_y = min(bottom_y, tb_top)

        return QRect(
            avail.x() + (avail.width() - width) // 2,
            bottom_y - height - BOTTOM_MARGIN,
            width, height
        )

    def _position_bottom_center(self):
            target = self._target_rect(self.width(), self.height())
            if self.geometry() == target:
                return
            if getattr(self, "_track_animation", None) and \
                    self._track_animation.state() == QPropertyAnimation.Running:
                self._track_animation.stop()
            self._track_animation = QPropertyAnimation(self, b"geometry")
            self._track_animation.setDuration(160)
            self._track_animation.setEasingCurve(QEasingCurve(QEasingCurve.OutCubic))
            self._track_animation.setStartValue(self.geometry())
            self._track_animation.setEndValue(target)
            self._track_animation.start()

    def _animate_to(self, width, height, growing=True, duration=None):
        if duration is None:
            duration = glass.GROW_DURATION_MS if growing else glass.SHRINK_DURATION_MS
        curve = glass.grow_curve() if growing else glass.shrink_curve()
        self._geometry_animation = QPropertyAnimation(self, b"geometry")
        self._geometry_animation.setDuration(duration)
        self._geometry_animation.setEasingCurve(curve)
        self._geometry_animation.setStartValue(self.geometry())
        self._geometry_animation.setEndValue(self._target_rect(width, height))
        self._geometry_animation.start()

    def _layout_children(self):
        self.surface.setGeometry(0, 0, self.width(), self.height())
        if self._mode == "card":
            pad = 16
            button_row_h = 30
            text_h = min(TEXT_MAX_H, self.height() - pad * 2 - button_row_h - 8)
            self.text_edit.setGeometry(pad, pad, self.width() - pad * 2, text_h)
            btn_y = pad + text_h + 8
            self.close_btn.setGeometry(self.width() - pad - 30 - 8 - 30, btn_y, 30, 30)
            self.copy_btn.setGeometry(self.width() - pad - 30, btn_y, 30, 30)
        elif self._mode in {"no_speech", "error", "done"}:
            self.message_label.setGeometry(8, 0, self.width() - 16, self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_children()

    def _set_mode(self, mode, caption=""):
        self._mode = mode
        self.surface.set_mode(mode, caption=caption)

    # ── tick (60 FPS) ─────────────────────────────────────────────────────────

    def _tick(self):
        if self.surface.boot_glow_alpha > 0.0:
            self.surface.boot_glow_alpha = max(0.0, self.surface.boot_glow_alpha - 0.02)
            self.surface.update()

        if self._mode == "boot":
            self.surface.boot_dot_phase += 0.09
            self.surface.update()

        elif self._mode == "idle":
            self.surface.idle_breath_phase = getattr(self.surface, "idle_breath_phase", 0.0)
            self.surface.idle_breath_phase = (self.surface.idle_breath_phase + 0.006) % 1.0
            breath = (math.sin(self.surface.idle_breath_phase * math.tau) + 1.0) / 2.0
            self.setWindowOpacity(0.90 + 0.08 * breath)

        elif self._mode == "recording":
            self.surface.wave_mirror_phase += 0.09
            self.surface.update()

        elif self._mode == "processing":
            if not self.surface.morph_done:
                self.surface.morph_t += 0.06
                if self.surface.morph_t >= 1.0:
                    self.surface.morph_t = 1.0
                    self.surface.morph_done = True
            self.surface.spin_angle = (self.surface.spin_angle + 4.0) % 360.0
            self.surface.update()

        elif self._mode == "card":
            # Feature 8: Timer hairline countdown computation
            if self._card_start_time > 0:
                elapsed = (time.time() - self._card_start_time) * 1000.0
                self.surface.card_progress = max(0.0, 1.0 - elapsed / 8000.0)
                self.surface.update()

        elif self._mode == "done":
            self.surface.update()

    # ── cursor hover (idle only) ───────────────────────────────────────────────

    def _check_cursor(self):
        if self._mode != "idle":
            return
        near = self.geometry().adjusted(-18, -18, 18, 18).contains(QCursor.pos())
        if near == self._near:
            return
        self._near = near
        if near:
            self._animate_to(HUD_HOVER_W, HOVER_H, growing=True, duration=120)
        else:
            self._animate_to(HUD_W, HUD_H, growing=False, duration=130)

    # ── boot & idle ───────────────────────────────────────────────────────────

    def trigger_boot_glow(self):
        """Feature 7: Visual acknowledgment when a 2nd instance is launched."""
        self.surface.boot_glow_alpha = 1.0
        self.surface.update()

    def _idle(self):
        if self._mode == "recording":
            return
        if self._mode == "processing" and not self._processing_finished:
            return

        self._hide_timer.stop()
        self._revert_timer.stop()
        if self._geometry_animation:
            self._geometry_animation.stop()
            self._geometry_animation = None

        self._pending_transcript = None
        self._processing_finished = False
        self._processing_failed_kind = None
        self._paste_succeeded = False
        self._outcome_signaled = False
        self.surface.morph_t = 0.0
        self.surface.morph_done = False
        self.surface.spin_angle = 0.0
        self.surface.done_alpha = 0.0
        self._near = False

        self.setWindowOpacity(0.92)
        self.text_edit.hide()
        self.message_label.hide()
        self.copy_btn.hide()
        self.close_btn.hide()
        self._set_mode("idle")

        idle_rect = self._target_rect(HUD_W, HUD_H)
        self.setGeometry(idle_rect)
        self.surface.update()

        if not self.isVisible():
            self.show()

        self.signal_request_idle.emit()

    # ── transcript ────────────────────────────────────────────────────────────

    def show_transcript(self, text: str, note: str = None):
        content = text if not note else f"{note}\n\n{text}"
        self._pending_transcript = content
        self.text_edit.setPlainText(content)
        if not self.isVisible():
            self.show()

    def _hide_transcript(self):
        self._hide_timer.stop()
        self.text_edit.clear()
        self._collapse_to_idle()

    def _on_copy(self):
        try:
            pyperclip.copy(self.text_edit.toPlainText())
        except Exception:
            logger.exception("Failed to copy transcript")
        self._hide_transcript()

    # ── state transitions ─────────────────────────────────────────────────────

    def animate_idle_to_recording(self):
        self._outcome_signaled = False
        self._processing_finished = False
        self._processing_failed_kind = None
        self._paste_succeeded = False
        self._pending_transcript = None

        if self.sound_cues:
            self.sound_cues.play("record")
        self._set_mode("recording")
        self.setWindowOpacity(1.0)
        self._animate_to(RECORDING_W, RECORDING_H, growing=True)

    def animate_recording_to_processing(self):
        self._processing_finished = False
        self._processing_failed_kind = None
        self._paste_succeeded = False
        self._outcome_signaled = False
        self.surface.morph_t = 0.0
        self.surface.morph_done = False
        self.surface.spin_angle = 0.0
        self.setWindowOpacity(1.0)
        self._set_mode("processing")
        self._animate_to(PROCESSING_W, PROCESSING_H, growing=False)

    def _on_processing_resolved(self):
        if not self._outcome_signaled or self._mode == "recording":
            return
        kind = self._processing_failed_kind
        if kind == "no_speech":
            self._show_message("no_speech", "No speech detected")
        elif kind == "error":
            self._show_message("error", "Couldn\u2019t transcribe")
        else:
            if self.sound_cues:
                self.sound_cues.play("success")
            if self._pending_transcript:
                self._expand_to_transcript()
            else:
                self._idle()

    def signal_success(self, pasted: bool = False):
        self._processing_failed_kind = None
        self._processing_finished = True
        self._paste_succeeded = pasted
        self._outcome_signaled = True
        QTimer.singleShot(200, self._on_processing_resolved)

    def signal_no_speech(self):
        self._processing_failed_kind = "no_speech"
        self._processing_finished = True
        self._outcome_signaled = True
        QTimer.singleShot(200, self._on_processing_resolved)

    def signal_error(self):
        self._processing_failed_kind = "error"
        self._processing_finished = True
        self._outcome_signaled = True
        QTimer.singleShot(200, self._on_processing_resolved)

    def _show_message(self, mode, text):
        if self.sound_cues:
            self.sound_cues.play(mode)
        self.message_label.setText(text)
        self._set_mode(mode)
        self.message_label.show()
        width = self._target_size_for_mode(mode)[0]
        anim = QPropertyAnimation(self, b"geometry")
        anim.setDuration(glass.MESSAGE_DURATION_MS)
        anim.setEasingCurve(glass.message_curve())
        anim.setStartValue(self.geometry())
        anim.setEndValue(self._target_rect(width, MESSAGE_H))
        anim.start()
        self._geometry_animation = anim
        self._revert_timer.start(2200)

    def _expand_to_transcript(self):
        self.setWindowOpacity(1.0)
        self._set_mode("card")
        self.text_edit.show()
        self.copy_btn.show()
        self.close_btn.show()
        height = self._transcript_height_for_text(self._pending_transcript)
        self.text_edit.setPlainText(self._pending_transcript)
        self._pending_transcript = None

        # Start timer hairline animation (Feature 8)
        self._card_start_time = time.time()
        self.surface.card_progress = 1.0

        self._animate_to(CARD_W, height, growing=True)
        self._hide_timer.start(8000)

    def _collapse_to_idle(self):
        self._card_start_time = 0.0
        self._hide_timer.stop()
        self._revert_timer.stop()
        self.text_edit.hide()
        self.message_label.hide()
        self.copy_btn.hide()
        self.close_btn.hide()
        self._idle()

    # ── public entry ──────────────────────────────────────────────────────────

    def update_state(self, state):
        name = state.name
        if name == "BOOT":
            self._set_mode("boot")
            if not self.isVisible():
                self.show()
        elif name == "IDLE":
            mid_reveal = self._mode == "processing" and self._processing_finished
            if (not self._revert_timer.isActive() and
                    self._mode not in {"card"} and
                    not self._pending_transcript and
                    not mid_reveal):
                self._idle()
        elif name == "RECORDING":
            self._hide_timer.stop()
            self._revert_timer.stop()
            if self._geometry_animation:
                self._geometry_animation.stop()
                self._geometry_animation = None
            self.text_edit.hide()
            self.message_label.hide()
            self.copy_btn.hide()
            self.close_btn.hide()
            self._pending_transcript = None
            self.animate_idle_to_recording()
            if not self.isVisible():
                self.show()
        elif name == "PROCESSING":
            self.animate_recording_to_processing()
            if not self.isVisible():
                self.show()
        elif name == "NO_SPEECH":
            if not self._outcome_signaled:
                self.signal_no_speech()
        elif name == "FAILURE":
            if not self._outcome_signaled:
                self.signal_error()
