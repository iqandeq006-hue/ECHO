import sounddevice as sd
import numpy as np
import wave
import threading
import os
import logging

logger = logging.getLogger(__name__)

# Use AppData directory for the temp recording (user-writable location).
# The install folder (e.g. C:\Program Files\ECHO) is NOT writable by a
# normal running process even when the installer itself ran as admin —
# writing here used to throw PermissionError once ECHO was installed via
# Inno Setup, since it correctly defaults to Program Files.
_TEMP_DIR = os.path.join(os.getenv('APPDATA'), 'ECHO', 'temp')
os.makedirs(_TEMP_DIR, exist_ok=True)
AUDIO_PATH = os.path.join(_TEMP_DIR, "audio.wav")
SAMPLE_RATE = 16000  # Whisper expects 16kHz


class Recorder:
    def __init__(self):
        self.recording = False
        self.frames = []
        self._thread = None

    def start(self):
        self.frames = []
        self.recording = True
        self._thread = threading.Thread(target=self._record, daemon=True)
        self._thread.start()
        logger.info("Recorder: recording started")

    def _record(self):
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16') as stream:
                while self.recording:
                    try:
                        data, _ = stream.read(1024)
                        self.frames.append(data.copy())
                    except Exception:
                        logger.exception("Error reading from input stream")
                        # Stop recording on stream read failure
                        self.recording = False
                        break
        except Exception:
            logger.exception("Failed to open audio input stream. Check microphone and permissions.")
            self.recording = False

    def stop(self):
        self.recording = False
        if self._thread:
            self._thread.join()
        else:
            # stop() was called before start() ever ran (e.g. a very rapid
            # hotkey bounce). There is no recording thread, so make sure we
            # don't fall through to has_audio() with stale frames left over
            # from a previous, unrelated recording.
            self.frames = []

        # Fix 2: Guard against empty frames (hotkey pressed and released instantly)
        if not self.frames:
            logger.warning("No audio captured, skipping save.")
            return

        self._save()
        logger.info("Recorder: recording stopped")

    def _save(self):
        audio_data = np.concatenate(self.frames, axis=0)
        os.makedirs(os.path.dirname(AUDIO_PATH), exist_ok=True)
        with wave.open(AUDIO_PATH, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16 = 2 bytes
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(audio_data.tobytes())

    def has_audio(self):
        """Check if audio was actually captured"""
        return len(self.frames) > 0

    def get_audio_path(self):
        return AUDIO_PATH
