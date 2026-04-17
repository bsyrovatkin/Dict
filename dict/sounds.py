"""Asynchronous WAV playback via winsound (Windows-only)."""
from __future__ import annotations

import winsound

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


def _play(name: str) -> None:
    path = config.ASSETS_DIR / config.SOUND_FILES[name]
    if not path.exists():
        log.warning("sound %s not found at %s", name, path)
        return
    try:
        winsound.PlaySound(
            str(path),
            winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
        )
    except Exception:
        log.exception("failed to play %s", name)


def play_start() -> None:
    _play("start")


def play_stop() -> None:
    _play("stop")
