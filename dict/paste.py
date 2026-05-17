"""Auto-paste / typewriter into the focused field. Cross-platform via pynput.

On macOS: paste uses Cmd+V (instead of Ctrl+V on Windows/Linux).
"""
from __future__ import annotations

import sys
import threading
import time as _time

from dict import clipboard
from dict.utils_logging import get_logger

log = get_logger(__name__)

_RESTORE_DELAY_S = 0.2


def _paste_key_combo() -> str:
    """Return the OS-correct paste combo for pynput."""
    return "cmd+v" if sys.platform == "darwin" else "ctrl+v"


def _send_combo(combo: str) -> None:
    """Send a "ctrl+v" / "cmd+shift+v" combo via pynput."""
    from pynput.keyboard import Controller, Key
    SPECIAL = {"ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt,
               "cmd": Key.cmd, "super": Key.cmd, "win": Key.cmd,
               "enter": Key.enter, "space": Key.space, "tab": Key.tab,
               "esc": Key.esc, "pause": Key.pause}
    ctl = Controller()
    parts = [p.strip().lower() for p in combo.split("+")]
    keys = [SPECIAL.get(p, p) for p in parts]
    # Press in order, release in reverse
    for k in keys:
        ctl.press(k)
    for k in reversed(keys):
        ctl.release(k)


def _release_combo(combo: str) -> None:
    """Best-effort release of all modifier keys in `combo`.

    Used after a hotkey fires, before sending our own keystrokes, so the
    user's still-down modifiers don't taint our SendInput sequence."""
    if not combo:
        return
    try:
        from pynput.keyboard import Controller, Key
        SPECIAL = {"ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt,
                   "cmd": Key.cmd, "super": Key.cmd, "win": Key.cmd,
                   "enter": Key.enter, "space": Key.space, "tab": Key.tab,
                   "esc": Key.esc, "pause": Key.pause}
        ctl = Controller()
        for p in combo.split("+"):
            k = SPECIAL.get(p.strip().lower(), p.strip().lower())
            try:
                ctl.release(k)
            except Exception:
                pass
    except Exception:
        log.warning("release of hotkey %r failed (continuing)", combo)


def paste_text(
    text: str,
    current_hotkey: str | None = None,
    restore_delay_s: float = _RESTORE_DELAY_S,
) -> bool:
    """Save clipboard -> set text -> send paste combo -> restore in 200ms."""
    saved = clipboard.get_text()
    if not clipboard.set_text(text):
        return False
    _release_combo(current_hotkey or "")
    try:
        _send_combo(_paste_key_combo())
    except Exception:
        log.warning("paste_text: send paste combo failed; text left in clipboard")
        return False
    def _restore() -> None:
        clipboard.set_text(saved)
    timer = threading.Timer(restore_delay_s, _restore)
    timer.daemon = True
    timer.start()
    return True


def type_text(
    text: str,
    current_hotkey: str | None = None,
    delay_s: float = 0.018,
) -> bool:
    """Type `text` character-by-character via pynput.

    Doesn't touch the clipboard. Slower than Ctrl+V but gives a typewriter
    feel for live streaming chunks. Works for Cyrillic + emoji (Unicode)."""
    if not text:
        return True
    _release_combo(current_hotkey or "")
    try:
        from pynput.keyboard import Controller
        ctl = Controller()
        for ch in text:
            ctl.type(ch)
            if delay_s > 0:
                _time.sleep(delay_s)
        return True
    except Exception:
        log.warning("type_text: failed for %d chars", len(text))
        return False
