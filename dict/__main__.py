"""Entry point: single-instance lock, wiring, main loop."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import msvcrt

from dict import clipboard, config, logger as logger_mod, settings as settings_mod, sounds
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


def _pretty_hotkey(combo: str) -> str:
    """'ctrl+shift+v' -> 'Ctrl+Shift+V' for UI display."""
    parts = [p.strip().capitalize() if len(p.strip()) > 1 else p.strip().upper()
             for p in combo.split("+")]
    return "+".join(parts)


def main() -> int:
    _configure_logging()
    log = get_logger("dict.main")

    lock = _SingleInstanceLock(config.LOCK_PATH)
    if not lock.acquire():
        print("Dict already running")
        return 0

    try:
        user_settings = settings_mod.load()
        effective_hotkey = user_settings.hotkey or config.HOTKEY
        effective_model = user_settings.model_size or config.MODEL_SIZE

        # Build the object graph bottom-up.
        history = History(maxlen=config.HISTORY_MAX)
        recorder = Recorder()
        transcriber = Transcriber(model_size=effective_model)

        controller_holder: dict[str, "Controller"] = {}
        tray_holder: dict[str, "Tray"] = {}

        def _on_button_toggle() -> None:
            c = controller_holder.get("c")
            if c is not None:
                c.on_hotkey()

        def _on_open_settings() -> None:
            # Settings window is added in a later step; stub for now.
            log.info("settings button clicked (settings window not yet implemented)")

        window = HistoryWindow(
            history=history,
            on_copy=clipboard.set_text,
            on_toggle=_on_button_toggle,
            on_open_settings=_on_open_settings,
            hotkey_label=_pretty_hotkey(effective_hotkey),
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

        # Wire RMS from recorder → VU meter in window
        recorder.set_level_callback(window.set_level)

        hotkey = HotkeyWatcher(effective_hotkey, on_trigger=controller.on_hotkey)

        def on_left_click() -> None:
            window.toggle()

        def on_quit() -> None:
            hotkey.stop()
            window.stop()
            lock.release()

        tray = Tray(on_left_click=on_left_click, on_quit=on_quit)
        tray_holder["tray"] = tray

        # Show the window early so the user sees the spinner while Whisper loads.
        window.start()
        window.set_state("loading")

        def warmup() -> None:
            log.info("warming up whisper model (%s)...", effective_model)
            try:
                transcriber.ensure_loaded()
                window.set_state("idle")
                log.info("dict ready; press %s to record", effective_hotkey)
            except Exception:
                log.exception("initial model load failed")
                window.set_state("error")

        threading.Thread(target=warmup, name="whisper-warmup", daemon=True).start()

        hotkey.start()
        tray.run()  # blocks until on_quit
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
