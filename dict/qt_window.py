"""PySide6 main window — Jarvis-style frameless HUD.

Layout:
  ┌─────────────────────────────────────────┐
  │ ◉ DICT   [ F9 ]          ⚙   _   ✕      │
  ├─────────────────────────────────────────┤
  │                                         │
  │            ▓▓▓                          │
  │          ▓▓   ▓▓        ← record widget │
  │         ▓  ◉   ▓           (VU ring +   │
  │          ▓▓   ▓▓            pulse +     │
  │            ▓▓▓              spinner)    │
  │                                         │
  │             READY                       │
  ├─────────────────────────────────────────┤
  │  ▸ HISTORY  (click a row to copy)       │
  │    [12:34:56]  hello world              │
  │    [12:34:40]  test test                │
  └─────────────────────────────────────────┘

All cross-thread calls go through Qt signals so `set_state` / `set_level`
/ `refresh` can safely be invoked from the audio callback, the keyboard
hook, or the transcription worker.
"""
from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter,
    QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from dict.history import History
from dict.qt_design import LINE_DIM, SURFACE_1, state_color
from dict.qt_widgets.compact_history import CompactHistory
from dict.qt_widgets.cta_bar import CTABar
from dict.qt_widgets.status_strip import StatusStrip
from dict.qt_widgets.transcript_panel import TranscriptPanel
from dict.utils_logging import get_logger

log = get_logger(__name__)


# ---------- Palette --------------------------------------------------------

BG        = QColor("#05070f")
BG_PANEL  = QColor("#0a0f1a")
GRID_DIM  = QColor("#0f2a3a")
CYAN      = QColor("#00e5ff")
CYAN_DIM  = QColor("#0091a8")
CYAN_SOFT = QColor(0, 229, 255, 110)
RED       = QColor("#ff3b5c")
RED_SOFT  = QColor(255, 59, 92, 100)
YELLOW    = QColor("#ffcc00")
YELLOW_S  = QColor(255, 204, 0, 130)
FG        = QColor("#c8f0ff")
FG_DIM    = QColor("#4a6978")

MONO = "Consolas"


STATE_COLOR = {
    "idle":         CYAN,
    "recording":    RED,
    "transcribing": YELLOW,
    "busy":         YELLOW,
    "loading":      CYAN_DIM,
    "error":        QColor("#ff8a00"),
}

STATE_TEXT = {
    "idle":         "READY",
    "recording":    "● REC",
    "transcribing": "DECODING…",
    "busy":         "DECODING…",
    "loading":      "INIT…",
    "error":        "MIC ERROR",
}


# ---------- Record widget (QPainter HUD: concentric rings, VU, radar) ------

class RecordWidget(QWidget):
    """Layered HUD widget mirroring docs/superpowers/design-source/src/record-widget.jsx.

    Internal coordinate space is 360x360; the painter scales uniformly so the
    widget can be displayed at any size (typically 200x200). Layer order in
    paintEvent matches the JSX `tick()` exactly:
      1. Outer cardinal ticks
      2. Corner brackets
      3. 3 dotted concentric rings
      4. Degree ticks every 15 degrees
      5. Radar sweep (idle only)
      6. Decoding spinner arc (decoding only)
      7. VU ring (54 segments)
      8. Peak chevron (rec only)
      9. Inner core ring
     10. Pulse ring (rec only)
     11. Core glyph (play / square / dots)
     12. Center crosshair
    """

    clicked = Signal()

    VU_SEGMENTS = 54
    CORE_RADIUS = 58
    RING_INNER = 84
    RING_OUTER = 110
    R_OUT = 170

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(200, 200)
        self.setCursor(Qt.PointingHandCursor)
        self._state = "loading"
        self._level = 0.0
        self._level_target = 0.0

        # Animation phases
        self._sweep_phase = 0.0   # idle radar
        self._spin_phase = 0.0    # decoding spinner
        self._pulse_phase = 0.0   # core pulse (rec)
        self._t_ms = 0.0          # monotonic-ish time accumulator for VU/peak

        # VU envelope + peak tracker (mirrors vuRef / peakRef in JSX)
        import random as _random
        self._random = _random.Random()
        self._vu: list[float] = [0.0] * self.VU_SEGMENTS
        self._peak = {"idx": 0, "val": 0.0, "t": 0.0}

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    # ---- public API (unchanged) ----

    def set_state(self, state: str) -> None:
        self._state = state

    def set_level(self, level: float) -> None:
        self._level_target = max(0.0, min(1.0, level))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ---- state palette ----

    @staticmethod
    def _state_palette(state: str) -> dict:
        """Return {'hi','mid','ink','dim'} QColors for the given state.

        Mirrors the JSX `col` object — picks crimson for rec, amber for
        decoding/busy/transcribing, accent (cyan) for everything else.
        """
        from dict.qt_design import (
            ACCENT, ACCENT_DEEP, ACCENT_INK, ACCENT_DIM,
            AMBER, AMBER_DEEP, AMBER_INK, AMBER_DIM,
            CRIMSON, CRIMSON_DEEP, CRIMSON_INK, CRIMSON_DIM,
        )
        if state in ("recording", "rec"):
            return {"hi": CRIMSON, "mid": CRIMSON_DEEP, "ink": CRIMSON_INK, "dim": CRIMSON_DIM}
        if state in ("busy", "transcribing", "decoding"):
            return {"hi": AMBER, "mid": AMBER_DEEP, "ink": AMBER_INK, "dim": AMBER_DIM}
        # idle / loading / error -> accent
        return {"hi": ACCENT, "mid": ACCENT_DEEP, "ink": ACCENT_INK, "dim": ACCENT_DIM}

    # ---- animation tick ----

    def _tick(self) -> None:
        # Smooth incoming level
        self._level += (self._level_target - self._level) * 0.35

        # Advance phases
        self._sweep_phase += 0.06
        self._spin_phase += 0.07
        self._pulse_phase += 0.105
        self._t_ms += 33.0
        t = self._t_ms / 1000.0  # seconds

        # Update VU envelope per state — mirrors JSX `tick()` lines 47-61
        state = self._state
        if state in ("recording", "rec"):
            # When we have a live mic level use it as a multiplier so the bars
            # actually reflect speech volume; otherwise leave the random
            # envelope at full intensity.
            mult = max(0.2, self._level if self._level > 0 else 1.0)
            for i in range(self.VU_SEGMENTS):
                target = (0.25 + self._random.random() * 0.75
                          * (0.5 + 0.5 * math.sin(t * 6 + i * 0.4))) * mult
                self._vu[i] += (target - self._vu[i]) * 0.35
        elif state in ("busy", "transcribing", "decoding"):
            for i in range(self.VU_SEGMENTS):
                self._vu[i] += (0.08 - self._vu[i]) * 0.2
        else:
            for i in range(self.VU_SEGMENTS):
                self._vu[i] += (0.0 - self._vu[i]) * 0.15

        # Peak tracker with slow decay
        max_i = 0
        max_v = 0.0
        for i, v in enumerate(self._vu):
            if v > max_v:
                max_v = v
                max_i = i
        dt = (self._t_ms - self._peak["t"])
        if max_v > self._peak["val"] - dt * 0.0008:
            self._peak = {"idx": max_i, "val": max_v, "t": self._t_ms}

        self.update()

    # ---- paint ----

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QConicalGradient
        from dict.qt_design import LINE_DIM, LINE_MID

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # Scale 360x360 internal space into the actual widget rect, centered.
        s = min(self.width(), self.height()) / 360.0
        p.translate(self.width() / 2, self.height() / 2)
        p.scale(s, s)
        p.translate(-180, -180)

        cx = 180.0
        cy = 180.0
        col = self._state_palette(self._state)
        state = self._state

        # 1) Outer cardinal ticks (N/E/S/W from r=160 to r=174)
        pen = QPen(LINE_MID)
        pen.setWidthF(1.0)
        pen.setCosmetic(False)
        p.setPen(pen)
        for ang_deg in (0, 90, 180, 270):
            a = math.radians(ang_deg - 90)
            r1 = self.R_OUT - 10
            r2 = self.R_OUT + 4
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                       QPointF(cx + math.cos(a) * r2, cy + math.sin(a) * r2))

        # 2) Corner brackets at BR=178, inset 68% from center
        pen = QPen(col["ink"])
        pen.setWidthF(1.0)
        p.setPen(pen)
        BR = self.R_OUT + 8
        bracket_len = 14
        for qx, qy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            ox = cx + qx * BR * 0.68
            oy = cy + qy * BR * 0.68
            p.drawLine(QPointF(ox + qx * bracket_len, oy), QPointF(ox, oy))
            p.drawLine(QPointF(ox, oy), QPointF(ox, oy + qy * bracket_len))

        # 3) 3 concentric dotted rings
        pen = QPen(LINE_DIM)
        pen.setWidthF(1.0)
        pen.setDashPattern([1.0, 3.0])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for r in (165, 140, 120):
            p.drawEllipse(QPointF(cx, cy), r, r)

        # 4) Degree ticks every 15 degrees on inner ring (r=120)
        pen = QPen(QColor(138, 149, 172, int(0.35 * 255)))
        pen.setWidthF(1.0)
        pen.setDashPattern([])  # solid
        p.setPen(pen)
        for deg in range(0, 360, 15):
            a = math.radians(deg - 90)
            major = (deg % 45) == 0
            r1 = 120 - (6 if major else 3)
            r2 = 120
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                       QPointF(cx + math.cos(a) * r2, cy + math.sin(a) * r2))

        # 5) Radar sweep (idle only) — conic gradient, annulus 72..118
        if state == "idle":
            sweep_a = (self._sweep_phase * 0.6) % (2 * math.pi)
            # Qt's QConicalGradient: angle in degrees, 0 = 3 o'clock, ccw.
            # JSX uses 0 = 3 o'clock CW with sweep starting at (sweepA - PI/2).
            # Convert: rotate so the bright edge sits at sweep_a relative to 12 o'clock.
            angle_deg = (-math.degrees(sweep_a) + 90.0) % 360.0
            grad = QConicalGradient(QPointF(cx, cy), angle_deg)
            grad.setColorAt(0.0, col["ink"])
            grad.setColorAt(0.15, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            outer = QPainterPath()
            outer.addEllipse(QPointF(cx, cy), 118, 118)
            inner_path = QPainterPath()
            inner_path.addEllipse(QPointF(cx, cy), 72, 72)
            annulus = outer.subtracted(inner_path)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(grad))
            p.drawPath(annulus)

        # 6) Decoding spinner (decoding/busy/transcribing only)
        if state in ("busy", "transcribing", "decoding"):
            span = math.pi * 0.8
            a0 = (self._spin_phase * 2.2 / 0.07) % (2 * math.pi)  # ~t*2.2 rad/s
            # Simpler & matching the design: derive from t directly
            a0 = (t * 2.2) % (2 * math.pi)
            rect = QRectF(cx - 110, cy - 110, 220, 220)
            # Tail (faded) behind
            pen = QPen(col["ink"])
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            tail_start_deg = -math.degrees(a0 - 0.4) - 90.0 + 90.0  # see note below
            # Qt arc: 0 = 3 o'clock, ccw, units = 1/16 degree.
            # JSX angles use 0 = 3 o'clock, cw (canvas). Convert by negating.
            start16 = int(-math.degrees(a0 - 0.4) * 16)
            sweep16 = int(-math.degrees(0.4) * 16)
            p.drawArc(rect, start16, sweep16)
            # Head (bright)
            pen = QPen(col["hi"])
            pen.setWidthF(2.0)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            start16 = int(-math.degrees(a0) * 16)
            sweep16 = int(-math.degrees(span) * 16)
            p.drawArc(rect, start16, sweep16)
            del tail_start_deg  # unused diagnostic var

        # 7) VU ring: 54 segments between r=84 and r=110
        seg = self.VU_SEGMENTS
        gap_deg = 1.8 if seg >= 72 else 2.4
        seg_deg = (360.0 / seg) - gap_deg
        base_r = 84.0
        max_h = 26.0
        for i in range(seg):
            v = max(0.0, min(1.0, self._vu[i]))
            h = 2.0 + v * max_h
            r_mid = base_r + h / 2.0
            # Color by state + amplitude
            if state == "idle":
                c = col["hi"] if v > 0.01 else col["dim"]
            elif state in ("busy", "transcribing", "decoding"):
                c = col["dim"]
            else:  # rec
                if v > 0.85:
                    c = QColor("#ffffff")
                elif v > 0.55:
                    c = col["hi"]
                else:
                    c = col["mid"]
            # Stroke width approximates arc segment width (cap removed)
            # JSX computes width based on circumference; reproduce conservatively.
            stroke_w = max(1.6, (2.0 * math.pi * r_mid) / seg - gap_deg * math.pi / 180.0 * r_mid)
            stroke_w = max(1.4, stroke_w * 0.9)
            pen = QPen(c)
            pen.setWidthF(stroke_w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            # Arc angle window centered at (i * 360/seg) measured from 12 o'clock (cw)
            c_deg_cw_from_n = (i * 360.0 / seg)
            # Convert to Qt's coordinate system (0 = 3 o'clock, ccw)
            start_qt_deg = 90.0 - c_deg_cw_from_n - (seg_deg / 2.0)
            sweep_qt_deg = seg_deg
            rect = QRectF(cx - r_mid, cy - r_mid, 2 * r_mid, 2 * r_mid)
            p.drawArc(rect, int(start_qt_deg * 16), int(sweep_qt_deg * 16))

        # 8) Peak / clip chevron (rec only)
        if state in ("recording", "rec") and self._peak["val"] > 0.5:
            p_idx = self._peak["idx"]
            p_ang_cw_from_n = (p_idx * 360.0 / seg)
            # JSX: pAng = (idx*360/seg - 90) * PI/180  (radians, cw from 3 o'clock)
            p_ang = math.radians(p_ang_cw_from_n - 90.0)
            rr = base_r + max_h + 6
            peak_x = cx + math.cos(p_ang) * rr
            peak_y = cy + math.sin(p_ang) * rr
            t_ang = p_ang + math.pi  # pointing inward
            tip = 5.0
            fill = QColor("#ffffff") if self._peak["val"] > 0.92 else col["hi"]
            p.setBrush(QBrush(fill))
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(peak_x + math.cos(t_ang + 0.35) * tip,
                        peak_y + math.sin(t_ang + 0.35) * tip)
            path.lineTo(peak_x, peak_y)
            path.lineTo(peak_x + math.cos(t_ang - 0.35) * tip,
                        peak_y + math.sin(t_ang - 0.35) * tip)
            path.closeSubpath()
            p.drawPath(path)

        # 9) Inner core ring
        core_r = self.CORE_RADIUS
        if state in ("recording", "rec"):
            ring_col = col["hi"]
            ring_w = 2.0
        else:
            ring_col = col["mid"]
            ring_w = 1.25
        pen = QPen(ring_col)
        pen.setWidthF(ring_w)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), core_r, core_r)

        # 10) Pulse ring (rec only)
        if state in ("recording", "rec"):
            pulse = (math.sin(self._pulse_phase) + 1.0) / 2.0
            from dict.qt_design import CRIMSON
            pc = QColor(CRIMSON)
            pc.setAlphaF(min(1.0, 0.18 + 0.22 * pulse))
            pen = QPen(pc)
            pen.setWidthF(1.0)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), core_r + 6 + pulse * 6, core_r + 6 + pulse * 6)

        # 11) Core glyph
        if state == "idle" or state in ("loading", "error"):
            # Play triangle (filled)
            p.setBrush(QBrush(col["hi"]))
            p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(cx - 10, cy - 14)
            path.lineTo(cx + 16, cy)
            path.lineTo(cx - 10, cy + 14)
            path.closeSubpath()
            p.drawPath(path)
        elif state in ("recording", "rec"):
            # White square
            p.setBrush(QBrush(QColor("#ffffff")))
            p.setPen(Qt.NoPen)
            p.drawRect(QRectF(cx - 10, cy - 10, 20, 20))
        else:  # decoding
            # Three pulsing dots
            for i in (-1, 0, 1):
                pulse = (math.sin(t * 4 - i) + 1.0) / 2.0
                dot_col = QColor(col["hi"])
                dot_col.setAlphaF(min(1.0, 0.4 + 0.6 * pulse))
                p.setBrush(QBrush(dot_col))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(cx + i * 12, cy), 3.0, 3.0)

        # 12) Center crosshair (tiny +)
        pen = QPen(QColor(205, 215, 235, int(0.25 * 255)))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLine(QPointF(cx - 3, cy), QPointF(cx + 3, cy))
        p.drawLine(QPointF(cx, cy - 3), QPointF(cx, cy + 3))


# ---------- Header sub-widgets ---------------------------------------------

class _BrandMark(QWidget):
    """18×18 SVG-equivalent: outer ring + semi-transparent inner ring + filled dot.

    Colors driven by state via set_state().
    """
    SIZE = 22  # actual widget pixels (slightly larger hit-box around the 18px art)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._state = "idle"

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, _ev) -> None:
        from dict.qt_design import LINE_MID, state_color
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        col = state_color(self._state)

        # Outer ring: radius 7.5, LINE_MID stroke
        outer_pen = QPen(QColor(138, 149, 172, int(0.4 * 255)))
        outer_pen.setWidthF(1.0)
        p.setPen(outer_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), 7.5, 7.5)

        # Inner ring: radius 5, 50% alpha state-colored
        inner_col = QColor(col)
        inner_col.setAlphaF(0.5)
        inner_pen = QPen(inner_col)
        inner_pen.setWidthF(1.0)
        p.setPen(inner_pen)
        p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        # Center filled dot: radius 3, state-colored
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        p.drawEllipse(QPointF(cx, cy), 3.0, 3.0)


class _HotkeySlab(QWidget):
    """Clipped-polygon slab showing 'HOTKEY <key>' in mono 7pt.

    Mirrors the JSX hotkey slab: 6px corner cuts on TL + BR,
    border rgba(138,149,172,0.28), no fill.
    HOTKEY in TEXT_DIM, key in TEXT_HI.
    """

    def __init__(self, label: str = "F9", parent=None) -> None:
        super().__init__(parent)
        self._label = label.upper()
        self.setContentsMargins(8, 3, 8, 3)

    def set_label(self, label: str) -> None:
        self._label = label.upper()
        self.updateGeometry()
        self.update()

    def sizeHint(self) -> QSize:
        from dict.qt_design import FONT_MONO
        f = QFont(FONT_MONO)
        f.setPointSize(7)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        # 8px left pad + "HOTKEY " + label + 8px right pad + 4px extra
        w = fm.horizontalAdvance("HOTKEY ") + fm.horizontalAdvance(self._label) + 24
        h = fm.height() + 8
        return QSize(max(w, 60), max(h, 18))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _ev) -> None:
        from dict.qt_design import TEXT_DIM, TEXT_HI, FONT_MONO
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()

        # Build 6px clipped polygon (TL + BR corners cut)
        cut = 6
        path = QPainterPath()
        path.moveTo(r.x() + cut, r.y())
        path.lineTo(r.right(), r.y())
        path.lineTo(r.right(), r.bottom() - cut)
        path.lineTo(r.right() - cut, r.bottom())
        path.lineTo(r.x(), r.bottom())
        path.lineTo(r.x(), r.y() + cut)
        path.closeSubpath()

        pen = QPen(QColor(138, 149, 172, int(0.28 * 255)))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

        # Draw text: "HOTKEY " in dim, then label in hi
        f = QFont(FONT_MONO)
        f.setPointSize(7)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        p.setFont(f)

        prefix = "HOTKEY "
        prefix_w = fm.horizontalAdvance(prefix)
        text_h = fm.height()
        # Vertically center
        ty = r.y() + (r.height() - text_h) // 2 + fm.ascent()
        tx = r.x() + 8

        p.setPen(TEXT_DIM)
        p.drawText(tx, ty, prefix)
        p.setPen(TEXT_HI)
        p.drawText(tx + prefix_w, ty, self._label)


class _StatusPill(QWidget):
    """Animated status pill: clipped polygon (8px cuts), border+tinted fill.

    States:
      idle     → small diamond (square rotated 45°), accent color, READY label
      rec      → pulsing filled dot (sin on radius), CRIMSON, REC label
      decoding → rotating arc (top-border-only), AMBER, DECODING label
    """
    _TIMER_INTERVAL_MS = 33  # ~30 fps

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._phase = 0.0   # for pulse (rec) and spin (decoding)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._TIMER_INTERVAL_MS)
        self.setContentsMargins(8, 4, 10, 4)

    def set_state(self, state: str) -> None:
        self._state = state
        self._phase = 0.0
        self.update()

    def _tick(self) -> None:
        self._phase += 0.105  # ~3.2 rad/s at 30 fps — good for both pulse and spin
        self.update()

    def sizeHint(self) -> QSize:
        from dict.qt_design import FONT_RAJDHANI
        f = QFont(FONT_RAJDHANI)
        f.setPointSize(7)
        f.setWeight(QFont.Bold)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        max_label = "DECODING"
        w = 8 + 8 + 6 + fm.horizontalAdvance(max_label) + 10 + 8  # marker + gap + text + pad
        h = max(22, fm.height() + 8)
        return QSize(w, h)

    def paintEvent(self, _ev) -> None:
        from dict.qt_design import state_color, FONT_RAJDHANI
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect()
        state = self._state
        col = state_color(state)

        # --- Clipped polygon background (8px corner cuts on TL + BR) ---
        cut = 8
        path = QPainterPath()
        path.moveTo(r.x() + cut, r.y())
        path.lineTo(r.right(), r.y())
        path.lineTo(r.right(), r.bottom() - cut)
        path.lineTo(r.right() - cut, r.bottom())
        path.lineTo(r.x(), r.bottom())
        path.lineTo(r.x(), r.y() + cut)
        path.closeSubpath()

        # Fill: transparent for idle, 10% tinted for rec/decoding
        if state == "idle":
            p.setBrush(Qt.NoBrush)
            border_col = QColor(138, 149, 172, int(0.28 * 255))
        else:
            fill = QColor(col)
            fill.setAlpha(int(0.10 * 255))
            p.setBrush(QBrush(fill))
            border_col = col

        pen = QPen(border_col)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)

        # --- Animated marker (left side) ---
        cx_marker = r.x() + 8 + 4   # 8px left pad + 4px (half marker width=8)
        cy_marker = r.y() + r.height() / 2.0

        if state in ("recording", "rec"):
            # Pulsing filled circle: sin pulse on radius 2.5..5
            pulse = (math.sin(self._phase * 1.2) + 1.0) / 2.0  # 0..1
            radius = 2.5 + pulse * 2.5
            glow_col = QColor(col)
            glow_col.setAlpha(int(0.55 * 255))
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx_marker, cy_marker), radius, radius)
        elif state in ("busy", "transcribing", "decoding"):
            # Rotating arc — like a spinner, only the top arc portion
            p.setBrush(Qt.NoBrush)
            spin_angle = math.degrees(self._phase * 3.0) % 360.0  # fast spin
            arc_rect = QRectF(cx_marker - 4, cy_marker - 4, 8, 8)
            pen_arc = QPen(col)
            pen_arc.setWidthF(1.5)
            pen_arc.setCapStyle(Qt.RoundCap)
            p.setPen(pen_arc)
            # Draw 270° arc starting at the spin angle (leave 90° gap)
            start16 = int((90.0 - spin_angle) * 16)
            span16 = int(270 * 16)
            p.drawArc(arc_rect, start16, span16)
        else:
            # Idle: small square rotated 45° (diamond)
            p.save()
            p.translate(cx_marker, cy_marker)
            p.rotate(45.0)
            side = 5.0
            pen_d = QPen(col)
            pen_d.setWidthF(1.0)
            p.setPen(pen_d)
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(-side / 2, -side / 2, side, side))
            p.restore()

        # --- Label text ---
        label = ("REC" if state in ("recording", "rec")
                 else "DECODING" if state in ("busy", "transcribing", "decoding")
                 else "READY")
        if state == "idle":
            text_col = QColor(138, 149, 172, int(0.75 * 255))  # TEXT_MID-ish
        else:
            text_col = col

        f = QFont(FONT_RAJDHANI)
        f.setPointSize(7)
        f.setWeight(QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)  # ~0.18em at 7pt ≈ 1px
        p.setFont(f)
        p.setPen(text_col)
        # Position text after marker (marker occupies first ~16px) + 6px gap
        text_x = r.x() + 8 + 8 + 6
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        text_y = r.y() + (r.height() - fm.height()) // 2 + fm.ascent()
        p.drawText(text_x, text_y, label)


class _HeaderWidget(QWidget):
    """Full header bar: brand mark + DICT wordmark + hotkey slab + status pill
    + spacer + window controls + bottom gradient divider.

    Padding: 12/16/10/16 (top/right/bottom/left). Gap: 12px.
    """

    def __init__(
        self,
        hotkey_label: str,
        on_settings,
        on_minimize,
        on_close,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._build(hotkey_label, on_settings, on_minimize, on_close)

    def _build(self, hotkey_label, on_settings, on_minimize, on_close) -> None:
        from dict.qt_design import TEXT_HI, TEXT_MID, CRIMSON, ACCENT, FONT_RAJDHANI

        h = QHBoxLayout(self)
        h.setContentsMargins(16, 12, 16, 10)
        h.setSpacing(12)

        # --- Brand mark group (icon + "DICT" text) ---
        brand_group = QWidget()
        brand_group.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        bg_layout = QHBoxLayout(brand_group)
        bg_layout.setContentsMargins(0, 0, 0, 0)
        bg_layout.setSpacing(8)

        self._brand_mark = _BrandMark()
        bg_layout.addWidget(self._brand_mark)

        dict_label = QLabel("DICT")
        f_dict = QFont(FONT_RAJDHANI)
        f_dict.setPointSize(18)
        f_dict.setWeight(QFont.Bold)
        f_dict.setLetterSpacing(QFont.AbsoluteSpacing, 5.0)  # ~0.32em at 18pt ≈ 5–6px
        dict_label.setFont(f_dict)
        dict_label.setStyleSheet(f"color: {TEXT_HI.name()};")
        bg_layout.addWidget(dict_label)

        h.addWidget(brand_group)

        # --- Hotkey slab ---
        self._hotkey_slab = _HotkeySlab(hotkey_label)
        h.addWidget(self._hotkey_slab)

        # --- Status pill ---
        self._status_pill = _StatusPill()
        h.addWidget(self._status_pill)

        # --- Stretch ---
        h.addStretch(1)

        # --- Window control buttons ---
        btn_style_base = (
            "QPushButton {"
            "  background: transparent;"
            "  border: none;"
            f"  color: {TEXT_MID.name()};"
            "  font-size: 13px;"
            "}"
        )
        btn_style_normal_hover = (
            btn_style_base +
            "QPushButton:hover {"
            "  background: rgba(138,149,172,31);"
            f"  color: {TEXT_HI.name()};"
            "}"
        )
        btn_style_close_hover = (
            btn_style_base +
            "QPushButton:hover {"
            "  background: rgba(255,71,87,38);"
            f"  color: {CRIMSON.name()};"
            "}"
        )

        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(28, 24)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet(btn_style_normal_hover)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.clicked.connect(on_settings)
        self._paint_gear_icon(self.settings_btn)

        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setFixedSize(28, 24)
        self.minimize_btn.setCursor(Qt.PointingHandCursor)
        self.minimize_btn.setStyleSheet(btn_style_normal_hover)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.clicked.connect(on_minimize)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 24)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(btn_style_close_hover)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(on_close)

        h.addWidget(self.settings_btn)
        h.addWidget(self.minimize_btn)
        h.addWidget(self.close_btn)

    def _paint_gear_icon(self, btn: QPushButton) -> None:
        """Try to set gear PNG icon; fall back to unicode ⚙."""
        try:
            from dict import config as _cfg
            gear_png = _cfg.ASSETS_DIR / "icon_gear@2x.png"
            if gear_png.exists():
                btn.setIcon(QIcon(str(gear_png)))
                btn.setIconSize(QSize(14, 14))
                return
        except Exception:
            pass
        btn.setText("⚙")

    # ---- public API ----

    def set_state(self, state: str) -> None:
        self._state = state
        self._brand_mark.set_state(state)
        self._status_pill.set_state(state)
        self.update()  # repaint divider gradient if needed

    def set_hotkey(self, label: str) -> None:
        self._hotkey_slab.set_label(label)

    def paintEvent(self, ev) -> None:
        """Draw the bottom gradient divider over the header."""
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        y = self.height() - 1
        # Horizontal gradient: transparent → LINE_MID(35%) at 10%→90% → transparent
        grad = QLinearGradient(0, y, self.width(), y)
        transparent = QColor(0, 0, 0, 0)
        mid_col = QColor(138, 149, 172, int(0.35 * 255))
        grad.setColorAt(0.0, transparent)
        grad.setColorAt(0.10, mid_col)
        grad.setColorAt(0.90, mid_col)
        grad.setColorAt(1.0, transparent)
        p.fillRect(0, y, self.width(), 1, QBrush(grad))


# ---------- Panel widget with corner brackets ------------------------------

class _PanelWidget(QWidget):
    """Main panel widget: paints state-tinted corner brackets after children."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "idle"

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, ev) -> None:
        # Explicit fill: stylesheet-driven background can be flaky under load,
        # so paint SURFACE_1 ourselves first.
        from PySide6.QtGui import QPainter
        from dict.qt_design import paint_corner_brackets, state_color, SURFACE_1
        p_fill = QPainter(self)
        p_fill.fillRect(self.rect(), SURFACE_1)
        p_fill.end()
        super().paintEvent(ev)

        # State-tinted inner border (replaces the brittle QGraphicsDropShadowEffect)
        glow = QColor(state_color(self._state))
        glow.setAlpha(80)
        pen = QPen(glow); pen.setWidthF(1.5)
        p_brd = QPainter(self)
        p_brd.setRenderHint(QPainter.Antialiasing, True)
        p_brd.setPen(pen); p_brd.setBrush(Qt.NoBrush)
        # Inset 1px so the border sits inside the widget rect cleanly
        p_brd.drawRect(QRectF(self.rect().adjusted(1, 1, -2, -2)))
        p_brd.end()

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = state_color(self._state)
        col = QColor(col)
        col.setAlpha(180)
        # Inset 1px so brackets sit on the panel border, not outside
        rect = self.rect().adjusted(1, 1, -2, -2)
        paint_corner_brackets(p, rect, col, size=14, width=1.5)


# ---------- Main window ----------------------------------------------------

class MainWindow(QWidget):
    # Thread-safe signals
    state_changed = Signal(str)
    level_updated = Signal(float)
    history_refresh_signal = Signal()
    hotkey_label_changed = Signal(str)
    show_requested = Signal()
    toggle_requested = Signal()
    partial_appended_signal = Signal(str)
    partials_cleared_signal = Signal()

    def __init__(
        self,
        history: History,
        on_copy: Callable[[str], None],
        on_toggle: Callable[[], None],
        on_open_settings: Callable[[], None],
        on_close: Callable[[], None],
        hotkey_label: str = "F9",
    ) -> None:
        super().__init__()
        self._history = history
        self._on_copy = on_copy
        self._on_toggle = on_toggle
        self._on_open_settings = on_open_settings
        self._on_close = on_close
        self._hotkey_label = hotkey_label
        self._drag_pos: QPoint | None = None

        self.setObjectName("mainWindow")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(560, 680)
        self.resize(560, 680)

        # Ensure any gap around the panel (e.g. bleed from drop shadow) is
        # painted BG (#03040a) rather than the system default light gray.
        from PySide6.QtGui import QPalette
        from dict.qt_design import BG
        pal = self.palette()
        pal.setColor(QPalette.Window, BG)
        self.setPalette(pal)
        self.setAutoFillBackground(True)

        self._build_ui()
        self._apply_styles()

        # Signal wiring
        self.state_changed.connect(self._apply_state)
        self.level_updated.connect(self._apply_level)
        self.history_refresh_signal.connect(self._apply_refresh)
        self.hotkey_label_changed.connect(self._apply_hotkey_label)
        self.show_requested.connect(self._apply_show)
        self.toggle_requested.connect(self._apply_toggle)
        self.partial_appended_signal.connect(self._apply_partial_appended)
        self.partials_cleared_signal.connect(self._apply_partials_cleared)

    # ---- UI construction ----

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Panel container with hand-painted state-tinted border + corner brackets.
        # NB: a QGraphicsDropShadowEffect was tried here but caused hard crashes
        # under heavy CPU load (Whisper decoding) on Windows — the effect ran on
        # the GUI thread and tripped over Qt's render pipeline. The border is
        # now painted directly in _PanelWidget.paintEvent.
        self._panel = _PanelWidget(self)
        self._panel.setObjectName("panel")
        outer.addWidget(self._panel)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        # Header (Task 4: redesigned with brand mark, hotkey slab, status pill)
        inner.addWidget(self._build_header())

        # Capture zone: record widget on the left, status strip on the right
        cap = QWidget()
        cap.setStyleSheet(
            f"background-color: transparent; "
            f"border-bottom: 1px solid {LINE_DIM.name(QColor.HexArgb)};"
        )
        ch = QHBoxLayout(cap)
        ch.setContentsMargins(18, 12, 18, 8)
        ch.setSpacing(18)
        self._record_widget = RecordWidget()
        self._record_widget.setFixedSize(200, 200)
        self._record_widget.clicked.connect(self._on_toggle)
        self._status_strip = StatusStrip()
        ch.addWidget(self._record_widget, 0)
        ch.addWidget(self._status_strip, 1)
        inner.addWidget(cap)

        # CTA bar
        self._cta = CTABar(self._hotkey_label)
        inner.addWidget(self._cta)

        # Transcript panel (flex: 1)
        trx_wrapper = QWidget()
        tw = QVBoxLayout(trx_wrapper)
        tw.setContentsMargins(16, 10, 16, 8)
        self._transcript_panel = TranscriptPanel()
        tw.addWidget(self._transcript_panel, 1)
        inner.addWidget(trx_wrapper, 1)

        # Compact history at the bottom
        self._compact_history = CompactHistory(self._history, on_copy=self._on_copy)
        inner.addWidget(self._compact_history)

    def _build_header(self) -> "_HeaderWidget":
        """Build and return the header QWidget.

        The widget exposes:
          - set_state(state)      — updates brand dot + status pill
          - set_hotkey(label)     — updates the hotkey slab text
          - settings_btn / minimize_btn / close_btn — for signal wiring
        """
        self._header = _HeaderWidget(
            hotkey_label=self._hotkey_label,
            on_settings=self._on_open_settings,
            on_minimize=self.hide,
            on_close=self._on_close,
        )
        # Expose individual buttons for any external code that might reference them
        self._settings_btn = self._header.settings_btn
        self._minimize_btn = self._header.minimize_btn
        self._close_btn = self._header.close_btn
        return self._header

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            #panel {{
                background-color: {SURFACE_1.name()};
                border: 1px solid {LINE_DIM.name(QColor.HexArgb)};
                border-radius: 0px;
            }}
        """)

    # ---- drag-to-move (frameless) ----

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def closeEvent(self, event) -> None:  # noqa: N802
        # Close button → hide, not quit
        event.ignore()
        self.hide()

    # ---- thread-safe public API (emits signals) ----

    def set_state(self, state: str) -> None:
        self.state_changed.emit(state)

    def set_level(self, level: float) -> None:
        self.level_updated.emit(level)

    def refresh(self) -> None:
        self.history_refresh_signal.emit()

    def show_for(self, seconds: float) -> None:
        del seconds
        self.show_requested.emit()

    def set_hotkey_label(self, label: str) -> None:
        self._hotkey_label = label
        self.hotkey_label_changed.emit(label)

    def toggle(self) -> None:
        self.toggle_requested.emit()

    def stop(self) -> None:
        # Called from controller on quit — safely close on main thread.
        QTimer.singleShot(0, QApplication.quit)

    # ---- slots (run on main thread) ----

    def _apply_state(self, state: str) -> None:
        self._header.set_state(state)
        self._record_widget.set_state(state)
        self._status_strip.set_state(state)
        self._cta.set_state(state)
        self._transcript_panel.set_state(state)
        # Update panel border tint + corner brackets (hand-painted; no drop shadow)
        if isinstance(self._panel, _PanelWidget):
            self._panel.set_state(state)

    def _apply_level(self, level: float) -> None:
        self._record_widget.set_level(level)
        self._status_strip.set_level(level)

    def _apply_refresh(self) -> None:
        self._compact_history.refresh()

    def _apply_hotkey_label(self, label: str) -> None:
        self._header.set_hotkey(label)
        self._cta.set_hotkey(label)

    def _apply_show(self) -> None:
        # HUD style: show on top but never steal focus from the user's
        # current text field (so auto-paste sends Ctrl+V into the right
        # window). The Qt.WindowStaysOnTopHint flag is what brings us
        # to the top; raise_/activateWindow would also steal focus.
        self.show()

    def _apply_toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self._apply_show()

    def _apply_partial_appended(self, text: str) -> None:
        self._transcript_panel.append_partial(text)

    def _apply_partials_cleared(self) -> None:
        self._transcript_panel.clear()

    def append_partial(self, text: str) -> None:
        self.partial_appended_signal.emit(text)

    def clear_partials(self) -> None:
        self.partials_cleared_signal.emit()
