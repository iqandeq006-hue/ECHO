import time
import keyboard
import logging
import threading

logger = logging.getLogger(__name__)


class HotkeyListener:
    """Listens for the global hotkey and reports press/release events.

    IMPORTANT: This class no longer spawns its own background thread for
    on_release. The `keyboard` library already invokes `_handle` from its
    own internal (non-Qt) listener thread. Previously we additionally
    wrapped on_release in a raw `threading.Thread`, which meant heavy work
    (transcription) ran on a thread Qt knew nothing about. Qt signals
    emitted from that thread could not be safely queued to the GUI thread,
    which produced the "Cannot create children for a parent that is in a
    different thread" / "Cannot queue arguments of type 'QTextCursor'"
    errors.

    on_release is now expected to be a *fast, non-blocking* callable (see
    App.stop_and_transcribe), which simply hands off to a proper QThread.
    """

    def __init__(self, hotkey: str, on_press, on_release):
        # Convert pynput format "<ctrl>+<alt>+s" → "ctrl+alt+s"
        self.hotkey = hotkey.replace("<", "").replace(">", "")
        self.on_press = on_press
        self.on_release = on_release
        self._held = False
        self._held_lock = threading.Lock()
        self._suspended = False
        self._last_call_time = 0.0
        self._last_toggle_time = 0.0

    def start(self):
        keyboard.add_hotkey(
            self.hotkey,
            self._handle,
            suppress=True   # prevents hotkey from reaching the focused app
        )
        logger.info("Hotkey listening for: %s", self.hotkey)

    def update_hotkey(self, new_hotkey: str):
        """Swap the active hotkey binding without restarting the app.
        Removes the old binding first so two hotkeys never overlap."""
        new_hotkey = new_hotkey.replace("<", "").replace(">", "")
        try:
            keyboard.remove_hotkey(self.hotkey)
        except (KeyError, ValueError):
            logger.debug("Old hotkey '%s' was not registered; nothing to remove", self.hotkey)
        self.hotkey = new_hotkey
        with self._held_lock:
            self._held = False
            self._last_call_time = 0.0
            self._last_toggle_time = 0.0
        keyboard.add_hotkey(
            self.hotkey,
            self._handle,
            suppress=True
        )
        logger.info("Hotkey updated, now listening for: %s", self.hotkey)

    def suspend(self):
        """Temporarily ignore hotkey triggers (e.g. during rebinding)."""
        self._suspended = True
        logger.debug("Hotkey listener suspended")

    def resume(self):
        """Re-enable hotkey triggers after suspension."""
        self._suspended = False
        with self._held_lock:
            self._held = False
            self._last_call_time = 0.0
            self._last_toggle_time = 0.0
        logger.debug("Hotkey listener resumed")

    def _handle(self):
        if self._suspended:
            return

        now = time.time()
        with self._held_lock:
            time_since_last_call = now - self._last_call_time
            time_since_last_toggle = now - self._last_toggle_time
            self._last_call_time = now

            # OS Key-repeat suppression: key repeat fires events every ~30-50ms.
            # Any call within 200ms of the previous call is a key-repeat event.
            if time_since_last_call < 0.2 or time_since_last_toggle < 0.3:
                return

            self._last_toggle_time = now
            is_press = not self._held
            self._held = not self._held

        if is_press:
            # Call on_press synchronously so it can capture the current
            # foreground window / focused control before any thread context
            # changes happen. on_press should be fast (it starts the recorder
            # which itself spawns a thread).
            try:
                self.on_press()
            except Exception:
                logger.exception("Error in on_press handler")
        else:
            try:
                # on_release (App.stop_and_transcribe) must be fast/non-blocking.
                # It kicks off a QThread worker internally and returns immediately.
                self.on_release()
            except Exception:
                logger.exception("Error in on_release handler")

    def stop(self):
        keyboard.remove_all_hotkeys()
