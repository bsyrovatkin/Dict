"""System tray icon wrapper around pystray."""
from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


class Tray:
    def __init__(
        self,
        on_left_click: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_left_click = on_left_click
        self._on_quit = on_quit
        self._images: dict[str, Image.Image] = {
            state: Image.open(config.ASSETS_DIR / filename)
            for state, filename in config.ICON_FILES.items()
        }
        self._icon = pystray.Icon(
            name="dict",
            icon=self._images["idle"],
            title="Dict - voice transcriber",
            menu=pystray.Menu(
                pystray.MenuItem("Show/hide", self._handle_click, default=True, visible=False),
                pystray.MenuItem("Quit", self._handle_quit),
            ),
        )

    def set_state(self, state: str) -> None:
        img = self._images.get(state)
        if img is None:
            log.warning("unknown tray state %s", state)
            return
        self._icon.icon = img

    def run(self) -> None:
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()

    def _handle_click(self, icon, item) -> None:
        try:
            self._on_left_click()
        except Exception:
            log.exception("tray click handler raised")

    def _handle_quit(self, icon, item) -> None:
        try:
            self._on_quit()
        finally:
            icon.stop()

    def notify(self, title: str, message: str) -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            log.exception("tray notify failed")
