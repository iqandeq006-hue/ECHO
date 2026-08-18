"""
Windows shell watcher for taskbar position tracking and topmost re-assertion.

Features 1 & 2:
- Polls Shell_TrayWnd to detect taskbar position and slide animations.
- Periodically re-asserts HWND_TOPMOST to ensure the overlay stays above all windows.
"""

import ctypes
import platform
import logging
from PyQt5.QtCore import QObject, QTimer, pyqtSignal, QRect
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QCursor

logger = logging.getLogger(__name__)

if platform.system() == "Windows":
    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    user32 = ctypes.windll.user32
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
else:
    user32 = None


class ShellWatcher(QObject):
    """Watcher that polls the Windows taskbar rect and re-asserts z-order topmost."""

    position_changed = pyqtSignal()

    def __init__(self, target_hwnd_func, parent=None):
        super().__init__(parent)
        self.target_hwnd_func = target_hwnd_func
        self._last_taskbar_top = None

        if platform.system() == "Windows":
            self._timer = QTimer(self)
            self._timer.setInterval(30)
            self._timer.timeout.connect(self._tick)
            self._timer.start()

    def get_taskbar_top_for_screen(self, screen) -> int | None:
        if platform.system() != "Windows" or not user32:
            return None
        try:
            geo = screen.geometry()
            for class_name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                hwnd = user32.FindWindowW(class_name, None)
                while hwnd:
                    rect = RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        if rect.left < geo.right() and rect.right > geo.left() and rect.top < geo.bottom() and rect.bottom > geo.top():
                            return rect.top
                    hwnd = user32.FindWindowExW(None, hwnd, class_name, None)
        except Exception:
            logger.exception("Error checking taskbar rect")
        return None

    def _tick(self):
        if platform.system() != "Windows" or not user32:
            return

        # 1. Re-assert Topmost z-order (Feature 2)
        try:
            hwnd = self.target_hwnd_func()
            if hwnd:
                user32.SetWindowPos(
                    hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                )
        except Exception:
            logger.exception("Failed to reassert HWND_TOPMOST")

        # 2. Track Taskbar rect changes (Feature 1)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            taskbar_top = self.get_taskbar_top_for_screen(screen)
            if taskbar_top != self._last_taskbar_top:
                self._last_taskbar_top = taskbar_top
                self.position_changed.emit()
