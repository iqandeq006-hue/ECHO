"""Windows light/dark theme detection.

Windows stores the user's chosen "app mode" (Settings > Personalization >
Colors > Choose your default app mode) in the registry, separately from the
"system" theme that colors the taskbar/Start menu (SystemUsesLightTheme).
Apps are expected to read AppsUseLightTheme -- not SystemUsesLightTheme --
for their own UI/icon decisions, which is what this module does.
"""
import logging
import winreg

logger = logging.getLogger(__name__)

_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_VALUE_NAME = "AppsUseLightTheme"


def is_light_theme() -> bool:
    """Return True if Windows system/taskbar is set to Light mode, False for Dark.

    Checks SystemUsesLightTheme first (which colors the taskbar where the tray icon
    resides), falling back to AppsUseLightTheme. Defaults to False (dark).
    """
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY_PATH) as key:
            for val_name in ("SystemUsesLightTheme", "AppsUseLightTheme"):
                try:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    return bool(val)
                except (FileNotFoundError, OSError):
                    continue
    except (FileNotFoundError, OSError):
        logger.debug(
            "Themes\\Personalize not found in registry; defaulting to dark theme"
        )
    return False
