"""Single line: PRESS [hotkey] TO START DICTATION.
Hotkey badge uses a clipped polygon (slab-style)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from dict.qt_design import (
    LINE_DIM, LINE_MID, TEXT_DIM, TEXT_HI,
    FONT_MONO,
    state_color,
)


class _HotkeyBadge(QLabel):
    """Slab badge (clipped corners) showing the hotkey."""
    def __init__(self, label: str = "F9", parent=None) -> None:
        super().__init__(label.upper(), parent)
        # Compact: 8pt for the F9 chip (was 9)
        f = QFont(FONT_MONO); f.setPointSize(8); f.setWeight(QFont.DemiBold)
        f.setStyleHint(QFont.Monospace)
        f.setLetterSpacing(QFont.PercentageSpacing, 116)
        self.setFont(f)
        self.setAlignment(Qt.AlignCenter)
        self.setContentsMargins(10, 3, 10, 3)
        self._state = "idle"
        self.setStyleSheet(f"color: {TEXT_HI.name()};")

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def set_label(self, label: str) -> None:
        self.setText(label.upper())

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        # Build clipped polygon (slab) — 6px corner cuts on top-left + bottom-right
        path = QPainterPath()
        cut = 6
        path.moveTo(r.x() + cut, r.y())
        path.lineTo(r.x() + r.width(), r.y())
        path.lineTo(r.x() + r.width(), r.y() + r.height() - cut)
        path.lineTo(r.x() + r.width() - cut, r.y() + r.height())
        path.lineTo(r.x(), r.y() + r.height())
        path.lineTo(r.x(), r.y() + cut)
        path.closeSubpath()
        col = state_color(self._state)
        if self._state == "idle":
            p.setBrush(Qt.NoBrush)
            pen_col = QColor(138, 149, 172, 90)
        else:
            fill = QColor(col); fill.setAlpha(31)  # 12%
            p.setBrush(fill)
            pen_col = col
        pen = QPen(pen_col); pen.setWidthF(1)
        p.setPen(pen)
        p.drawPath(path)
        super().paintEvent(ev)


class CTABar(QWidget):
    """PRESS [F9] TO START DICTATION."""
    def __init__(self, hotkey: str = "F9", parent=None) -> None:
        super().__init__(parent)
        self._hotkey = hotkey
        self._build()

    def _build(self) -> None:
        h = QHBoxLayout(self)
        h.setContentsMargins(16, 7, 16, 7)
        h.setAlignment(Qt.AlignCenter)
        h.setSpacing(10)

        f_mono_sm = QFont(FONT_MONO); f_mono_sm.setPointSize(7)  # compact: was 8
        f_mono_sm.setStyleHint(QFont.Monospace)
        f_mono_sm.setLetterSpacing(QFont.PercentageSpacing, 114)

        self._pre = QLabel("PRESS")
        self._pre.setFont(f_mono_sm)
        self._pre.setStyleSheet(f"color: {TEXT_DIM.name()};")

        self._badge = _HotkeyBadge(self._hotkey)

        self._post = QLabel("TO START DICTATION")
        self._post.setFont(f_mono_sm)
        self._post.setStyleSheet(f"color: {TEXT_DIM.name()};")

        h.addWidget(self._pre)
        h.addWidget(self._badge)
        h.addWidget(self._post)

        # Bottom border is drawn as a gradient in paintEvent (mirrors header).

    def set_state(self, state: str) -> None:
        self._badge.set_state(state)
        self._post.setText(
            "TO STOP & TRANSCRIBE" if state in ("recording", "rec")
            else "TO CANCEL DECODING" if state in ("busy", "transcribing", "decoding")
            else "WHISPER MODEL LOADING…" if state == "loading"
            else "TO START DICTATION"
        )

    def set_hotkey(self, label: str) -> None:
        self._badge.set_label(label)

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        # Bottom divider as horizontal gradient (line-mid 18% → transparent 80%)
        from PySide6.QtGui import QLinearGradient, QBrush
        p = QPainter(self)
        y = self.height() - 1
        grad = QLinearGradient(0, y, self.width(), y)
        grad.setColorAt(0.0, QColor(138, 149, 172, int(0.18 * 255)))
        grad.setColorAt(0.80, QColor(138, 149, 172, 0))
        grad.setColorAt(1.0, QColor(138, 149, 172, 0))
        p.fillRect(0, y, self.width(), 1, QBrush(grad))
