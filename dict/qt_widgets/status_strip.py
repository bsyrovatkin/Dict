"""Right-hand metrics column shown next to the record widget.

Rows: STATE (big, color = state_color), ELAPSED (mono tabular), PEAK (mono dim),
LEVEL (28-segment bar).
Mirrors app.jsx::StatRow + LevelRow.
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dict.qt_design import (
    LINE_DIM, TEXT_DIM, TEXT_HI, TEXT_MID,
    FONT_MONO, FONT_RAJDHANI,
    state_color,
)


class _LevelMeter(QWidget):
    """28-segment horizontal level bar. Top 4 segments are red (hot zone)."""
    SEGMENTS = 28
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(140, 14)
        self._level = 0.0
        self._state = "idle"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(50)

    def set_state(self, state: str) -> None:
        self._state = state

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, level))

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        w = self.width(); h = self.height()
        col = state_color(self._state)
        seg_w = w / self.SEGMENTS
        for i in range(self.SEGMENTS):
            x = i * seg_w
            lit = (i / self.SEGMENTS) < self._level
            hot = i / self.SEGMENTS > 0.85
            if lit:
                c = QColor("#ff4757") if hot else (col if i / self.SEGMENTS > 0.55 else QColor(138, 149, 172, 153))
            else:
                c = QColor(138, 149, 172, 46)
            p.fillRect(int(x), 2, int(seg_w - 1), h - 4, c)


class StatusStrip(QWidget):
    """Vertical column: STATE / ELAPSED / PEAK / LEVEL."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._peak_db = float("-inf")
        self._t0: Optional[float] = None
        self._build_ui()
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(100)

    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        self._state_label_l = self._label_dim("STATE")
        self._state_value = QLabel("IDLE")
        # Large readout: Rajdhani Bold ~14pt (spec 14–20px), 0.22em tracking
        font = QFont(FONT_RAJDHANI); font.setPointSize(14); font.setWeight(QFont.Bold)
        font.setLetterSpacing(QFont.PercentageSpacing, 122)
        self._state_value.setFont(font)
        self._state_value.setStyleSheet(f"color: {state_color('idle').name()};")

        self._elapsed_label_l = self._label_dim("ELAPSED")
        self._elapsed_value = QLabel("00:00.0")
        # Mono Medium for tabular numerics (spec wants tabular-nums readouts)
        m = QFont(FONT_MONO); m.setPointSize(11); m.setWeight(QFont.Medium)
        m.setStyleHint(QFont.Monospace)
        self._elapsed_value.setFont(m)
        self._elapsed_value.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._peak_label_l = self._label_dim("PEAK")
        self._peak_value = QLabel("-∞ dB")
        # Same Mono Medium, slightly dimmer color
        mp = QFont(FONT_MONO); mp.setPointSize(11); mp.setWeight(QFont.Medium)
        mp.setStyleHint(QFont.Monospace)
        self._peak_value.setFont(mp)
        self._peak_value.setStyleSheet(f"color: {TEXT_MID.name()};")

        self._level_label_l = self._label_dim("LEVEL")
        self._level_meter = _LevelMeter()

        # Two-column rows (label | value)
        for lbl, val in [
            (self._state_label_l, self._state_value),
            (self._elapsed_label_l, self._elapsed_value),
            (self._peak_label_l, self._peak_value),
            (self._level_label_l, self._level_meter),
        ]:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl.setFixedWidth(64)
            row.addWidget(lbl, 0)
            row.addWidget(val, 1, Qt.AlignLeft | Qt.AlignVCenter)
            v.addLayout(row)
            v.addWidget(self._divider())

        # Drop the final divider
        v.takeAt(v.count() - 1)

    def _label_dim(self, text: str) -> QLabel:
        lbl = QLabel(text)
        # Section label: Mono 8pt with wide tracking (design min 8pt)
        f = QFont(FONT_MONO); f.setPointSize(8)
        f.setStyleHint(QFont.Monospace)
        f.setLetterSpacing(QFont.PercentageSpacing, 128)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
        return lbl

    def _divider(self) -> QWidget:
        w = QWidget(); w.setFixedHeight(1)
        w.setStyleSheet(f"background-color: {LINE_DIM.name(QColor.HexArgb)};")
        return w

    def set_state(self, state: str) -> None:
        self._state = state
        if state in ("recording", "rec"):
            self._t0 = time.monotonic()
            self._state_value.setText("REC")
        elif state in ("busy", "transcribing", "decoding"):
            self._state_value.setText("DECODE")
        elif state == "loading":
            self._t0 = None
            self._state_value.setText("LOADING…")
        else:
            self._t0 = None
            self._state_value.setText("IDLE")
        col = state_color(state)
        self._state_value.setStyleSheet(f"color: {col.name()};")
        self._level_meter.set_state(state)

    def set_level(self, level: float) -> None:
        self._level_meter.set_level(level)
        # update peak (in dBFS roughly: 20 * log10(level))
        import math
        if level > 0.001:
            db = 20 * math.log10(level)
            if db > self._peak_db:
                self._peak_db = db

    def reset_peak(self) -> None:
        self._peak_db = float("-inf")

    def _tick(self) -> None:
        if self._t0 is not None:
            elapsed = time.monotonic() - self._t0
            mm = int(elapsed // 60); ss = int(elapsed % 60); ds = int((elapsed * 10) % 10)
            self._elapsed_value.setText(f"{mm:02d}:{ss:02d}.{ds:d}")
        else:
            self._elapsed_value.setText("00:00.0")
        if self._peak_db == float("-inf"):
            self._peak_value.setText("-∞ dB")
        else:
            self._peak_value.setText(f"{self._peak_db:+.1f} dB")
