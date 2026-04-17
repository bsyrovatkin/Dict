"""Clipboard wrapper that never raises - failures are reported via bool."""
from __future__ import annotations

import pyperclip

from dict.utils_logging import get_logger

log = get_logger(__name__)


def set_text(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception:
        log.exception("clipboard write failed")
        return False
