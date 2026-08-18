import ctypes
import platform
import logging
from config.logging_config import setup_logging
from enum import Enum, auto

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from config.config import Config
from core.hotkey import HotkeyListener
from core.recorder import Recorder
from core.transcriber import Transcriber, TranscriptionError
from core.typer import Typer
from core.history import History
from core.sound_cues import SoundCues
from ui.tray import TrayIcon
from ui.overlay import OverlayIndicator
from ui.settings import SettingsWindow
from ui.fallback import PasteFallbackWindow

setup_logging()
logger = logging.getLogger(__name__)

user32 = None
SW_RESTORE = 9
if platform.system() == "Windows":
    try:
        user32 = ctypes.windll.user32
    except Exception:
        logger.exception("Failed to access user32 ctypes on Windows")

class AppState(Enum):
    BOOT = auto()
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
    NO_SPEECH = auto()
    FAILURE = auto()

ALLOWED_TRANSITIONS = {
    AppState.BOOT: {AppState.IDLE},
    AppState.IDLE: {AppState.RECORDING},
    AppState.RECORDING: {AppState.PROCESSING, AppState.NO_SPEECH},
    AppState.PROCESSING: {AppState.IDLE, AppState.NO_SPEECH, AppState.FAILURE},
    AppState.NO_SPEECH: {AppState.IDLE},
    AppState.FAILURE: {AppState.IDLE}
}


# ---------------------------------------------------------------------------
# Fix 6: GUITHREADINFO — cross-thread focus detection without AttachThreadInput
# ---------------------------------------------------------------------------
if platform.system() == "Windows":
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("hwndActive", ctypes.c_void_p),
            ("hwndFocus", ctypes.c_void_p),
            ("hwndCapture", ctypes.c_void_p),
            ("hwndMenuOwner", ctypes.c_void_p),
            ("hwndMoveSize", ctypes.c_void_p),
            ("hwndCaret", ctypes.c_void_p),
            ("rcCaret", ctypes.c_long * 4),
        ]

    def get_focused_control() -> int:
        """Return the HWND of the currently focused control in the
        foreground window, using GetGUIThreadInfo instead of the
        fragile AttachThreadInput + GetFocus combination.

        Returns 0 on any failure.
        """
        try:
            fg = user32.GetForegroundWindow()
            if not fg:
                return 0
            pid = ctypes.c_ulong()
            tid = user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            if not tid:
                return 0
            info = GUITHREADINFO()
            info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if not user32.GetGUIThreadInfo(tid, ctypes.byref(info)):
                return 0
            return int(info.hwndFocus) if info.hwndFocus else 0
        except Exception:
            logger.exception("get_focused_control failed")
            return 0
else:
    def get_focused_control() -> int:
        return 0


class TranscribeWorker(QObject):
    """The 'Listening Helper'.

    Runs on a real QThread. Its ONLY job is: read the audio file and run
    Whisper on it. It NEVER touches any widget, QTextDocument, or
    QTextCursor directly — it only emits a plain string back to the GUI
    thread via a signal. This is what makes the cross-thread hand-off safe.

    finished emits (text, outcome) where outcome is one of:
        "ok"        - transcription succeeded, text is non-empty
        "no_speech" - model ran fine but heard nothing usable
        "error"     - transcription genuinely failed (model/exception)
    """
    finished = pyqtSignal(str, str)

    def __init__(self, transcriber: Transcriber, audio_path: str):
        super().__init__()
        self.transcriber = transcriber
        self.audio_path = audio_path

    def run(self):
        try:
            text = self.transcriber.transcribe(self.audio_path)
        except TranscriptionError:
            logger.exception("TranscribeWorker: transcription genuinely failed")
            self.finished.emit("", "error")
            return
        except Exception:
            logger.exception("TranscribeWorker: unexpected exception during transcription")
            self.finished.emit("", "error")
            return

        if not text or len(text.strip()) < 3:
            self.finished.emit("", "no_speech")
        else:
            self.finished.emit(text, "ok")


class _ModelLoadWorker(QObject):
    """Loads a new Whisper model off the GUI thread (model load can take
    several seconds) and emits the resulting Transcriber once ready.
    On failure (e.g. an unbundled model name in a frozen build), emits
    finished(None, error_message) instead of letting the exception vanish
    silently inside the background thread."""
    finished = pyqtSignal(object, object)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            transcriber = Transcriber(model=self.model_name)
            if transcriber.model is None:
                raise TranscriptionError(f"Model '{self.model_name}' failed to load.")
            self.finished.emit(transcriber, None)
        except Exception as exc:
            logger.exception("Background model load failed for '%s'", self.model_name)
            self.finished.emit(None, str(exc))


class App(QObject):
    signal_update_state = pyqtSignal(object)

    def __init__(self, qt_app, config=None, transcriber=None, ipc_server=None):
        super().__init__()
        self.qt_app = qt_app

        self.config = config or Config()
        self.history = History()
        self.recorder = Recorder()

        if transcriber is not None:
            # Pre-loaded in main.py, before QApplication existed, to avoid
            # a native CUDA-context-vs-Qt-init crash (see main.py).
            self.transcriber = transcriber
        else:
            configured_model = self.config.get("model", "tiny")
            try:
                self.transcriber = Transcriber(model=configured_model)
            except Exception:
                logger.exception(
                    "Configured model '%s' failed to load at startup; falling back to 'tiny'",
                    configured_model
                )
                self.config.set("model", "tiny")
                self.config.save()
                self.transcriber = Transcriber(model="tiny")

        self.typer = Typer()
        self.sound_cues = SoundCues(enabled=self.config.get("sound_enabled", True))

        # Feature 6: Start in BOOT state
        self.state = AppState.BOOT
        self.is_rebinding_hotkey = False

        # Keep references alive until each thread fully cleans itself up.
        # Using a list means assigning a new pair never drops the old one early.
        self._active_threads: list = []

        self.overlay = OverlayIndicator(sound_cues=self.sound_cues)
        self.settings_window = SettingsWindow(
            self.config, self.history,
            on_hotkey_changed=self._on_hotkey_changed,
            on_model_changed=self._on_model_changed,
            on_sound_toggled=self._on_sound_toggled,
            on_hotkey_capture_start=self.suspend_hotkey,
            on_hotkey_capture_end=self.resume_hotkey
        )
        self.fallback_window = PasteFallbackWindow()
        self.tray = TrayIcon(
            on_settings=self.open_settings,
            on_history=self.open_history,
            on_quit=self.quit
        )

        self.hotkey_listener = HotkeyListener(
            hotkey=self.config.get("hotkey", "ctrl+shift+s"),
            on_press=self.start_recording,
            on_release=self.stop_and_transcribe
        )

        self.signal_update_state.connect(self.overlay.update_state)
        self.overlay.signal_request_idle.connect(self._on_overlay_idle_request)

        # Feature 7: Wire IPC server for smart instance management
        self._ipc_server = ipc_server
        if ipc_server:
            ipc_server.wake_requested.connect(self._on_wake_from_second_instance)

    def transition(self, new_state):
        if new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise RuntimeError(f"Invalid transition: {self.state} -> {new_state}")

        self.state = new_state
        self.signal_update_state.emit(new_state)

    def start(self):
        # Feature 6: Show boot animation, then transition to IDLE
        self.signal_update_state.emit(AppState.BOOT)
        self.overlay.show()
        self.tray.show()
        self.hotkey_listener.start()
        logger.info("ECHO running in background...")
        # Transition BOOT → IDLE after a brief delay for the boot animation
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1200, self._finish_boot)

    def _finish_boot(self):
        """Complete boot sequence: transition BOOT → IDLE."""
        if self.state == AppState.BOOT:
            self.transition(AppState.IDLE)

    def _on_wake_from_second_instance(self):
        """Feature 7: Another ECHO launch was attempted; show the glow."""
        logger.info("Wake signal received from second instance")
        self.overlay.trigger_boot_glow()

    def start_recording(self):
        if self.state != AppState.IDLE:
            return
        if self.is_rebinding_hotkey:
            return

        self.transition(AppState.RECORDING)
        self.recorder.start()

    def stop_and_transcribe(self):
        """Called from the hotkey-listener thread. Must be FAST and
        non-blocking: it stops the recorder (quick), then hands off the
        actual transcription work to a QThread and returns immediately.
        All the heavy lifting + the eventual write/overlay decision happens
        in _on_transcription_finished, which runs on the GUI thread because
        QThread's `finished` signal is queued back to whatever thread the
        QObject (self) lives on — the GUI thread.
        """
        if self.state != AppState.RECORDING:
            return

        self.recorder.stop()

        if not self.recorder.has_audio():
            self.transition(AppState.PROCESSING)
            self.overlay.signal_no_speech()
            self.transition(AppState.NO_SPEECH)
            # NO immediate transition(IDLE) — overlay timer drives it
            return

        self.transition(AppState.PROCESSING)

        audio_path = self.recorder.get_audio_path()

        # --- Spin up the Listening Helper on a real QThread ---
        thread = QThread()   # no parent — avoids cross-thread QObject warning
        worker = TranscribeWorker(self.transcriber, audio_path)
        worker.moveToThread(thread)

        # Hold strong Python references so GC cannot destroy them before the
        # thread finishes.  The pair is removed from the list once the thread
        # has fully stopped (thread.finished fires after the event loop exits).
        pair = [thread, worker]
        self._active_threads.append(pair)

        def _remove_pair():
            try:
                self._active_threads.remove(pair)
            except ValueError:
                pass

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_transcription_finished)
        # Cleanup once done
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_remove_pair)   # drop the strong ref last

        thread.start()

    def _on_transcription_finished(self, text: str, outcome: str):
        """Runs on the GUI thread. Outcome is 'ok', 'no_speech', or 'error'.

        For failures: App transitions to FAILURE/NO_SPEECH, overlay shows
        the visual and drives the eventual IDLE transition via
        signal_request_idle.

        For success with editable field: paste + immediate transition(IDLE).
        For success without editable field: show transcript, overlay drives
        the IDLE transition after 8s timeout.
        """
        if outcome == "error":
            self.overlay.signal_error()
            self.transition(AppState.FAILURE)
            # NO immediate transition(IDLE) — overlay timer drives it
            return

        if outcome == "no_speech":
            self.overlay.signal_no_speech()
            self.transition(AppState.NO_SPEECH)
            # NO immediate transition(IDLE) — overlay timer drives it
            return

        # -- Success path: check focus LIVE, not from a stale snapshot --
        self.history.add(text)

        focused_hwnd = get_focused_control()
        is_edit = self._is_edit_control_focused(focused_hwnd)
        logger.debug("_on_transcription_finished: focused_hwnd=%s is_edit=%s",
                     hex(focused_hwnd) if focused_hwnd else "0x0", is_edit)

        if is_edit:
            # Branch A: editable field — paste and go to IDLE immediately
            success = self.typer.paste(text)
            if not success:
                try:
                    self.overlay.show_transcript(text, "Speech may have noise \u2014 please try again")
                except Exception:
                    logger.exception("Failed to show transcript overlay after paste failure")
                    try:
                        self.fallback_window.show_transcript(text)
                    except Exception:
                        logger.exception("Fallback paste window also failed")
                # Paste failed — show transcript, let overlay drive IDLE
                self.overlay.signal_success()
                return
            # Paste succeeded — let water animation finish, then immediate IDLE
            self.overlay.signal_success(pasted=True)
            self.transition(AppState.IDLE)
        else:
            # Branch B: no editable field — show transcript card
            try:
                self.overlay.show_transcript(text)
            except Exception:
                logger.exception("Failed to show transcript overlay; falling back to paste window")
                try:
                    self.fallback_window.show_transcript(text)
                except Exception:
                    logger.exception("Fallback paste window also failed")
            self.overlay.signal_success()
            # NO immediate transition(IDLE) — overlay's 8s timer drives it

    def _is_edit_control_focused(self, hwnd: int) -> bool:
        """Return True if the given HWND belongs to an editable control.

        `hwnd` should come from get_focused_control(), which already
        resolved the focused child via GetGUIThreadInfo. This method
        just inspects the class name.
        """
        if platform.system() != "Windows" or not user32 or not hwnd:
            return False
        try:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            cls = (buf.value or "").lower()
            logger.debug("_is_edit_control_focused: hwnd=%s class=%s", hex(hwnd), cls)
            EDIT_CLASSES = ("edit", "rich", "textbox", "chrome_renderwidgethosthwnd", "chrome_widgetwin")
            return any(name in cls for name in EDIT_CLASSES)
        except Exception:
            logger.exception("_is_edit_control_focused: exception during detection")
            return False

    def _on_overlay_idle_request(self):
        """Called when the overlay has finished its async visual cycle
        (transcript timeout, no-speech/error revert, paste confirm) and
        wants the app to return to IDLE."""
        if self.state != AppState.IDLE and self.state in (AppState.NO_SPEECH, AppState.FAILURE, AppState.PROCESSING):
            self.transition(AppState.IDLE)

    def suspend_hotkey(self):
        """Suspend the global hotkey listener (e.g. during hotkey rebinding)."""
        self.is_rebinding_hotkey = True
        self.hotkey_listener.suspend()

    def resume_hotkey(self):
        """Resume the global hotkey listener after rebinding."""
        self.is_rebinding_hotkey = False
        self.hotkey_listener.resume()

    def open_settings(self):
        self.settings_window.show()

    def open_history(self):
        self.settings_window.show()
        self.settings_window.focus_history()

    def _on_hotkey_changed(self, new_hotkey: str):
        self.hotkey_listener.update_hotkey(new_hotkey)

    def _on_sound_toggled(self, enabled: bool):
        self.sound_cues.set_enabled(enabled)

    def _on_model_changed(self, new_model: str):
        """Reload the Whisper model on a background thread so the GUI
        never blocks (model load can take seconds), then swap it into
        self.transcriber once ready. If a transcription is already in
        flight, it keeps using whichever Transcriber instance it was
        given at thread-start time, so this is safe to do mid-recording."""
        logger.info("Loading new Whisper model in background: %s", new_model)

        thread = QThread()
        worker = _ModelLoadWorker(new_model)
        worker.moveToThread(thread)

        pair = [thread, worker]
        self._active_threads.append(pair)

        def _remove_pair():
            try:
                self._active_threads.remove(pair)
            except ValueError:
                pass

        def _on_loaded(transcriber, error):
            if error:
                logger.error("Keeping previous model; switch to '%s' failed: %s", new_model, error)
                try:
                    self.tray.notify("ECHO", f"Couldn't switch to '{new_model}': {error}")
                except Exception:
                    logger.exception("Failed to show model-switch-failure tray notification")
                return
            self.transcriber = transcriber
            logger.info("Whisper model switched to: %s", new_model)

        thread.started.connect(worker.run)
        worker.finished.connect(_on_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_remove_pair)

        thread.start()

    def quit(self):
        self.hotkey_listener.stop()
        self.qt_app.quit()