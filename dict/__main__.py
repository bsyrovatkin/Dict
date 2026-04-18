"""Entry point: single-instance lock, Qt wiring, main loop."""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import msvcrt

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from dict import clipboard, config, logger as logger_mod, settings as settings_mod, sounds
from dict.controller import Controller
from dict.history import History
from dict.hotkey import HotkeyWatcher
from dict.qt_settings import SettingsDialog
from dict.qt_tray import Tray
from dict.qt_window import MainWindow
from dict.recorder import Recorder
from dict.transcriber import Transcriber
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
    """'ctrl+shift+v' -> 'Ctrl+Shift+V'."""
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

    # High-DPI scaling is enabled automatically in Qt 6 — no explicit attribute needed.
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(config.ASSETS_DIR / "icon_idle.ico")))

    try:
        user_settings = settings_mod.load()
        effective_hotkey = user_settings.hotkey or config.HOTKEY
        effective_model = user_settings.model_size or config.MODEL_SIZE

        # Business layer (unchanged)
        history = History(maxlen=config.HISTORY_MAX)
        recorder = Recorder()
        transcriber = Transcriber(model_size=effective_model)

        controller_holder: dict[str, Controller] = {}
        hotkey_holder: dict[str, HotkeyWatcher] = {}

        def _on_button_toggle() -> None:
            c = controller_holder.get("c")
            if c is not None:
                c.on_hotkey()

        def _on_open_settings() -> None:
            log.info("opening settings dialog")
            dlg = SettingsDialog(user_settings, _save_settings, parent=window)
            dlg.exec()

        def _on_close_app() -> None:
            log.info("quit requested")
            try:
                hotkey_holder["h"].stop()
            except Exception:
                log.exception("hotkey stop failed")
            app.quit()

        window = MainWindow(
            history=history,
            on_copy=clipboard.set_text,
            on_toggle=_on_button_toggle,
            on_open_settings=_on_open_settings,
            on_close=_on_close_app,
            hotkey_label=_pretty_hotkey(effective_hotkey),
        )

        # Simple tray facade so Controller can call set_state/notify without
        # owning a real Tray instance at construction time.
        tray_holder: dict[str, Tray] = {}

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

        recorder.set_level_callback(window.set_level)

        hotkey = HotkeyWatcher(effective_hotkey, on_trigger=controller.on_hotkey)
        hotkey_holder["h"] = hotkey

        def on_tray_click() -> None:
            window.toggle()

        tray = Tray(on_left_click=on_tray_click, on_quit=_on_close_app)
        tray_holder["tray"] = tray
        tray.show()

        def _save_settings(new: settings_mod.Settings) -> None:
            nonlocal effective_hotkey
            settings_mod.save(new)
            if new.hotkey != effective_hotkey:
                log.info("re-registering hotkey: %s -> %s",
                         effective_hotkey, new.hotkey)
                hotkey_holder["h"].stop()
                new_watcher = HotkeyWatcher(new.hotkey,
                                            on_trigger=controller.on_hotkey)
                new_watcher.start()
                hotkey_holder["h"] = new_watcher
                effective_hotkey = new.hotkey
            window.set_hotkey_label(_pretty_hotkey(new.hotkey))
            # mutate user_settings reference so next dialog reads new values
            user_settings.hotkey = new.hotkey
            user_settings.model_size = new.model_size
            user_settings.language = new.language
            user_settings.volume = new.volume
            log.info("settings applied (model/lang changes take effect next restart)")

        window.set_state("loading")
        window.show()

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

        return app.exec()
    finally:
        lock.release()


if __name__ == "__main__":
    sys.exit(main())
