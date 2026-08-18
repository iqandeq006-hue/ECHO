"""
Sound cue playback for state transitions.

Looks for exactly four .wav files in assets/sounds/. If a file doesn't
exist yet, playback is silently skipped — no error, no crash. Drop a
correctly-named .wav into assets/sounds/ at any time and it starts
playing immediately on the next matching transition, no restart needed.

Expected filenames (case-sensitive, .wav only):
    pop_record.wav   - idle -> recording
    success.wav      - processing -> transcript / success
    no_speech.wav    - no speech detected
    error.wav        - transcription error
"""

import os
import logging
from PyQt5.QtCore import QUrl

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtMultimedia import QSoundEffect
    _MULTIMEDIA_AVAILABLE = True
except ImportError:
    # QtMultimedia ships with the standard PyQt5 wheel on Windows/macOS/Linux,
    # but some minimal or system-packaged installs omit it. If it's missing,
    # the app should keep running silently rather than crash on import.
    logger.warning("PyQt5.QtMultimedia not available - sound cues disabled")
    _MULTIMEDIA_AVAILABLE = False

SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "sounds")

CUE_FILES = {
    "record": "pop_record.wav",
    "success": "success.wav",
    "no_speech": "no_speech.wav",
    "error": "error.wav",
}


class SoundCues:
    """Loads available sound cues once and plays them on demand."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._effects = {}
        self._load_all()

    def _load_all(self):
        if not _MULTIMEDIA_AVAILABLE:
            return
        for cue_name, filename in CUE_FILES.items():
            path = os.path.join(SOUNDS_DIR, filename)
            if not os.path.isfile(path):
                logger.debug("Sound cue '%s' not found at %s (will stay silent)", cue_name, path)
                continue
            try:
                effect = QSoundEffect()
                effect.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
                effect.setVolume(0.6)
                self._effects[cue_name] = effect
            except Exception:
                logger.exception("Failed to load sound cue '%s'", cue_name)

    def play(self, cue_name: str):
        if not self.enabled:
            return
        effect = self._effects.get(cue_name)
        if effect is None:
            return
        try:
            effect.play()
        except Exception:
            logger.exception("Failed to play sound cue '%s'", cue_name)

    def set_enabled(self, enabled: bool):
        self.enabled = enabled

    def reload(self):
        """Re-scan the sounds folder. Call this if files are dropped in
        while the app is already running and you want them picked up
        without a restart."""
        self._effects.clear()
        self._load_all()
