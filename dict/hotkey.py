"""Global hotkey listener. Cross-platform via pynput.

On macOS the user must grant Accessibility permission to the Python
interpreter (or to the bundled .app) in System Settings -> Privacy &
Security -> Accessibility, otherwise no key events are received.
"""
from __future__ import annotations

from typing import Callable

from dict.utils_logging import get_logger

log = get_logger(__name__)


def is_valid_combo(combo: str) -> bool:
    """Cheap parse-only validity check for a hotkey combo string."""
    if not combo or not combo.strip():
        return False
    # pynput accepts "<f9>", "<ctrl>+v", "pause", etc. Allow simple keys
    # and modifier combos with +.
    parts = [p.strip() for p in combo.split("+")]
    return all(parts) and all(len(p) > 0 for p in parts)


def normalize_combo(combo: str) -> str:
    """Latinise + lowercase a combo string. Maps Cyrillic chars that share
    a QWERTY position to their Latin equivalents (so Russian-layout users
    can press the same physical keys)."""
    cyr_to_lat = str.maketrans(
        "йцукенгшщзхъфывапролджэячсмитьбю.",
        "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
    )
    parts = []
    for p in combo.split("+"):
        p = p.strip().lower().translate(cyr_to_lat)
        parts.append(p)
    return "+".join(parts)


def _combo_to_pynput(combo: str) -> str:
    """Translate our combo format into pynput's GlobalHotKeys format.

    Examples:
      "f9"             -> "<f9>"
      "ctrl+shift+v"   -> "<ctrl>+<shift>+v"
      "pause"          -> "<pause>"
      "ctrl+alt+d"     -> "<ctrl>+<alt>+d"
    """
    SPECIAL = {
        "ctrl", "alt", "shift", "cmd", "super", "win",
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8",
        "f9", "f10", "f11", "f12",
        "pause", "scroll_lock", "esc", "tab", "space",
        "enter", "backspace", "delete", "insert", "home",
        "end", "page_up", "page_down", "up", "down", "left", "right",
    }
    parts = []
    for p in combo.split("+"):
        p = p.strip().lower()
        if p in SPECIAL:
            parts.append(f"<{p}>")
        else:
            parts.append(p)
    return "+".join(parts)


class HotkeyWatcher:
    """Listens for a single global hotkey combo and invokes a callback on
    each press. Cross-platform via pynput."""

    def __init__(self, combo: str, on_trigger: Callable[[], None]) -> None:
        self._combo_raw = combo
        self._on_trigger = on_trigger
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard as _kb
        pynput_combo = _combo_to_pynput(self._combo_raw)
        try:
            self._listener = _kb.GlobalHotKeys({pynput_combo: self._on_fire})
            self._listener.start()
            log.info("hotkey %s registered (pynput, as %r)",
                     self._combo_raw, pynput_combo)
        except Exception:
            log.exception("hotkey registration failed for %r", self._combo_raw)

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                log.exception("hotkey listener stop failed")
            self._listener = None

    def _on_fire(self) -> None:
        log.info("hotkey fired: %s", self._combo_raw)
        try:
            self._on_trigger()
        except Exception:
            log.exception("hotkey handler raised")
