import json
import os

# Use AppData directory for config (user-writable location)
CONFIG_DIR = os.path.join(os.getenv('APPDATA'), 'ECHO')
os.makedirs(CONFIG_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "hotkey": "ctrl+shift+s",
    "model": "tiny",
    "sound_enabled": True
}


class Config:
    def __init__(self):
        if not os.path.exists(CONFIG_PATH):
            self._data = DEFAULTS.copy()
            self.save()
        else:
            with open(CONFIG_PATH, 'r') as f:
                self._data = json.load(f)
            # Backfill any keys missing from an older config.json (e.g. a
            # key added in a later version) so they get persisted instead
            # of silently relying on a fallback default forever.
            missing = {k: v for k, v in DEFAULTS.items() if k not in self._data}
            if missing:
                self._data.update(missing)
                self.save()

    def get(self, key, fallback=None):
        return self._data.get(key, fallback)

    def set(self, key, value):
        self._data[key] = value

    def save(self):
        with open(CONFIG_PATH, 'w') as f:
            json.dump(self._data, f, indent=2)