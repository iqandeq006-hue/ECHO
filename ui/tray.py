import os
import logging
from PyQt5.QtWidgets import QSystemTrayIcon, QMenu, QAction
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PyQt5.QtCore import Qt, QTimer

from ui import glass
from core.theme import is_light_theme

logger = logging.getLogger(__name__)

# Sizes Windows' shell notification API commonly requests for the tray icon
# itself and for showMessage() balloons (the balloon icon in particular
# wants an exact 40x40 "large icon" — see Shell_NotifyIcon docs). Pre-baking
# these avoids QIcon's on-the-fly scaling, which can land on an off-by-one
# non-square result (e.g. 40x38) when the source image isn't perfectly
# square, triggering "Wrong icon size" warnings.
_STANDARD_ICON_SIZES = (16, 24, 32, 40, 48, 256)

# Windows gives no Qt signal for "the app theme changed" — QSystemTrayIcon
# has nothing like it. This polls a single registry read, which is cheap
# (microseconds) compared to the GetWindowRect polling already confirmed
# negligible for the taskbar watcher (Features 1/2), so reusing the same
# poll-based approach here is consistent rather than an extra risk.
_THEME_POLL_MS = 1500

# NOTE, read this twice — the mapping is the opposite of what it looks like
# at first glance:
#   Windows in LIGHT mode -> tray background is LIGHT -> need the DARK logo
#   Windows in DARK mode  -> tray background is DARK  -> need the LIGHT logo
# This matches doc/FEATURE.md section 3 verbatim ("Light Mode: use the dark
# ECHO logo. Dark Mode: use the light ECHO logo."). Filenames below are
# named for the icon's own color, not for the Windows mode that triggers
# it, specifically so this dict is the only place that mapping has to be
# gotten right.
# Priority filenames for each theme:
# Windows in LIGHT mode -> needs DARK logo
# Windows in DARK mode  -> needs LIGHT logo
_THEME_ICON_CANDIDATES = {
    True: [  # Light theme
        "ECHO_AIOS_dark.png", "ECHO_dark.png", "ECHO_AIOS_dark.ico", "ECHO_dark.ico",
        "ECHO_AIOS.png", "ECHO.png", "ECHO_AIOS.ico", "ECHO.ico"
    ],
    False: [  # Dark theme
        "ECHO_AIOS_light.png", "ECHO_light.png", "ECHO_AIOS_light.ico", "ECHO_light.ico",
        "ECHO_AIOS.png", "ECHO.png", "ECHO_AIOS.ico", "ECHO.ico"
    ]
}

# QMenu can't use backdrop-filter blur (that's a real OS-level capability
# QSS doesn't expose), so this gets as close as possible to the same glass
# language with a solid-but-translucent panel, the same accent border, and
# the same radius scale as every other surface in the app.
TRAY_MENU_STYLE = f"""
    QMenu {{
        background: rgba(18, 18, 20, 0.96);
        color: white;
        border: 0.5px solid rgba({glass.ACCENT_RGB}, 0.4);
        border-radius: 16px;
        padding: 8px;
    }}
    QMenu::item {{
        padding: 8px 26px 8px 16px;
        border-radius: 9px;
        font-size: 13px;
    }}
    QMenu::item:selected {{
        background: rgba({glass.ACCENT_RGB}, 0.30);
    }}
    QMenu::separator {{
        height: 0.5px;
        background: rgba(255, 255, 255, 0.12);
        margin: 6px 8px;
    }}
"""


class TrayIcon:
    @staticmethod
    def _load_icon(icon_path: str) -> QIcon:
        """Build a QIcon with exact square pixmaps at the standard sizes
        Windows' shell notification API expects, instead of relying on
        QIcon to scale a single (slightly non-square-aspect) source image
        on demand."""
        source = QPixmap(icon_path)
        icon = QIcon()
        if source.isNull():
            logger.warning("Failed to load tray icon image at %s", icon_path)
            return icon

        for size in _STANDARD_ICON_SIZES:
            scaled = source.scaled(
                size, size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            # Center the (possibly non-square-source) result on an exact
            # size x size square canvas so every advertised pixmap is truly
            # size x size, never e.g. 40x38.
            canvas = QPixmap(size, size)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            x = (size - scaled.width()) // 2
            y = (size - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
            painter.end()
            icon.addPixmap(canvas)

        return icon

    def __init__(self, on_settings, on_history, on_quit):
        self.on_settings = on_settings
        self.on_history = on_history
        self.on_quit = on_quit

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._search_dirs = [
            os.path.join(base_dir, "assets"),
            os.path.join(base_dir, "assets", "icons"),
        ]
        # None (not True/False) on purpose: guarantees the first
        # _apply_theme_icon() call below actually sets an icon instead of
        # short-circuiting on a false "no change" match against a real bool.
        self._current_is_light = None

        self.tray = QSystemTrayIcon()
        self.tray.setToolTip("Voice Overlay — Running")
        self._apply_theme_icon()

        self.menu = QMenu()
        self.menu.setStyleSheet(TRAY_MENU_STYLE)

        self.settings_action = QAction("Settings", self.menu)
        self.settings_action.triggered.connect(self.on_settings)
        self.menu.addAction(self.settings_action)

        self.history_action = QAction("History", self.menu)
        self.history_action.triggered.connect(self.on_history)
        self.menu.addAction(self.history_action)

        self.menu.addSeparator()

        self.logs_action = QAction("View Logs", self.menu)
        self.logs_action.triggered.connect(self._open_logs_folder)
        self.menu.addAction(self.logs_action)

        self.menu.addSeparator()

        self.quit_action = QAction("Quit", self.menu)
        self.quit_action.triggered.connect(self.on_quit)
        self.menu.addAction(self.quit_action)

        self.tray.setContextMenu(self.menu)

        # Parented to self.tray (a QObject) rather than left parentless, so
        # it's cleaned up automatically alongside the tray icon rather than
        # relying only on the Python-side self._theme_timer reference.
        self._theme_timer = QTimer(self.tray)
        self._theme_timer.timeout.connect(self._apply_theme_icon)
        self._theme_timer.start(_THEME_POLL_MS)

    def _apply_theme_icon(self):
        """Re-check the active Windows theme and swap the tray icon only if
        it actually changed since the last check."""
        light = is_light_theme()
        if light == self._current_is_light:
            return
        self._current_is_light = light

        candidates = _THEME_ICON_CANDIDATES.get(light, _THEME_ICON_CANDIDATES[False])
        icon_path = None

        for directory in self._search_dirs:
            if not os.path.isdir(directory):
                continue
            for candidate in candidates:
                full_path = os.path.join(directory, candidate)
                if os.path.exists(full_path):
                    icon_path = full_path
                    break
            if icon_path:
                break

        if icon_path and os.path.exists(icon_path):
            self.tray.setIcon(self._load_icon(icon_path))
            logger.info("Tray icon set from '%s' (theme=%s)", icon_path, "light" if light else "dark")
        else:
            logger.warning(
                "No tray icon found in search directories: %s; keeping previous icon",
                self._search_dirs
            )

    def _open_logs_folder(self):
        """Open the folder containing ECHO.log in the system file explorer
        (Explorer on Windows, Finder on macOS, the default file manager on
        Linux), so the user can grab logs for troubleshooting without
        knowing the %APPDATA% path by heart."""
        try:
            from config.logging_config import LOG_DIR
            import subprocess
            import platform
            if platform.system() == "Windows":
                os.startfile(LOG_DIR)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", LOG_DIR])
            else:
                subprocess.Popen(["xdg-open", LOG_DIR])
        except Exception:
            logger.exception("Failed to open logs folder")

    def show(self):
        self.tray.show()
        self.tray.showMessage(
            "ECHO",
            "ECHO is live.\nAt your service.",
            self.tray.icon(),
            3000
        )

    def notify(self, title: str, message: str):
        """Show a tray balloon notification."""
        self.tray.showMessage(title, message, self.tray.icon(), 3000)
