import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["HF_HUB_OFFLINE"] = "1"
import sys
import platform
import subprocess
import logging

# ---------------------------------------------------------------------------
# When frozen (PyInstaller build), ffmpeg.exe is bundled right next to
# ECHO.exe (see packaging/echo.spec). Whisper's audio decode shells out to
# `ffmpeg` via subprocess, which only resolves through the system PATH —
# so on a machine without ffmpeg installed globally, that call would fail
# silently. Prepending the bundled folder to PATH here, before anything
# else imports/uses the transcriber, makes the bundled copy discoverable
# exactly like a system install would be. In dev mode (not frozen), this
# is skipped and it falls back to whatever ffmpeg is on your normal PATH.
# ---------------------------------------------------------------------------
if getattr(sys, 'frozen', False):
    _bundled_bin_dir = os.path.dirname(sys.executable)
    os.environ["PATH"] = _bundled_bin_dir + os.pathsep + os.environ.get("PATH", "")

from config.logging_config import setup_logging
from config.config import Config
from core.transcriber import Transcriber, TranscriptionError

setup_logging()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Suppress the console window that briefly flashes when Whisper internally
# shells out to FFmpeg to decode audio. PyInstaller's console=False only
# hides the console for THIS exe, not for child processes it spawns, so
# we patch subprocess.Popen to always pass CREATE_NO_WINDOW on Windows.
# ---------------------------------------------------------------------------
if platform.system() == "Windows":
    _original_popen_init = subprocess.Popen.__init__

    def _patched_popen_init(self, *args, **kwargs):
        if "startupinfo" not in kwargs:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _original_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_popen_init


# ---------------------------------------------------------------------------
# Feature 7: Smart Instance Management via QLocalServer / QLocalSocket IPC.
#
# Replaces the old mutex + QMessageBox approach.  The mutex is retained as
# a secondary safety net (belt-and-suspenders) to guard against the rare
# race where the IPC socket hasn't started listening yet when the second
# instance connects.  But the primary mechanism is now IPC:
#
#   1. Try to wake the running instance via QLocalSocket.
#   2. If that succeeds  → exit silently (no dialog, per spec).
#   3. If that fails     → this IS the first instance; start QLocalServer.
#
# The old QMessageBox dialog is removed entirely per the feature spec.
# ---------------------------------------------------------------------------
_mutex_handle = None  # kept alive for the process lifetime; do not let GC drop it

def _another_instance_already_running() -> bool:
    """Secondary mutex check — belt-and-suspenders alongside IPC."""
    global _mutex_handle
    if platform.system() != "Windows":
        return False
    import ctypes
    ERROR_ALREADY_EXISTS = 183
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, "ECHO_SingleInstance_Mutex")
    return ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS


if __name__ == "__main__":
    # --- Step 1: Quick mutex check (no Qt required) ---
    # This catches the common second-instance case without any heavy work.
    if _another_instance_already_running():
        logger.warning("Mutex says another instance exists; exiting.")
        sys.exit(0)

    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.environ["PATH"] = app_dir + os.pathsep + os.environ.get("PATH", "")

    # --- Step 2: Load the Whisper model BEFORE any Qt object or module exists ---
    # Creating *any* QApplication / QCoreApplication or loading Qt GUI DLLs
    # before CUDA initializes causes CTranslate2's CUDA init to crash
    # natively (no Python traceback, exit code 1) on Windows.
    # The only safe ordering is: load the model with zero Qt involvement,
    # then import Qt, create QApplication once, and keep it alive.
    config = Config()
    configured_model = config.get("model", "tiny")
    try:
        transcriber = Transcriber(model=configured_model)
        if transcriber.model is None:
            raise TranscriptionError(f"Model '{configured_model}' failed to load.")
    except Exception:
        logger.exception(
            "Configured model '%s' failed to load at startup; falling back to 'tiny'",
            configured_model
        )
        config.set("model", "tiny")
        config.save()
        transcriber = Transcriber(model="tiny")

    # --- Step 3: Now that CUDA is initialized, import Qt and create QApplication ---
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtGui import QFontDatabase
    from core.ipc import send_wake_to_running_instance, IPCServer
    from app import App

    qt_app = QApplication(sys.argv)
    qt_app.setQuitOnLastWindowClosed(False)

    # --- Step 4: IPC single-instance check (needs QApplication for QLocalSocket) ---
    # If another instance is already running, wake it and exit.
    # The mutex above is the fast path; IPC is the reliable path that also
    # sends a wake signal to bring the running instance's overlay forward.
    if send_wake_to_running_instance():
        logger.info("Sent wake signal to running ECHO instance; exiting.")
        sys.exit(0)

    # Register the bundled Inter font (metric-matched to San Francisco,
    # Apple's system font) so every 'Inter' reference in glass.py's QSS
    # actually resolves to it, instead of silently falling back to
    # whatever's installed on the machine (Segoe UI on stock Windows).
    _font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "fonts")
    _font_path = os.path.join(_font_dir, "Inter.ttf")
    if os.path.isfile(_font_path):
        font_id = QFontDatabase.addApplicationFont(_font_path)
        if font_id == -1:
            logger.warning("Failed to register bundled Inter font at %s", _font_path)
    else:
        logger.warning("Bundled Inter font not found at %s", _font_path)

    # Feature 7: Start the IPC server so future launches can reach us
    ipc_server = IPCServer()

    app = App(qt_app, config=config, transcriber=transcriber, ipc_server=ipc_server)
    app.start()

    sys.exit(qt_app.exec_())