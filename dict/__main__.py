"""Entry point: single-instance lock, wiring, main loop."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import msvcrt

from dict import clipboard, config, logger as logger_mod, sounds
from dict.controller import Controller
from dict.history import History
from dict.hotkey import HotkeyWatcher
from dict.recorder import Recorder
from dict.transcriber import Transcriber
from dict.tray import Tray
from dict.window import HistoryWindow
from dict.utils_logging import get_logger


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


class _SingleInstanceLock:
    """Non-blocking file lock; on failure the process should exit."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file = open(self._path, "a+")
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if self._file is not None:
                self._file.close()
                self._file = None
            return False

    def release(self) -> None:
        if self._file is None:
            return
        try:
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._file.close()
        self._file = None


def main() -> int:
    _configure_logging()
    log = get_logger("dict.main")

    lock = _SingleInstanceLock(config.LOCK_PATH)
    if not lock.acquire():
        print("Dict already running")
        return 0

    try:
        # Build the object graph bottom-up. Controller needs window (which
        # wants on_toggle=controller.on_hotkey) and tray (created after
        # controller). Break both cycles with lazy-resolving holders.
        history = History(maxlen=config.HISTORY_MAX)
        recorder = Recorder()
        transcriber = Transcriber()

        controller_holder: dict[str, "Controller"] = {}
        tray_holder: dict[str, "Tray"] = {}

        def _on_button_toggle() -> None:
            c = controller_holder.get("c")
            if c is not None:
                c.on_hotkey()

        window = HistoryWindow(
            history=history,
            on_copy=clipboard.set_text,
            on_toggle=_on_button_toggle,
        )

        class _TrayFacade:
            def set_state(self, state: str) -> None:
                t = tray_holder.get("tray")
                if t is not None:
                    t.set_state(state)

            def notify(self, title: str, message: str) -> None:
                t = tray_holder.get("tray")
                if t is not None:
                    t.notify(title, message)

        controller = Controller(
            recorder=recorder,
            transcriber=transcriber,
            tray=_TrayFacade(),
            window=window,
            history=history,
            sounds=sounds,
            clipboard_set=clipboard.set_text,
            logger_append=logger_mod.append,
            auto_show_seconds=config.AUTO_SHOW_SECONDS,
        )
        controller_holder["c"] = controller

        hotkey = HotkeyWatcher(config.HOTKEY, on_trigger=controller.on_hotkey)

        def on_left_click() -> None:
            window.toggle()

        def on_quit() -> None:
            hotkey.stop()
            window.stop()
            lock.release()

        tray = Tray(on_left_click=on_left_click, on_quit=on_quit)
        tray_holder["tray"] = tray

        # Warm up the model up front so the first hotkey press is responsive.
        log.info("warming up whisper model (%s)...", config.MODEL_SIZE)
        try:
            transcriber.ensure_loaded()
        except Exception:
            log.exception("initial model load failed - hotkey remains active; each attempt will retry")

        window.start()
        hotkey.start()
        log.info("dict ready; press %s to record", config.HOTKEY)
        tray.run()  # blocks until on_quit
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
