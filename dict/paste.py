"""Auto-paste recognized text into the focused text field.

Saves the clipboard, copies our text, sends Ctrl+V, and restores the
clipboard ~200ms later. The active app reads the clipboard asynchronously
on Ctrl+V, so restoring synchronously would race with the paste.

If the user's hotkey shares modifier keys with Ctrl+V (e.g.
ctrl+shift+v), we issue a best-effort keyboard.release(<hotkey>) before
sending Ctrl+V — otherwise the still-pressed modifiers cause SendInput
to misbehave.
"""
from __future__ import annotations

import threading

import keyboard
import pyperclip

from dict.utils_logging import get_logger

log = get_logger(__name__)

_RESTORE_DELAY_S = 0.2


def paste_text(
    text: str,
    current_hotkey: str | None = None,
    restore_delay_s: float = _RESTORE_DELAY_S,
) -> bool:
    """Place `text` in the clipboard, send Ctrl+V, restore old clipboard.

    Returns True if Ctrl+V was sent successfully. Returns False if the
    keyboard.send failed (text remains in the clipboard so the user can
    paste manually; the restore timer is NOT scheduled in that case).
    """
    saved = ""
    try:
        saved = pyperclip.paste() or ""
    except Exception:
        log.exception("paste_text: read of clipboard failed; will not restore")
        saved = ""

    try:
        pyperclip.copy(text)
    except Exception:
        log.exception("paste_text: copy of new text failed")
        return False

    if current_hotkey:
        try:
            keyboard.release(current_hotkey)
        except Exception:
            log.warning("paste_text: keyboard.release(%r) failed (continuing)",
                        current_hotkey)

    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.warning("paste_text: keyboard.send('ctrl+v') failed; text left in clipboard")
        return False

    def _restore() -> None:
        try:
            pyperclip.copy(saved)
        except Exception:
            log.warning("paste_text: clipboard restore failed (swallowed)")

    threading.Timer(restore_delay_s, _restore).start()
    return True
