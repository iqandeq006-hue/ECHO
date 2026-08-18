import pyperclip
import pyautogui
import time
import logging

logger = logging.getLogger(__name__)

CLIPBOARD_VERIFY_TIMEOUT_S = 1.0
CLIPBOARD_VERIFY_INTERVAL_S = 0.02


class Typer:
    def paste(self, text: str) -> bool:
        """Paste text into whatever currently has focus via clipboard + Ctrl+V.

        Always attempts to restore the user's original clipboard contents,
        even if the paste itself fails. Returns True on success, False if
        the paste attempt raised an error.
        """
        try:
            old_clipboard = pyperclip.paste()
        except Exception as e:
            logger.exception("Could not read existing clipboard")
            old_clipboard = ""

        success = True
        try:
            pyperclip.copy(text)
            logger.debug("Typer.paste: copied text length=%d", len(text))

            # Poll until the clipboard actually contains what we just copied
            # instead of sleeping a fixed, possibly-too-short amount of time.
            # Large payloads or a busy system can make clipboard propagation
            # slower than a flat 100ms on some platforms/backends.
            deadline = time.monotonic() + CLIPBOARD_VERIFY_TIMEOUT_S
            while time.monotonic() < deadline:
                try:
                    if pyperclip.paste() == text:
                        break
                except Exception:
                    pass
                time.sleep(CLIPBOARD_VERIFY_INTERVAL_S)
            else:
                logger.warning("Typer.paste: clipboard did not confirm new contents within %.1fs; proceeding anyway", CLIPBOARD_VERIFY_TIMEOUT_S)

            # Attempt paste
            logger.debug("Typer.paste: sending Ctrl+V")
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)
        except Exception as e:
            success = False
            logger.exception("Paste failed")
        finally:
            # Always restore the original clipboard, even on failure
            try:
                pyperclip.copy(old_clipboard)
            except Exception as e:
                logger.exception("Could not restore clipboard")

        if success:
            logger.info("Pasted text (length %d)", len(text))
        return success
