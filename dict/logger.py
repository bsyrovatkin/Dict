"""Append-only plain-text transcription log."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dict import config


def append(text: str, path: Path | None = None) -> None:
    """Append one `YYYY-MM-DD HH:MM:SS | <text>` line.

    Newlines inside `text` are escaped so each record stays on one line.
    """
    target = path if path is not None else config.LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    with target.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {safe}\n")
