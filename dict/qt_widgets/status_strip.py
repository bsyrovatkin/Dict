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
    ACCENT, LINE_DIM, TEXT_DIM, TEXT_HI, TEXT_MID,
    FONT_MONO, FONT_RAJDHANI,
    state_color,
)


class _GlowLabel(QLabel):
    """QLabel that paints a soft halo behind the text in the same colour as
    the text itself. Mirrors app.jsx::StatRow `textShadow: 0 0 8px ${color}55`
    when highlight=true (state != idle)."""
    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self._fg = TEXT_HI
        self._glow = False
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_color(self, color: QColor, *, glow: bool) -> None:
        self._fg = QColor(color)
        self._glow = glow
        self.setStyleSheet(f"color: {color.name()}; background: transparent;")
        self.update()

    def paintEvent(self, ev) -> None:
        if self._glow:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            # Two-pass faux glow: large soft halo + tighter inner halo.
            r = self.rect()
            from PySide6.QtGui import QRadialGradient, QBrush
            cx, cy = r.width() / 2.0, r.height() / 2.0
            radius = max(r.width(), r.height()) * 0.65
            grad = QRadialGradient(cx, cy, radius)
            halo = QColor(self._fg); halo.setAlpha(0x55)  # 0x55 ≈ 33% — matches CSS "color55"
            inner = QColor(self._fg); inner.setAlpha(0x28)
            grad.setColorAt(0.0, halo)
            grad.setColorAt(0.45, inner)
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(r, QBrush(grad))
        super().paintEvent(ev)


class _LevelMeter(QWidget):
    """28-segment horizontal level bar. Top 4 segments are red (hot zone)."""
    SEGMENTS = 28
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Design width is 140 (app.jsx LevelRow). Was 124 — bumped to match.
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
        # Use the glow-aware label so the value gets a state-tinted text-shadow
        # (mirrors app.jsx::StatRow `textShadow: 0 0 8px ${color}55` when highlight).
        self._state_value = _GlowLabel("IDLE")
        # Large readout: Rajdhani Bold 18pt (design app.jsx: fontSize 20 for `big`).
        # Was 12pt — too close to ELAPSED size and missing the design's hero-readout feel.
        font = QFont(FONT_RAJDHANI); font.setPointSize(18); font.setWeight(QFont.Bold)
        font.setLetterSpacing(QFont.PercentageSpacing, 122)
        self._state_value.setFont(font)
        self._state_value.set_color(state_color('idle'), glow=False)

        self._elapsed_label_l = self._label_dim("ELAPSED")
        self._elapsed_value = QLabel("00:00.0")
        # Mono Medium 10pt (compact: was 11) for tabular numerics
        m = QFont(FONT_MONO); m.setPointSize(10); m.setWeight(QFont.Medium)
        m.setStyleHint(QFont.Monospace)
        self._elapsed_value.setFont(m)
        self._elapsed_value.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._peak_label_l = self._label_dim("PEAK")
        self._peak_value = QLabel("-∞ dB")
        # Same Mono Medium 10pt, slightly dimmer color
        mp = QFont(FONT_MONO); mp.setPointSize(10); mp.setWeight(QFont.Medium)
        mp.setStyleHint(QFont.Monospace)
        self._peak_value.setFont(mp)
        self._peak_value.setStyleSheet(f"color: {TEXT_MID.name()};")

        self._level_label_l = self._label_dim("LEVEL")
        self._level_meter = _LevelMeter()

        # Two-column rows. Divider pattern mirrors app.jsx:
        #   STATE  ─── divider ───  ELAPSED  PEAK  ─── divider ───  LEVEL
        # i.e. ONE divider after STATE, ONE divider between PEAK and LEVEL.
        # No divider between ELAPSED and PEAK, no divider below LEVEL.
        rows = [
            (self._state_label_l, self._state_value, True),    # divider AFTER state
            (self._elapsed_label_l, self._elapsed_value, False),
            (self._peak_label_l, self._peak_value, True),      # divider AFTER peak
            (self._level_label_l, self._level_meter, False),
        ]
        for lbl, val, add_div in rows:
            row = QHBoxLayout()
            row.setSpacing(10)
            lbl.setFixedWidth(56)
            row.addWidget(lbl, 0)
            row.addWidget(val, 1, Qt.AlignLeft | Qt.AlignVCenter)
            v.addLayout(row)
            if add_div:
                v.addWidget(self._divider())

    def _label_dim(self, text: str) -> QLabel:
        lbl = QLabel(text)
        # Section label: Mono 7pt (compact: was 8) with wide tracking
        f = QFont(FONT_MONO); f.setPointSize(7)
        f.setStyleHint(QFont.Monospace)
        f.setLetterSpacing(QFont.PercentageSpacing, 128)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
        return lbl

    def _divider(self) -> QWidget:
        """Horizontal gradient line: line-mid alpha 18% at left, fades to
        transparent at 80% across the width. Mirrors app.jsx::Divider."""
        from PySide6.QtGui import QLinearGradient, QBrush, QPainter

        class _GradLine(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self.setFixedHeight(1)

            def paintEvent(self, _ev) -> None:
                p = QPainter(self)
                w = self.width()
                grad = QLinearGradient(0, 0, w, 0)
                grad.setColorAt(0.0, QColor(138, 149, 172, int(0.18 * 255)))
                grad.setColorAt(0.80, QColor(138, 149, 172, 0))
                grad.setColorAt(1.0, QColor(138, 149, 172, 0))
                p.fillRect(self.rect(), QBrush(grad))

        return _GradLine()

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
        # Glow on non-idle states (mirrors app.jsx `highlight={state !== 'idle'}`)
        is_idle = state in ("idle", "ready", "loading")
        self._state_value.set_color(col, glow=not is_idle)
        # ELAPSED turns accent-cyan when actively recording (app.jsx::StatRow `active={state==='rec'}`)
        if state in ("recording", "rec"):
            self._elapsed_value.setStyleSheet(f"color: {ACCENT.name()};")
        else:
            self._elapsed_value.setStyleSheet(f"color: {TEXT_HI.name()};")
        self._level_meter.set_state(state)
        self.update()  # repaint top-tinted background gradient

    def paintEvent(self, ev) -> None:
        """Subtle state-tinted gradient at the top of the strip (5% alpha,
        fades to transparent at the bottom). Mirrors app.jsx wrapper
        `background: linear-gradient(180deg, color-mix(in oklab, ${stateColor} 5%, transparent) 0%, transparent 100%)`.
        Painted as a wide top halo, no harsh edge."""
        from PySide6.QtGui import QLinearGradient, QBrush
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect()
        col = state_color(self._state)
        tint = QColor(col); tint.setAlpha(int(0.06 * 255))
        grad = QLinearGradient(0, 0, 0, r.height())
        grad.setColorAt(0.0, tint)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(r, QBrush(grad))
        super().paintEvent(ev)

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
