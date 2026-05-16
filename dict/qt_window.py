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
    QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from dict.history import History
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
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMinimumSize(560, 680)
        self.resize(560, 680)

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
        outer.setContentsMargins(12, 12, 12, 12)

        # Rounded panel container
        self._panel = QWidget(self)
        self._panel.setObjectName("panel")
        shadow = QGraphicsDropShadowEffect(self._panel)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 229, 255, 80))
        shadow.setOffset(0, 0)
        self._panel.setGraphicsEffect(shadow)

        outer.addWidget(self._panel)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(16, 12, 16, 16)
        inner.setSpacing(8)

        inner.addLayout(self._build_header())
        inner.addWidget(self._build_record(), 1)
        inner.addWidget(self._build_status())
        inner.addWidget(self._build_partials())
        inner.addWidget(self._build_history(), 0)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self._title = QLabel("◉ DICT")
        self._title.setObjectName("title")

        self._hotkey_badge = QLabel(f"[ {self._hotkey_label} ]")
        self._hotkey_badge.setObjectName("hotkey")

        row.addWidget(self._title)
        row.addWidget(self._hotkey_badge)
        row.addStretch()

        self._settings_btn = QPushButton()
        self._settings_btn.setObjectName("iconbtn")
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setCursor(Qt.PointingHandCursor)
        # Use the generated gear PNG; fall back to unicode if missing.
        from dict import config as _cfg
        gear_png = _cfg.ASSETS_DIR / "icon_gear@2x.png"
        if gear_png.exists():
            self._settings_btn.setIcon(QIcon(str(gear_png)))
            self._settings_btn.setIconSize(QSize(18, 18))
        else:
            self._settings_btn.setText("⚙")
        self._settings_btn.clicked.connect(self._on_open_settings)

        self._minimize_btn = QPushButton("—")
        self._minimize_btn.setObjectName("iconbtn")
        self._minimize_btn.setFixedSize(28, 28)
        self._minimize_btn.setCursor(Qt.PointingHandCursor)
        self._minimize_btn.clicked.connect(self.hide)

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("closebtn")
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setCursor(Qt.PointingHandCursor)
        self._close_btn.clicked.connect(self._on_close)

        row.addWidget(self._settings_btn)
        row.addWidget(self._minimize_btn)
        row.addWidget(self._close_btn)
        return row

    def _build_record(self) -> QWidget:
        self._record_widget = RecordWidget()
        self._record_widget.clicked.connect(self._on_toggle)
        return self._record_widget

    def _build_status(self) -> QLabel:
        self._status = QLabel("INIT…")
        self._status.setObjectName("status")
        self._status.setAlignment(Qt.AlignCenter)
        return self._status

    def _build_partials(self) -> QWidget:
        # ScrollArea containing a word-wrapped label. Hidden when empty.
        from PySide6.QtWidgets import QScrollArea

        self._partials_box = QScrollArea()
        self._partials_box.setObjectName("partialsBox")
        self._partials_box.setWidgetResizable(True)
        self._partials_box.setMaximumHeight(120)
        self._partials_box.setFrameShape(QScrollArea.NoFrame)

        self._partials_label = QLabel("")
        self._partials_label.setObjectName("partialsLabel")
        self._partials_label.setWordWrap(True)
        self._partials_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._partials_box.setWidget(self._partials_label)
        self._partials_box.setVisible(False)
        return self._partials_box

    def _build_history(self) -> QWidget:
        box = QWidget()
        box.setObjectName("historyPanel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        label = QLabel("▸ HISTORY   (click a row to copy)")
        label.setObjectName("historyLabel")
        lay.addWidget(label)

        self._history_list = QListWidget()
        self._history_list.setObjectName("historyList")
        self._history_list.itemClicked.connect(self._on_history_item)
        lay.addWidget(self._history_list)
        return box

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            #panel {{
                background-color: {BG.name()};
                border: 1px solid #1a3a5a;
                border-radius: 14px;
            }}
            #title {{
                color: {CYAN.name()};
                font-family: '{MONO}';
                font-size: 17px;
                font-weight: bold;
            }}
            #hotkey {{
                color: {CYAN_DIM.name()};
                font-family: '{MONO}';
                font-size: 11px;
                font-weight: bold;
                padding: 2px 8px;
                border: 1px solid {CYAN_DIM.name()};
                border-radius: 4px;
            }}
            #iconbtn, #closebtn {{
                background: transparent;
                color: {FG_DIM.name()};
                border: 1px solid transparent;
                border-radius: 4px;
                font-size: 14px;
                font-weight: bold;
            }}
            #iconbtn:hover {{
                color: {CYAN.name()};
                border-color: {CYAN_DIM.name()};
            }}
            #closebtn:hover {{
                color: {RED.name()};
                border-color: {RED.name()};
            }}
            #status {{
                color: {CYAN.name()};
                font-family: '{MONO}';
                font-size: 12px;
                font-weight: bold;
                letter-spacing: 2px;
                padding: 4px 0 6px 0;
            }}
            #partialsBox {{
                background-color: {BG_PANEL.name()};
                border: 1px solid #122030;
                border-radius: 8px;
            }}
            #partialsLabel {{
                color: {FG.name()};
                font-family: '{MONO}';
                font-size: 10pt;
                padding: 8px 10px;
            }}
            #historyPanel {{
                background-color: {BG_PANEL.name()};
                border: 1px solid #122030;
                border-radius: 8px;
            }}
            #historyLabel {{
                color: {CYAN_DIM.name()};
                font-family: '{MONO}';
                font-size: 9px;
                font-weight: bold;
                padding: 8px 10px 4px 10px;
                letter-spacing: 1px;
            }}
            #historyList {{
                background: transparent;
                border: none;
                color: {FG.name()};
                font-family: '{MONO}';
                font-size: 10pt;
                padding: 0 6px 6px 6px;
            }}
            #historyList::item {{
                padding: 6px 8px;
                border-radius: 4px;
            }}
            #historyList::item:hover {{
                background-color: #0f2a3a;
            }}
            #historyList::item:selected {{
                background-color: {CYAN.name()};
                color: {BG.name()};
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
        self._record_widget.set_state(state)
        self._status.setText(STATE_TEXT.get(state, "READY"))
        self._status.setStyleSheet(
            f"color: {STATE_COLOR.get(state, CYAN).name()}; "
            f"font-family: '{MONO}'; font-size: 12px; font-weight: bold; "
            f"letter-spacing: 2px;"
        )

    def _apply_level(self, level: float) -> None:
        self._record_widget.set_level(level)

    def _apply_refresh(self) -> None:
        self._history_list.clear()
        for entry in self._history.items():
            ts = entry.timestamp.strftime("%H:%M:%S")
            item = QListWidgetItem(f"  {ts}   {entry.text}")
            self._history_list.addItem(item)

    def _apply_hotkey_label(self, label: str) -> None:
        self._hotkey_badge.setText(f"[ {label} ]")

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
        current = self._partials_label.text()
        joined = (current + " " + text).strip() if current else text
        self._partials_label.setText(joined)
        self._partials_box.setVisible(True)
        # Auto-scroll to bottom — defer so Qt recomputes the label height first
        def _scroll_to_bottom() -> None:
            bar = self._partials_box.verticalScrollBar()
            bar.setValue(bar.maximum())
        QTimer.singleShot(0, _scroll_to_bottom)

    def _apply_partials_cleared(self) -> None:
        self._partials_label.setText("")
        self._partials_box.setVisible(False)

    def append_partial(self, text: str) -> None:
        self.partial_appended_signal.emit(text)

    def clear_partials(self) -> None:
        self.partials_cleared_signal.emit()

    def _on_history_item(self, item: QListWidgetItem) -> None:
        text = item.text().strip()
        # Drop the timestamp prefix: "HH:MM:SS   <text>"
        parts = text.split("   ", 1)
        payload = parts[1] if len(parts) == 2 else text
        try:
            self._on_copy(payload)
        except Exception:
            log.exception("on_copy failed")
