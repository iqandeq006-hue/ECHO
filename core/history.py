import json
import os
import threading
from datetime import datetime

# Use AppData directory for history (user-writable location) — same reason
# as recorder.py's AUDIO_PATH: Program Files is not writable by a normal
# running process, even when the installer itself ran as admin.
_STORAGE_DIR = os.path.join(os.getenv('APPDATA'), 'ECHO', 'storage')
HISTORY_PATH = os.path.join(_STORAGE_DIR, "history.json")


class History:
    def __init__(self):
        self._lock = threading.Lock()
        os.makedirs(_STORAGE_DIR, exist_ok=True)
        if not os.path.exists(HISTORY_PATH):
            self._write([])

    def add(self, text: str):
        with self._lock:
            entries = self.load()
            entries.insert(0, {
                "text": text,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            entries = entries[:100]  # Keep last 100 entries only
            self._write(entries)

    def load(self):
        try:
            with open(HISTORY_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return []

    def clear(self):
        with self._lock:
            self._write([])

    def _write(self, data):
        with open(HISTORY_PATH, 'w') as f:
            json.dump(data, f, indent=2)
