"""Bounded most-recent-first history of transcriptions."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Entry:
    timestamp: datetime
    text: str


class History:
    def __init__(self, maxlen: int) -> None:
        self._items: deque[Entry] = deque(maxlen=maxlen)

    def push(self, text: str) -> Entry:
        entry = Entry(timestamp=datetime.now(), text=text)
        self._items.append(entry)
        return entry

    def items(self) -> list[Entry]:
        """Return entries newest-first."""
        return list(reversed(self._items))
