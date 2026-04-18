"""QSystemTrayIcon wrapper — native Windows tray with icon state changes.

Replaces the pystray implementation. Runs on the main Qt thread.
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


class Tray(QObject):
    # Thread-safe re-emission for icon state changes
    state_change = Signal(str)

    def __init__(
        self,
        on_left_click: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_left_click = on_left_click
        self._on_quit = on_quit
        self._icons: dict[str, QIcon] = {
            state: QIcon(str(config.ASSETS_DIR / filename))
            for state, filename in config.ICON_FILES.items()
        }
        self._tray = QSystemTrayIcon(self._icons["idle"])
        self._tray.setToolTip("Dict — voice transcriber")

        menu = QMenu()
        show_act = menu.addAction("Show / hide")
        show_act.triggered.connect(lambda: self._on_left_click())
        menu.addSeparator()
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(lambda: self._on_quit())
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_activated)
        self.state_change.connect(self._apply_state)

    def show(self) -> None:
        self._tray.show()

    def set_state(self, state: str) -> None:
        self.state_change.emit(state)

    def _apply_state(self, state: str) -> None:
        icon = self._icons.get(state)
        if icon is None:
            log.warning("unknown tray state %s", state)
            return
        self._tray.setIcon(icon)

    def notify(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message, self._icons.get("idle"), 3000)

    def _on_activated(self, reason) -> None:
        from PySide6.QtWidgets import QSystemTrayIcon as QSTI
        # Left click or double-click toggles the window
        if reason in (QSTI.Trigger, QSTI.DoubleClick, QSTI.MiddleClick):
            try:
                self._on_left_click()
            except Exception:
                log.exception("tray click handler raised")
