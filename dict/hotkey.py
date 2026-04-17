"""Global hotkey listener via pynput."""
from __future__ import annotations

from typing import Callable, Optional

from pynput import keyboard

from dict.utils_logging import get_logger

log = get_logger(__name__)


class HotkeyWatcher:
    def __init__(self, combo: str, on_trigger: Callable[[], None]) -> None:
        self._combo = combo
        self._on_trigger = on_trigger
        self._listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys({self._combo: self._on_fire})
        self._listener.start()
        log.info("hotkey %s registered", self._combo)

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None

    def _on_fire(self) -> None:
        try:
            self._on_trigger()
        except Exception:
            log.exception("hotkey handler raised")
