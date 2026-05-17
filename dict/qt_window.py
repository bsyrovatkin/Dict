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

        # --- Equalizer per-segment characteristics (precomputed) -----------
        # Each segment behaves like its own EQ band: a "frequency speed"
        # (fast for 0°/180° = "highs", slow for 90°/270° = "lows"), a unique
        # phase offset so the ring ripples, a per-segment decay, and a small
        # random hiss multiplier. Pre-computing avoids per-frame allocations.
        self._band_speed: list[float] = []
        self._band_phase: list[float] = []
        self._band_decay: list[float] = []
        self._band_hiss:  list[float] = []
        for i in range(self.VU_SEGMENTS):
            ang = i * 2 * math.pi / self.VU_SEGMENTS
            # 4..12 — slowest at the cardinal sides, fastest at top/bottom
            speed = 4.0 + 8.0 * abs(math.cos(ang))
            self._band_speed.append(speed)
            self._band_phase.append(i * 0.28)
            self._band_decay.append(0.40 if speed > 8.0 else 0.25)
            # Subtle, fixed per-segment hiss factor 0.85..1.00 (no per-frame RNG)
            self._band_hiss.append(0.85 + 0.15 * self._random.random())

        # Per-segment afterglow timestamp: when did each segment last cross 0.7?
        self._afterglow: list[float] = [-1e9] * self.VU_SEGMENTS

        # --- Decoding "brewing" state --------------------------------------
        self._pings: list[dict] = []        # active sonar pings
        self._last_ping_ms: float = -1e9
        self._particles: list[dict] = []    # tiny flickering data dots

        # --- Recording extras (Fix 3): denser visible motion in REC state.
        # Crimson signal particles inside the ring and short cyan "tick fires"
        # tangent to the outer reticle (random sensor blips).
        self._rec_particles: list[dict] = []
        self._blips: list[dict] = []
        self._last_blip_ms: float = -1e9

        # --- State transition (smooth cross-fade between idle/rec/decoding) -
        self._prev_state: str = self._state
        self._state_change_ms: float = 0.0
        self._STATE_FADE_MS = 500.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    # ---- public API (unchanged) ----

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._prev_state = self._state
            self._state_change_ms = self._t_ms
        self._state = state

    # ---- state-transition blend helper ----
    def _state_blend(self) -> tuple[str, str, float]:
        """Return (prev_state, new_state, t) where t in [0,1] is the
        progress of the current crossfade. Once t reaches 1, prev is
        collapsed to new so subsequent paints skip interpolation."""
        if self._prev_state == self._state:
            return self._state, self._state, 1.0
        age = self._t_ms - self._state_change_ms
        if age >= self._STATE_FADE_MS:
            self._prev_state = self._state
            return self._state, self._state, 1.0
        t = max(0.0, min(1.0, age / self._STATE_FADE_MS))
        # Ease-out cubic: starts fast, settles gently
        t_eased = 1.0 - (1.0 - t) ** 3
        return self._prev_state, self._state, t_eased

    @staticmethod
    def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
        return QColor(
            int(a.red()   * (1.0 - t) + b.red()   * t),
            int(a.green() * (1.0 - t) + b.green() * t),
            int(a.blue()  * (1.0 - t) + b.blue()  * t),
            int(a.alpha() * (1.0 - t) + b.alpha() * t),
        )

    def _lerp_palette(self, t: float) -> dict:
        """Interpolated palette dict between prev_state and new_state."""
        pp = self._state_palette(self._prev_state)
        np = self._state_palette(self._state)
        if t >= 1.0:
            return np
        if t <= 0.0:
            return pp
        return {k: self._lerp_color(pp[k], np[k], t) for k in pp}

    @staticmethod
    def _amount(prev: str, new: str, t: float, names: tuple[str, ...]) -> float:
        """Continuous 0..1 weight of a named state during the crossfade.
        Used for things like REC pulse ring or DECODING sonar pings that
        should fade in/out rather than snap."""
        prev_in = prev in names
        new_in = new in names
        if prev_in and new_in:
            return 1.0
        if not prev_in and not new_in:
            return 0.0
        return t if new_in else (1.0 - t)

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

        # Update VU envelope per state
        state = self._state
        if state in ("recording", "rec"):
            # Equalizer-style: drive segments from real input level + per-band
            # response curves. Real mic RMS rarely exceeds ~0.3 even on loud
            # speech, so boost it 3x (capped at 1.0) and keep a generous floor
            # so the ring is unmistakably alive even in silence. Without the
            # boost the afterglow threshold (0.7) almost never fires.
            master = max(0.22, min(1.0, self._level * 3.0))
            for i in range(self.VU_SEGMENTS):
                # Sinusoidal band envelope, unique speed + phase per segment
                band_env = 0.5 + 0.5 * math.sin(
                    t * self._band_speed[i] + self._band_phase[i]
                )
                target = master * band_env * self._band_hiss[i]
                # Mild per-frame hiss without per-segment RNG cost
                target *= 0.92 + 0.08 * math.sin(t * 17.0 + i)
                self._vu[i] += (target - self._vu[i]) * self._band_decay[i]
                # After-glow: remember the time when a segment crossed 0.7
                if self._vu[i] > 0.7:
                    self._afterglow[i] = self._t_ms
            # --- Crimson signal particles (Fix 3): up to 6 alive at once ---
            if len(self._rec_particles) < 6:
                import random as _r
                self._rec_particles.append({
                    "x": _r.uniform(-72.0, 72.0),
                    "y": _r.uniform(-72.0, 72.0),
                    "start": self._t_ms,
                    "life": _r.uniform(400.0, 700.0),
                })
            self._rec_particles = [
                pt for pt in self._rec_particles
                if self._t_ms - pt["start"] < pt["life"]
            ]
            # --- Tick-fire sensor blips (Fix 3): spawn ~3/sec, lifetime ~200ms
            if self._t_ms - self._last_blip_ms > 300.0:
                import random as _r
                self._blips.append({
                    "angle": _r.uniform(0.0, 360.0),
                    "start": self._t_ms,
                    "life": 200.0,
                })
                self._last_blip_ms = self._t_ms
            self._blips = [
                b for b in self._blips if self._t_ms - b["start"] < b["life"]
            ]
        elif state in ("busy", "transcribing", "decoding"):
            for i in range(self.VU_SEGMENTS):
                self._vu[i] += (0.08 - self._vu[i]) * 0.2
            # --- Sonar pings: spawn one every ~500ms (was 800 — denser) ---
            if self._t_ms - self._last_ping_ms > 500.0:
                self._pings.append({"start": self._t_ms})
                self._last_ping_ms = self._t_ms
            # Cull expired pings (lifetime ~1600ms — long enough to overlap 3)
            self._pings = [
                pg for pg in self._pings if self._t_ms - pg["start"] < 1600.0
            ]
            # --- Speech / data particles (up to 12 alive at once) ---
            if len(self._particles) < 12:
                import random as _r
                self._particles.append({
                    "x": _r.uniform(-70.0, 70.0),
                    "y": _r.uniform(-70.0, 70.0),
                    "start": self._t_ms,
                    "life": _r.uniform(600.0, 900.0),
                })
            self._particles = [
                pt for pt in self._particles
                if self._t_ms - pt["start"] < pt["life"]
            ]
        else:
            for i in range(self.VU_SEGMENTS):
                self._vu[i] += (0.0 - self._vu[i]) * 0.15
            # Clear decoding state when leaving the state
            if self._pings:
                self._pings.clear()
            if self._particles:
                self._particles.clear()
            # Clear REC-specific extras (Fix 3) when leaving REC.
            if self._rec_particles:
                self._rec_particles.clear()
            if self._blips:
                self._blips.clear()

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
        # Interpolate palette + state-weights for smooth crossfade between
        # idle / rec / decoding instead of the old snap-on-state-change.
        prev_state, new_state, fade_t = self._state_blend()
        col = self._lerp_palette(fade_t)
        # `state` is the destination — single-state branches below still gate
        # on it, but their visible weight is scaled by *_amount so they fade
        # in/out smoothly across the transition window.
        state = new_state
        rec_amount = self._amount(prev_state, new_state, fade_t, ("recording", "rec"))
        dec_amount = self._amount(prev_state, new_state, fade_t, ("busy", "transcribing", "decoding"))
        idle_amount = self._amount(prev_state, new_state, fade_t, ("idle", "loading", "error"))
        # Seconds clock — used by the decoding / idle / rec branches below.
        t = self._t_ms / 1000.0

        # 1) Outer cardinal ticks (N/E/S/W from r=150 to r=164) — shrunk
        # to fit inside the 170x170 visible widget bounds (was 160..174).
        pen = QPen(LINE_MID)
        pen.setWidthF(1.0)
        pen.setCosmetic(False)
        p.setPen(pen)
        for ang_deg in (0, 90, 180, 270):
            a = math.radians(ang_deg - 90)
            r1 = self.R_OUT - 20  # 150
            r2 = self.R_OUT - 6   # 164
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                       QPointF(cx + math.cos(a) * r2, cy + math.sin(a) * r2))

        # 1b) Bold state-color border ring (non-idle only). Shrunk from
        # r=174 to r=162 so it sits inside the visible widget area.
        # Forces the user to see the widget is alive in this state.
        if state != "idle" and state != "loading":
            ring_col = QColor(col["hi"]); ring_col.setAlpha(200)
            ring_pen = QPen(ring_col); ring_pen.setWidthF(3.0); ring_pen.setCapStyle(Qt.RoundCap)
            p.setPen(ring_pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), 162.0, 162.0)

        # 2) Corner brackets pulled inside the visible widget area.
        # Was BR = R_OUT + 8 = 178 (sat outside the 170x170 bounds and got
        # clipped). Now BR = R_OUT - 6 = 164, inset 68% from center, so the
        # L-bracket corner lands at ~111 internal (~52px display) and arms
        # extend further OUT to ~125 internal (~59px display) — well inside
        # the 85px display-half.
        pen = QPen(col["ink"])
        pen.setWidthF(1.0)
        p.setPen(pen)
        BR = self.R_OUT - 6  # 164
        bracket_len = 14
        for qx, qy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            ox = cx + qx * BR * 0.68
            oy = cy + qy * BR * 0.68
            p.drawLine(QPointF(ox + qx * bracket_len, oy), QPointF(ox, oy))
            p.drawLine(QPointF(ox, oy), QPointF(ox, oy + qy * bracket_len))

        # 3) 3 concentric dotted rings — bumped alpha so they read on dark bg
        # (was LINE_DIM ~30/255 — nearly invisible at the 0.472 down-scale).
        ring_col = QColor(138, 149, 172, 90)
        pen = QPen(ring_col)
        pen.setWidthF(1.0)
        pen.setDashPattern([1.0, 3.0])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for r in (155, 135, 115):
            p.drawEllipse(QPointF(cx, cy), r, r)

        # 4) Degree ticks every 15 degrees on inner dotted ring (r=115)
        pen = QPen(QColor(138, 149, 172, int(0.35 * 255)))
        pen.setWidthF(1.0)
        pen.setDashPattern([])  # solid
        p.setPen(pen)
        for deg in range(0, 360, 15):
            a = math.radians(deg - 90)
            major = (deg % 45) == 0
            r1 = 115 - (6 if major else 3)
            r2 = 115
            p.drawLine(QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                       QPointF(cx + math.cos(a) * r2, cy + math.sin(a) * r2))

        # 4b) Recording extras (Fix 3): outer "bounce sticks", inner EQ ring,
        # crimson signal particles, and random cyan tick-fire blips. These
        # add visible motion variety so the REC state reads as obviously busy.
        if state in ("recording", "rec"):
            from dict.qt_design import CRIMSON, CRIMSON_DEEP

            crimson = QColor(CRIMSON)

            # (a) 8 radial "bounce sticks" between the diagonals — now pulled
            # inward (was r=178..204, outside the visible 170-internal widget)
            # so they sit between the middle/outer dotted rings (r=135..155)
            # and grow further inward when active. Skipped on cardinal angles
            # so they don't overlap the outer ticks.
            for i, angle_deg in enumerate(
                [22, 67, 112, 157, 202, 247, 292, 337]
            ):
                phase = t * (3.0 + 0.4 * i) + i * 0.7
                env = max(0.10, self._level) * (0.5 + 0.5 * math.sin(phase))
                bar_len = 6.0 + 12.0 * env
                a = math.radians(angle_deg - 90)
                r0 = 140.0
                r1 = r0 + bar_len
                c = QColor(crimson)
                c.setAlphaF(min(1.0, 0.5 + 0.5 * env))
                pen_b = QPen(c)
                pen_b.setWidthF(2.4)
                pen_b.setCapStyle(Qt.RoundCap)
                p.setPen(pen_b)
                p.drawLine(
                    QPointF(cx + math.cos(a) * r0, cy + math.sin(a) * r0),
                    QPointF(cx + math.cos(a) * r1, cy + math.sin(a) * r1),
                )

            # (b) Inner equalizer ring — 36 thin fast bars at r~68..76.
            inner_segs = 36
            for i in range(inner_segs):
                c_deg = i * (360.0 / inner_segs)
                a_mid = math.radians(c_deg - 90)
                phase2 = t * (8.0 + math.sin(i * 0.5)) + i * 0.31
                env2 = max(0.0, self._level) * (0.3 + 0.7 * abs(math.sin(phase2)))
                bar_len = 1.0 + 7.0 * env2
                r1_in = 68.0
                r2_in = 68.0 + bar_len
                col_in = QColor(CRIMSON_DEEP) if env2 <= 0.7 else QColor(crimson)
                pen_i = QPen(col_in)
                pen_i.setWidthF(1.4)
                pen_i.setCapStyle(Qt.RoundCap)
                p.setPen(pen_i)
                p.drawLine(
                    QPointF(cx + math.cos(a_mid) * r1_in,
                            cy + math.sin(a_mid) * r1_in),
                    QPointF(cx + math.cos(a_mid) * r2_in,
                            cy + math.sin(a_mid) * r2_in),
                )

            # (c) Crimson signal particles flickering inside the ring.
            for pt in self._rec_particles:
                age_p = self._t_ms - pt["start"]
                k_p = age_p / max(1.0, pt["life"])
                # Triangle envelope (fade-in then fade-out)
                env_p = 1.0 - abs(2.0 * k_p - 1.0)
                env_p = max(0.0, min(1.0, env_p))
                pcol = QColor(crimson)
                pcol.setAlphaF(0.70 * env_p)
                p.setBrush(QBrush(pcol))
                p.setPen(Qt.NoPen)
                r_pt = 1.5 + 1.0 * env_p
                p.drawEllipse(QPointF(cx + pt["x"], cy + pt["y"]),
                              r_pt, r_pt)

            # (d) Cyan tick-fire blips tangent to the outer reticle — pulled
            # inward to r=156..164 (was 174..182, outside the visible widget).
            for b in self._blips:
                k_b = (self._t_ms - b["start"]) / max(1.0, b["life"])
                a_b = math.radians(b["angle"] - 90)
                r1_b = 156.0
                r2_b = 156.0 + 4.0 + 4.0 * (1.0 - k_b)
                cc = QColor("#ff7080")
                cc.setAlphaF(max(0.0, 1.0 - k_b))
                pen_blip = QPen(cc)
                pen_blip.setWidthF(2.0)
                pen_blip.setCapStyle(Qt.RoundCap)
                p.setPen(pen_blip)
                p.drawLine(
                    QPointF(cx + math.cos(a_b) * r1_b,
                            cy + math.sin(a_b) * r1_b),
                    QPointF(cx + math.cos(a_b) * r2_b,
                            cy + math.sin(a_b) * r2_b),
                )

        # 5a) Radar sweep — idle-weighted (slow cyan/accent sweep)
        if idle_amount > 0.001:
            sweep_a = (self._sweep_phase * 0.6) % (2 * math.pi)
            angle_deg = (-math.degrees(sweep_a) + 90.0) % 360.0
            grad = QConicalGradient(QPointF(cx, cy), angle_deg)
            ink = QColor(col["ink"]); ink.setAlphaF(min(1.0, ink.alphaF() * idle_amount))
            grad.setColorAt(0.0, ink)
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

        # 5b) REC radar sweep — faster crimson sweep at a different radius so
        # it doesn't compete with the VU ring. Adds visible "scanning" motion
        # to the REC state without overpowering the equalizer.
        if rec_amount > 0.001:
            from dict.qt_design import CRIMSON_INK as _CRINK
            rec_sweep_a = (self._sweep_phase * 1.2) % (2 * math.pi)
            rec_angle_deg = (-math.degrees(rec_sweep_a) + 90.0) % 360.0
            rec_grad = QConicalGradient(QPointF(cx, cy), rec_angle_deg)
            rec_ink = QColor(_CRINK); rec_ink.setAlphaF(min(1.0, rec_ink.alphaF() * rec_amount * 0.7))
            rec_grad.setColorAt(0.0, rec_ink)
            rec_grad.setColorAt(0.18, QColor(0, 0, 0, 0))
            rec_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            rec_outer = QPainterPath()
            rec_outer.addEllipse(QPointF(cx, cy), 158, 158)
            rec_inner = QPainterPath()
            rec_inner.addEllipse(QPointF(cx, cy), 120, 120)
            rec_annulus = rec_outer.subtracted(rec_inner)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(rec_grad))
            p.drawPath(rec_annulus)

        # 6) Decoding multi-arc spinner + sonar pings — DEC-weighted so they
        # fade in/out smoothly during state transitions.
        if dec_amount > 0.001:
            # Be explicit about composition mode here so any earlier paint
            # operation can't leave us in a mode that erases what we draw.
            from PySide6.QtGui import QPainter as _QP
            p.setCompositionMode(_QP.CompositionMode_SourceOver)

            # --- Color drift: amber <-> faintly cooler amber/green mix ---
            # 0..1 swing every ~4s. Blend 80% amber + 20% green at peak.
            drift = (math.sin(t * (2 * math.pi / 4.0)) + 1.0) / 2.0
            hi = col["hi"]
            ink = col["ink"]
            # GREEN from design palette (#6bffb3)
            mix_r = int(hi.red()   * (1 - 0.20 * drift) + 0x6b * 0.20 * drift)
            mix_g = int(hi.green() * (1 - 0.20 * drift) + 0xff * 0.20 * drift)
            mix_b = int(hi.blue()  * (1 - 0.20 * drift) + 0xb3 * 0.20 * drift)
            mix_hi = QColor(mix_r, mix_g, mix_b)
            # Bright variant of mix_ink — original ink alpha (~115) reads as
            # nearly invisible on the dark panel at 1.6px stroke.
            mix_ink = QColor(mix_r, mix_g, mix_b, 180)

            # --- Unmistakable amber backdrop fill so the user sees the state
            # change immediately even before the arcs spin in. Faint ring fill
            # at r=120 with ~10% amber alpha (scaled by dec_amount).
            backdrop_col = QColor(hi.red(), hi.green(), hi.blue(), int(28 * dec_amount))
            p.setBrush(QBrush(backdrop_col)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), 120.0, 120.0)

            # --- Sonar pings: expanding fading rings r=58 -> r=170 ---
            for pg in self._pings:
                age = self._t_ms - pg["start"]
                k = age / 1600.0
                if 0.0 <= k <= 1.0:
                    r_ping = 58.0 + (170.0 - 58.0) * k
                    alpha = int(235.0 * (1.0 - k) * (0.4 + 0.6 * min(1.0, k * 2.5)) * dec_amount)
                    pc = QColor(mix_hi.red(), mix_hi.green(), mix_hi.blue(), max(0, alpha))
                    pen_p = QPen(pc); pen_p.setWidthF(2.8); pen_p.setCapStyle(Qt.RoundCap)
                    p.setPen(pen_p); p.setBrush(Qt.NoBrush)
                    p.drawEllipse(QPointF(cx, cy), r_ping, r_ping)

            # --- Multi-arc spinner: three short arcs at scaled alpha (dec_amount)
            specs = (
                (110.0, +2.4, 0.55 * math.pi, 0.00, QColor(hi.red(), hi.green(), hi.blue(), int(255 * dec_amount)),     4.0),
                ( 95.0, -1.6, 0.55 * math.pi, 1.10, QColor(mix_hi.red(), mix_hi.green(), mix_hi.blue(), int(220 * dec_amount)), 3.4),
                ( 80.0, +1.1, 0.45 * math.pi, 2.20, QColor(mix_ink.red(), mix_ink.green(), mix_ink.blue(), int(mix_ink.alpha() * dec_amount)), 3.0),
            )
            for r_arc, omega, span_rad, phase0, color, width in specs:
                a0 = (t * omega + phase0) % (2 * math.pi)
                rect_a = QRectF(cx - r_arc, cy - r_arc, 2 * r_arc, 2 * r_arc)
                pen_a = QPen(color); pen_a.setWidthF(width); pen_a.setCapStyle(Qt.RoundCap)
                p.setPen(pen_a); p.setBrush(Qt.NoBrush)
                start16 = int(-math.degrees(a0) * 16)
                sweep16 = int(-math.degrees(span_rad) * 16)
                p.drawArc(rect_a, start16, sweep16)

            # --- Radar scan beam: thin amber line sweeping from center to r=110 ---
            beam_a = (t * 2.0) % (2 * math.pi)
            beam_dx = math.cos(beam_a - math.pi / 2) * 110.0
            beam_dy = math.sin(beam_a - math.pi / 2) * 110.0
            beam_col = QColor(hi.red(), hi.green(), hi.blue(), int(200 * dec_amount))
            pen_beam = QPen(beam_col); pen_beam.setWidthF(2.0); pen_beam.setCapStyle(Qt.RoundCap)
            p.setPen(pen_beam); p.setBrush(Qt.NoBrush)
            p.drawLine(QPointF(cx, cy), QPointF(cx + beam_dx, cy + beam_dy))

        # 7) VU ring: 54 segments — bars span r=72 .. r=154 at peak so they
        # cross the middle dotted ring (r=135) and reach the outer dotted
        # ring (r=155). Tuned for the shrunk geometry (widget visible 170px,
        # outer ticks at r=150..164, dotted rings at 115/135/155).
        seg = self.VU_SEGMENTS
        gap_deg = 1.8 if seg >= 72 else 2.4
        seg_deg = (360.0 / seg) - gap_deg
        base_r = 72.0
        max_h = 82.0
        for i in range(seg):
            v = max(0.0, min(1.0, self._vu[i]))
            h = 2.0 + v * max_h
            r_mid = base_r + h / 2.0
            # Color by state + amplitude
            if state == "idle":
                c = col["hi"] if v > 0.01 else col["dim"]
            elif state in ("busy", "transcribing", "decoding"):
                c = col["dim"]
            else:  # rec — equalizer look with afterglow
                # Afterglow: any segment that crossed 0.7 in the last 200ms
                # stays bright until the timer expires.
                glowing = (self._t_ms - self._afterglow[i]) < 200.0
                # White-cap (clip) only when we're fully into REC state —
                # otherwise the transition flashes bright white as the VU
                # envelope ramps up and many segments cross 0.85 at once.
                if v > 0.85 and rec_amount > 0.9:
                    c = QColor("#ffffff")
                elif glowing or v > 0.55:
                    c = col["hi"]
                else:
                    c = col["mid"]
            # During state crossfade, scale bar alpha by rec/idle weight so
            # the equalizer fades in/out instead of snapping.
            if state in ("recording", "rec"):
                a = QColor(c); a.setAlphaF(min(1.0, c.alphaF() * rec_amount))
                c = a
            # Stroke width: chunkier so bars read at all amplitudes (×1.6).
            stroke_w = max(2.6, (2.0 * math.pi * r_mid) / seg - gap_deg * math.pi / 180.0 * r_mid)
            stroke_w = max(2.6, stroke_w * 1.6)
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
            fill = QColor("#ffffff") if self._peak["val"] > 0.85 else col["hi"]
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

        # 10) Pulse ring + outer breathing ring — REC-weighted so they fade in
        # and out smoothly during state transitions.
        if rec_amount > 0.001:
            pulse = (math.sin(self._pulse_phase) + 1.0) / 2.0
            from dict.qt_design import CRIMSON
            pc = QColor(CRIMSON)
            pc.setAlphaF(min(1.0, (0.18 + 0.22 * pulse) * rec_amount))
            pen = QPen(pc); pen.setWidthF(1.0)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), core_r + 6 + pulse * 6, core_r + 6 + pulse * 6)
            big_r = 128.0 + 12.0 * math.sin(self._pulse_phase)
            big_col = QColor(CRIMSON)
            big_col.setAlphaF(min(1.0, (0.40 + 0.30 * pulse) * rec_amount))
            big_pen = QPen(big_col); big_pen.setWidthF(4.0); big_pen.setCapStyle(Qt.RoundCap)
            p.setPen(big_pen); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), big_r, big_r)

        # 11) Core glyph — three layers drawn with alpha = state weight so
        # idle/rec/decoding cross-fade smoothly during transitions (instead
        # of snapping). Each glyph paints if its state-weight > 0.

        # IDLE: play triangle
        if idle_amount > 0.001:
            tri_col = QColor(col["hi"]); tri_col.setAlphaF(min(1.0, idle_amount))
            p.setBrush(QBrush(tri_col)); p.setPen(Qt.NoPen)
            path = QPainterPath()
            path.moveTo(cx - 10, cy - 14)
            path.lineTo(cx + 16, cy)
            path.lineTo(cx - 10, cy + 14)
            path.closeSubpath()
            p.drawPath(path)

        # REC: crimson halo + bold white square — bumped from 24x24 internal
        # (~11px display) to 32x32 (~15px display) so the stop glyph reads
        # at the shrunk widget size. Halo radius bumped 28 → 36 to match.
        if rec_amount > 0.001:
            from PySide6.QtGui import QRadialGradient as _QRG
            from dict.qt_design import CRIMSON as _CR
            halo = _QRG(QPointF(cx, cy), 36.0)
            hc = QColor(_CR); hc.setAlpha(int(180 * rec_amount))
            halo.setColorAt(0.0, hc)
            halo.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(QBrush(halo)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), 36.0, 36.0)
            sq_col = QColor("#ffffff"); sq_col.setAlphaF(min(1.0, rec_amount))
            p.setBrush(QBrush(sq_col)); p.setPen(Qt.NoPen)
            p.drawRect(QRectF(cx - 16, cy - 16, 32, 32))

        # DECODING: particles + pulsing outer ring + amber core + orbiting dots
        if dec_amount > 0.001:
            for pt in self._particles:
                age = self._t_ms - pt["start"]
                k = age / max(1.0, pt["life"])
                env = max(0.0, min(1.0, 1.0 - abs(2.0 * k - 1.0)))
                pcol = QColor(col["hi"])
                pcol.setAlphaF(0.65 * env * dec_amount)
                p.setBrush(QBrush(pcol)); p.setPen(Qt.NoPen)
                r_pt = 2.0 + 1.0 * env
                p.drawEllipse(QPointF(cx + pt["x"], cy + pt["y"]), r_pt, r_pt)

            ring_pulse = (math.sin(t * 3.2) + 1.0) / 2.0
            outer_r = 42.0 + 12.0 * ring_pulse
            rc = QColor(col["hi"])
            rc.setAlphaF((0.30 + 0.25 * (1.0 - ring_pulse)) * dec_amount)
            pen_r = QPen(rc); pen_r.setWidthF(2.0)
            p.setPen(pen_r); p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(cx, cy), outer_r, outer_r)

            pulse_core = (math.sin(t * 2.4) + 1.0) / 2.0
            core_r = 9.0 + 5.0 * pulse_core
            core_col = QColor(col["hi"])
            core_col.setAlphaF((0.85 + 0.15 * pulse_core) * dec_amount)
            p.setBrush(QBrush(core_col)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), core_r, core_r)

            for i in range(3):
                orbit_a = t * 1.6 + (i * 2 * math.pi / 3)
                ox = cx + math.cos(orbit_a) * 22.0
                oy = cy + math.sin(orbit_a) * 22.0
                dc = QColor(col["hi"]); dc.setAlphaF(dec_amount)
                p.setBrush(QBrush(dc)); p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(ox, oy), 3.2, 3.2)

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
        f.setPointSize(7)  # compact: was 8
        f.setWeight(QFont.Medium)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        # 8px left pad + "HOTKEY " + label + 8px right pad + 4px extra
        w = fm.horizontalAdvance("HOTKEY ") + fm.horizontalAdvance(self._label) + 24
        h = fm.height() + 8
        return QSize(max(w, 60), max(h, 20))

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
        f.setPointSize(7)  # compact: was 8
        f.setWeight(QFont.Medium)
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
        f.setPointSize(7)  # compact: was 8
        f.setWeight(QFont.DemiBold)
        # Account for 22% letter-spacing applied in paintEvent (QFontMetrics
        # returns width without the spacing, so the rendered string is ~22%
        # wider than fm.horizontalAdvance suggests).
        f.setLetterSpacing(QFont.PercentageSpacing, 122)
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        max_label = "DECODING"
        text_w = fm.horizontalAdvance(max_label)
        # Layout: 8 left pad + 8 marker + 6 gap + text + 12 right pad (+ 8 cut)
        w = 8 + 8 + 6 + text_w + 12 + 8
        h = max(24, fm.height() + 8)
        return QSize(w, h)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

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
        elif state in ("busy", "transcribing", "decoding", "loading"):
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
                 else "LOADING" if state == "loading"
                 else "READY")
        if state == "idle":
            text_col = QColor(138, 149, 172, int(0.75 * 255))  # TEXT_MID-ish
        elif state == "loading":
            from dict.qt_design import CYAN_DEEP
            text_col = CYAN_DEEP
        else:
            text_col = col

        f = QFont(FONT_RAJDHANI)
        f.setPointSize(7)  # compact: was 8
        f.setWeight(QFont.DemiBold)
        f.setLetterSpacing(QFont.PercentageSpacing, 122)  # 0.22em tracking
        p.setFont(f)
        p.setPen(text_col)
        # Position text after marker (marker occupies first ~16px) + 6px gap
        text_x = r.x() + 8 + 8 + 6
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(f)
        text_y = r.y() + (r.height() - fm.height()) // 2 + fm.ascent()
        p.drawText(text_x, text_y, label)


class _WaveStrip(QWidget):
    """Mini 60×22 animated waveform strip in the header (compact).
    18 bars; the last 4 are state-colored, the rest are dim grey.
    Width was 120 — shrunk so the header fits in the 500px compact window
    without the waves running over the brand mark."""
    BARS = 18

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(60, 22)
        self._state = "idle"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(70)

    def set_state(self, state: str) -> None:
        self._state = state

    def _tick(self) -> None:
        self._phase += 0.18
        self.update()

    def paintEvent(self, _ev) -> None:
        from dict.qt_design import state_color
        p = QPainter(self)
        col = state_color(self._state)
        dim = QColor(138, 149, 172, 50)
        w = self.width()
        h = self.height()
        bar_w = max(1, int(w / self.BARS) - 1)
        for i in range(self.BARS):
            env = 0.3 + abs(math.sin(self._phase + i * 0.4)) * 0.7
            state = self._state
            if state in ("recording", "rec"):
                env *= 1.0
            elif state in ("busy", "transcribing", "decoding"):
                env *= 0.5 + 0.4 * abs(math.sin(self._phase + i * 0.2))
            else:
                env *= 0.25
            bh = max(1, int(env * (h - 4)))
            x = i * (bar_w + 1)
            y = (h - bh) // 2
            c = col if i >= self.BARS - 4 else dim
            p.fillRect(x, y, bar_w, bh, c)


class _HeaderWidget(QWidget):
    """Full header bar: brand mark + DICT wordmark + hotkey slab + status pill
    + waveform strip + spacer + window controls + bottom gradient divider.

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
        f_dict.setPointSize(14)
        f_dict.setWeight(QFont.Bold)
        # 0.32em tracking — PercentageSpacing renders more reliably across DPIs
        f_dict.setLetterSpacing(QFont.PercentageSpacing, 132)
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

        # --- Elastic gap pushes wave + window controls to the right edge,
        # so the brand mark / hotkey slab / status pill cluster on the left
        # and the wave strip never runs over them on narrow widths. ---
        h.addStretch(1)

        # --- Mini waveform strip (60×22, right-anchored) ---
        self._wave = _WaveStrip()
        h.addWidget(self._wave, 0, Qt.AlignVCenter)

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

        # Critical: NoFocus on all header buttons. Otherwise typewriter
        # streaming-paste sends Space keystrokes which Qt interprets as
        # "activate focused button" — opening Settings repeatedly when the
        # gear has stolen focus from an earlier mouse click. Mouse clicks
        # still work because we explicitly handle clicked() signal.
        self.settings_btn = QPushButton()
        self.settings_btn.setFixedSize(28, 24)
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.setStyleSheet(btn_style_normal_hover)
        self.settings_btn.setToolTip("Settings")
        self.settings_btn.setFocusPolicy(Qt.NoFocus)
        self.settings_btn.clicked.connect(on_settings)
        self._paint_gear_icon(self.settings_btn)

        self.minimize_btn = QPushButton("—")
        self.minimize_btn.setFixedSize(28, 24)
        self.minimize_btn.setCursor(Qt.PointingHandCursor)
        self.minimize_btn.setStyleSheet(btn_style_normal_hover)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.setFocusPolicy(Qt.NoFocus)
        self.minimize_btn.clicked.connect(on_minimize)

        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedSize(28, 24)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(btn_style_close_hover)
        self.close_btn.setToolTip("Close")
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.clicked.connect(on_close)

        h.addWidget(self.settings_btn)
        h.addWidget(self.minimize_btn)
        h.addWidget(self.close_btn)

    def _paint_gear_icon(self, btn: QPushButton) -> None:
        """Render the design's gear vector (circle r=2.2 + 8 radial ticks) at
        2x scale into a QPixmap using TEXT_MID. Mirrors header.jsx::WinBtn
        SVG so all three window-control glyphs (—, ✕, gear) share the same
        stroke colour and weight, matching the design comp."""
        try:
            from dict.qt_design import TEXT_MID
            from PySide6.QtGui import QPixmap
            size = 14
            scale = 2  # render @2x for crisp downscale
            pm = QPixmap(size * scale, size * scale)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing, True)
            pen = QPen(TEXT_MID)
            pen.setWidthF(1.2 * scale)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            # Inner circle r=2.2 at center (cx=cy=7 in 14px viewbox)
            cx = cy = 7.0 * scale
            p.drawEllipse(QPointF(cx, cy), 2.2 * scale, 2.2 * scale)
            # 8 radial ticks from r=5.5 to r=3.8 (length 1.7), every 45°
            for a_deg in (0, 45, 90, 135, 180, 225, 270, 315):
                a = math.radians(a_deg)
                dx, dy = math.sin(a), -math.cos(a)  # 0° = up
                x1, y1 = cx + dx * 5.5 * scale, cy + dy * 5.5 * scale
                x2, y2 = cx + dx * 3.8 * scale, cy + dy * 3.8 * scale
                p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            p.end()
            btn.setIcon(QIcon(pm))
            btn.setIconSize(QSize(size, size))
            return
        except Exception:
            pass
        btn.setText("⚙")

    # ---- public API ----

    def set_state(self, state: str) -> None:
        self._state = state
        self._brand_mark.set_state(state)
        self._status_pill.set_state(state)
        self._wave.set_state(state)
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
    """Main panel widget: paints state-tinted corner brackets after children.

    Animates color crossfade during state changes so the panel border doesn't
    snap (which previously caused the perceived 'screen flash' even though the
    RecordWidget itself was smoothing — the OUTER frame was still snapping)."""

    FADE_MS = 500

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._prev_state = "idle"
        self._fade_start_ms: float | None = None
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(33)  # ~30fps during transition only
        self._fade_timer.timeout.connect(self._on_fade_tick)
        self._import_time()

    def _import_time(self) -> None:
        import time as _t
        self._time = _t.monotonic

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._prev_state = self._state
            self._fade_start_ms = self._time() * 1000.0
            if not self._fade_timer.isActive():
                self._fade_timer.start()
        self._state = state
        self.update()

    def _on_fade_tick(self) -> None:
        if self._fade_start_ms is None:
            self._fade_timer.stop()
            return
        age = self._time() * 1000.0 - self._fade_start_ms
        if age >= self.FADE_MS:
            self._fade_start_ms = None
            self._fade_timer.stop()
        self.update()
        # Also trigger the parent MainWindow repaint so the outer glow ring
        # crossfades in lockstep with the panel's corner brackets.
        p = self.parent()
        if p is not None:
            try:
                p.update()
            except Exception:
                pass

    def _lerped_state_color(self) -> QColor:
        """Color interpolated between prev_state and current state."""
        from dict.qt_design import state_color
        new_col = state_color(self._state)
        if self._fade_start_ms is None or self._prev_state == self._state:
            return new_col
        age = self._time() * 1000.0 - self._fade_start_ms
        if age >= self.FADE_MS:
            return new_col
        t = max(0.0, min(1.0, age / self.FADE_MS))
        # Ease-out cubic
        t = 1.0 - (1.0 - t) ** 3
        prev_col = state_color(self._prev_state)
        return QColor(
            int(prev_col.red()   * (1 - t) + new_col.red()   * t),
            int(prev_col.green() * (1 - t) + new_col.green() * t),
            int(prev_col.blue()  * (1 - t) + new_col.blue()  * t),
        )

    def paintEvent(self, ev) -> None:
        from PySide6.QtGui import QPainter, QRadialGradient, QBrush
        from dict.qt_design import paint_corner_brackets, SURFACE_1
        p_fill = QPainter(self)
        p_fill.fillRect(self.rect(), SURFACE_1)
        p_fill.end()
        super().paintEvent(ev)

        lerped = self._lerped_state_color()
        r = self.rect()

        # State-tinted corner halos: four radial gradients positioned at the
        # four corners of the panel, each ~120px radius, tinted by current
        # state. No edge bands — corners glow individually, no crossing
        # artifacts, and the panel reads as "glowing from the corner brackets"
        # which matches the design's intent.
        halo = QPainter(self)
        halo.setRenderHint(QPainter.Antialiasing, True)
        radius = 130.0
        tint_in  = QColor(lerped); tint_in.setAlpha(int(0.18 * 255))
        tint_mid = QColor(lerped); tint_mid.setAlpha(int(0.05 * 255))
        clear    = QColor(0, 0, 0, 0)
        corners = [
            (r.x(), r.y()),                            # top-left
            (r.x() + r.width(), r.y()),                # top-right
            (r.x(), r.y() + r.height()),               # bottom-left
            (r.x() + r.width(), r.y() + r.height()),   # bottom-right
        ]
        for cx, cy in corners:
            grad = QRadialGradient(cx, cy, radius)
            grad.setColorAt(0.0, tint_in)
            grad.setColorAt(0.55, tint_mid)
            grad.setColorAt(1.0, clear)
            halo.fillRect(r, QBrush(grad))
        halo.end()

        # Corner brackets — sit on top of the corner halos in the state colour.
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = QColor(lerped); col.setAlpha(200)
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
    preview_set_signal = Signal(str)
    always_on_top_signal = Signal(bool)

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
        # Topmost is toggled at runtime by the controller (REC = on, IDLE = off).
        # Constructor stays NOT topmost so the app boots in the background.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # No outer GLOW_PAD ring. Previous attempts (translucent ring vs
        # opaque ring with band-gradient) both produced artifacts the user
        # rejected — desktop bleed-through, dark-frame look, corner cross
        # overlaps. The state-tinted glow is now painted INSIDE the panel via
        # corner radial gradients (no edge bands, no crossing).
        self.GLOW_PAD = 0
        self.setMinimumSize(500, 620)
        self.resize(500, 620)

        # OPAQUE window — translucent had two problems on Windows:
        #  (a) the user's colourful desktop wallpaper bled through the 14px
        #      glow ring and mixed with the state tint, producing the "грязный"
        #      green/yellow stripe the user reported on screenshot #1.
        #  (b) translucent frameless on Windows occasionally renders the panel
        #      edge with a hard 1-px artifact.
        # MainWindow.paintEvent now fills the ring with BG first, then layers
        # the state-tinted glow on top — so the glow blends with consistent
        # dark colour regardless of what's behind the window.
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
        self.preview_set_signal.connect(self._apply_preview_set)
        self.always_on_top_signal.connect(self._apply_always_on_top)

    # ---- UI construction ----

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)  # no ring, panel fills the window

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
        ch.setContentsMargins(14, 10, 14, 6)
        ch.setSpacing(14)
        self._record_widget = RecordWidget()
        self._record_widget.setFixedSize(170, 170)
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
        tw.setContentsMargins(12, 6, 12, 6)
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

    # Outer-ring glow removed entirely. The panel widget now paints 4 corner
    # radial gradients on its inside edge, which gives a "glow from the corner
    # brackets" feel without any band-crossing artifacts on the corners.

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
        """Tri-state tray toggle:
          - visible AND active (frontmost) → hide
          - visible BUT covered by another window → bring to front + brief topmost pop
          - hidden → show + brief topmost pop
        The middle case was missing — when Dict was visible but obscured by Chrome,
        the click hit `isVisible() == True` branch and hid it, so a SECOND tray
        click was needed to actually see it.
        """
        # isMinimized triggers a separate restore path
        if self.isMinimized():
            self.showNormal()
            self._tray_pop_topmost()
            return
        if self.isVisible():
            # Distinguish frontmost vs covered. On Windows, isActiveWindow is
            # the strongest signal of "frontmost"; if false, the window may be
            # technically visible but obscured.
            if self.isActiveWindow():
                self.hide()
                return
            # Visible but covered — bring to front.
            self.raise_()
            self.activateWindow()
            self._tray_pop_topmost()
            return
        # Hidden — show + pop topmost briefly so it appears above the foreground app.
        self.show()
        self._tray_pop_topmost()

    def _tray_pop_topmost(self) -> None:
        """Briefly pop to topmost (800ms) so the window actually appears above
        the user's foreground app, then drop back to non-topmost so other apps
        can naturally cover Dict afterwards."""
        try:
            import sys as _s
            if _s.platform != "win32":
                return
            import ctypes
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            from PySide6.QtCore import QTimer as _QT
            _QT.singleShot(
                800,
                lambda: user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags),
            )
        except Exception:
            log.exception("tray pop-topmost failed")

    def _apply_partial_appended(self, text: str) -> None:
        self._transcript_panel.append_partial(text)

    def _apply_partials_cleared(self) -> None:
        self._transcript_panel.clear()

    def _apply_preview_set(self, text: str) -> None:
        self._transcript_panel.set_preview(text)

    def append_partial(self, text: str) -> None:
        self.partial_appended_signal.emit(text)

    def clear_partials(self) -> None:
        self.partials_cleared_signal.emit()

    def set_preview(self, text: str) -> None:
        """Thread-safe: routes a preview update through Qt's signal queue
        so the GUI is touched only from the Qt main thread."""
        self.preview_set_signal.emit(text)

    def set_always_on_top(self, on: bool) -> None:
        """Thread-safe: toggle the Qt.WindowStaysOnTopHint flag at runtime."""
        self.always_on_top_signal.emit(bool(on))

    def _apply_always_on_top(self, on: bool) -> None:
        """Toggle topmost via Win32 SetWindowPos AND keep Qt's window-flags
        view in sync so Qt doesn't re-apply the old value on the next paint.

        On Windows:
          - HWND_TOPMOST  / HWND_NOTOPMOST flips WS_EX_TOPMOST instantly
          - HWND_TOP      raises the window above non-topmost peers
          - HWND_BOTTOM   pushes the window to the back so other apps cover it
        All with SWP_NOACTIVATE so we never steal focus.

        We also call setWindowFlag(StaysOnTop) so Qt's understanding of the
        window state matches reality — without this, Qt may reset the
        topmost state on the next show/paint and the user sees the window
        bouncing back to top.
        """
        log.info(
            "_apply_always_on_top(on=%s) visible=%s minimized=%s",
            on, self.isVisible(), self.isMinimized(),
        )

        # CRITICAL: if the window is hidden when REC starts, SetWindowPos on a
        # hidden HWND won't make it visible. Show first, then bring to front.
        if on and not self.isVisible():
            self.show()
        if on and self.isMinimized():
            self.showNormal()
        if on:
            try:
                self.raise_()
            except Exception:
                log.exception("self.raise_() before topmost failed")

        import sys as _sys
        if _sys.platform == "win32" and on:
            # Defer the win32 pop by 50ms so Qt has time to actually map
            # the window (show() is async). Running SetWindowPos on an
            # un-mapped HWND silently does nothing on some Windows builds.
            from PySide6.QtCore import QTimer as _QT
            _QT.singleShot(50, self._win32_pop_topmost)

        import sys as _sys
        if _sys.platform == "win32":
            try:
                import ctypes
                HWND_NOTOPMOST  = -2
                SWP_NOSIZE      = 0x0001
                SWP_NOMOVE      = 0x0002
                SWP_NOACTIVATE  = 0x0010
                flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
                hwnd = int(self.winId())
                user32 = ctypes.windll.user32
                if on:
                    # Already deferred via QTimer.singleShot above.
                    pass
                else:
                    # Clear topmost. We DO NOT push to HWND_BOTTOM anymore —
                    # user wants the window to stay where the eye is (still
                    # visible above the desktop) until they explicitly click
                    # another app, which then naturally covers Dict (because
                    # Dict is no longer topmost). Pushing to BOTTOM made it
                    # "disappear" relative to the workflow's other windows.
                    user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
            except Exception:
                log.exception("SetWindowPos failed (continuing with Qt fallback)")

        # On Windows the SetWindowPos call above already did the visible
        # change. DO NOT call setWindowFlag on Windows — it triggers a Qt
        # hide+show cycle which appears as a 1-frame blink during the
        # idle→rec transition (and was the actual cause of the "блик"
        # the user kept reporting; the widget crossfade was correct).
        # Qt's internal flag is stale but doesn't affect actual window state.
        if _sys.platform != "win32":
            try:
                current = bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
                if current != bool(on):
                    self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
                    if not self.isVisible():
                        self.show()
                    else:
                        self.show()
                if on:
                    self.raise_()
                else:
                    self.lower()
            except Exception:
                log.exception("Qt flag sync failed")

    def _win32_pop_topmost(self) -> None:
        """Aggressive Windows-only routine that brings the window above the
        currently-foreground app WITHOUT permanently stealing focus. Uses the
        AttachThreadInput trick to bypass Windows' foreground-rights UIPI
        (which silently makes SetWindowPos a no-op when our app isn't the
        active foreground window).

        Flow:
          1. Save current foreground hwnd
          2. Attach our thread input to the foreground thread
          3. SetWindowPos(HWND_TOPMOST | SWP_SHOWWINDOW) — actually elevates
          4. BringWindowToTop — z-order update
          5. Detach
          6. Restore foreground hwnd via SetWindowPos NOACTIVATE — fixes any
             accidental focus shift so auto-paste keeps targeting Chrome.
        """
        import sys as _sys
        if _sys.platform != "win32":
            return
        try:
            import ctypes
            from ctypes import wintypes
            HWND_TOPMOST = -1
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())

            # 1. Save foreground (so we can return focus to it).
            old_fg = user32.GetForegroundWindow()
            log.info("_win32_pop_topmost: my_hwnd=%s old_fg=%s", hwnd, old_fg)

            # 2. Attach our thread input to the foreground thread.
            attached = False
            try:
                fg_thread = user32.GetWindowThreadProcessId(old_fg, 0) if old_fg else 0
                my_thread = kernel32.GetCurrentThreadId()
                if fg_thread and fg_thread != my_thread:
                    attached = bool(user32.AttachThreadInput(fg_thread, my_thread, True))
            except Exception:
                log.exception("_win32_pop_topmost: AttachThreadInput failed")

            # 3+4. Force topmost + raise.
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
            try:
                user32.BringWindowToTop(hwnd)
            except Exception:
                log.exception("_win32_pop_topmost: BringWindowToTop failed")

            # 5. Detach.
            if attached:
                try:
                    user32.AttachThreadInput(fg_thread, my_thread, False)
                except Exception:
                    log.exception("_win32_pop_topmost: detach failed")

            # 6. Restore the foreground app's focus (without changing z-order).
            if old_fg and old_fg != hwnd:
                try:
                    user32.SetWindowPos(
                        old_fg, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                    )
                    # Re-issue our TOPMOST after restoring the other window
                    # so we're guaranteed to stay on top of it.
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
                except Exception:
                    log.exception("_win32_pop_topmost: restore focus failed")
        except Exception:
            log.exception("_win32_pop_topmost failed")
