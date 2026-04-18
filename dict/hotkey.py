"""Global hotkey listener.

Uses the `keyboard` library, which installs a low-level Windows keyboard
hook (SetWindowsHookEx WH_KEYBOARD_LL). This is more robust than
pynput's GlobalHotKeys, which in practice stops firing after the first
trigger on Windows 11.

Hotkey format is the `keyboard` library syntax: "f9", "ctrl+shift+v",
"ctrl+alt+space". We translate our pynput-style config (`<f9>`,
`<ctrl>+<shift>+v`) transparently.
"""
from __future__ import annotations

import re
from typing import Callable

import keyboard as kb  # type: ignore[import]

from dict.utils_logging import get_logger

log = get_logger(__name__)


def _to_keyboard_lib_syntax(combo: str) -> str:
    """Convert pynput-style `<ctrl>+<shift>+v` to keyboard-style `ctrl+shift+v`."""
    # keyboard lib uses plain names without angle brackets
    return re.sub(r"[<>]", "", combo).lower()


class HotkeyWatcher:
    def __init__(self, combo: str, on_trigger: Callable[[], None]) -> None:
        self._combo_cfg = combo
        self._combo = _to_keyboard_lib_syntax(combo)
        self._on_trigger = on_trigger
        self._handle: object | None = None

    def start(self) -> None:
        if self._handle is not None:
            return
        try:
            # suppress=False: do not swallow the key; trigger_on_release=False
            # so F9 press is instantaneous.
            self._handle = kb.add_hotkey(
                self._combo,
                self._on_fire,
                suppress=False,
                trigger_on_release=False,
            )
            log.info("hotkey %s registered (keyboard lib)", self._combo)
        except Exception:
            log.exception("failed to register hotkey %s", self._combo)

    def stop(self) -> None:
        if self._handle is None:
            return
        try:
            kb.remove_hotkey(self._handle)
        except Exception:
            log.exception("failed to remove hotkey")
        self._handle = None

    def _on_fire(self) -> None:
        log.info("hotkey fired: %s", self._combo)
        try:
            self._on_trigger()
        except Exception:
            log.exception("hotkey handler raised")
