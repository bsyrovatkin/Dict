"""PySide6 settings dialog — new HUD design.

Layout (mirrors docs/superpowers/design-source/src/settings.jsx):

  +------------------------------------------------+
  | CFG/ SETTINGS                                × |
  +------------------------------------------------+
  | §01 AUDIO  ───────                             |
  |   INPUT     [Realtek Audio (default)   ▼]      |
  |   MIC GAIN  [══════│════ thumb ═════] 1.20×    |
  |             LIVE  ▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮▮  1.20×     |
  |   VOLUME    [══════│════ thumb ═════] 70%      |
  |                                                |
  | §02 HOTKEY ───────                             |
  |   TRIGGER   › F9        REBIND                 |
  |   MODE      [ ⚪──] toggle · tap               |
  |   AUTO-PASTE[──⚪ ] on                         |
  |                                                |
  | §03 MODEL  ───────                             |
  |   ENGINE    [large-v3                  ▼]      |
  |   LANGUAGE  [auto                      ▼]      |
  +------------------------------------------------+
  | ESC · CLOSE                          [APPLY]   |
  +------------------------------------------------+

Public API preserved:
  - SettingsDialog(current, on_save, parent)
  - _save() builds Settings(...) with hotkey/model_size/language/
    volume/mic_gain/auto_paste and calls on_save(new_settings)
  - Hotkey capture via kb.read_hotkey in a thread + hotkey_captured signal
"""
from __future__ import annotations

import math
import threading
import time
from typing import Callable, Optional

import keyboard as kb  # type: ignore[import]
from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QMouseEvent, QPainter, QPen,
)
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from dict.hotkey import is_valid_combo, normalize_combo
from dict.qt_design import (
    ACCENT, ACCENT_DIM, ACCENT_INK, CRIMSON, FONT_MONO, FONT_RAJDHANI,
    LINE_DIM, LINE_MID, SURFACE_0, SURFACE_1, SURFACE_2,
    TEXT_DIM, TEXT_HI, TEXT_MID, paint_corner_brackets,
)
from dict.settings import Settings
from dict.utils_logging import get_logger

log = get_logger(__name__)


MODEL_CHOICES = ["large-v3", "medium", "small", "base", "tiny"]
# (display label, language code)
LANGUAGE_CHOICES: list[tuple[str, str | None]] = [
    ("auto", None),
    ("ru", "ru"),
    ("en", "en"),
    ("de", "de"),
    ("fr", "fr"),
    ("ja", "ja"),
]


# ---- Helper widgets --------------------------------------------------------


class _SectionTitle(QWidget):
    """§NN  LABEL  ───────────────── gradient line."""
    def __init__(self, num: str, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        # Tall enough for an 11pt Rajdhani label + its 1px bottom border
        self.setFixedHeight(26)
        self._num = num
        self._label = label

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        # §NN — Mono 8pt TEXT_DIM (design min 8pt)
        num_font = QFont(FONT_MONO)
        num_font.setPointSize(8)
        num_font.setStyleHint(QFont.Monospace)
        num_font.setLetterSpacing(QFont.PercentageSpacing, 110)
        p.setFont(num_font)
        p.setPen(QPen(TEXT_DIM))
        num_text = f"§{self._num}"
        num_w = p.fontMetrics().horizontalAdvance(num_text)
        # Baseline: align with LABEL baseline (drawn at y=17 below)
        p.drawText(0, 17, num_text)

        # LABEL — Rajdhani 11pt SemiBold (design: section title 11px)
        lbl_font = QFont(FONT_RAJDHANI)
        lbl_font.setPointSize(11)
        lbl_font.setWeight(QFont.DemiBold)
        lbl_font.setLetterSpacing(QFont.PercentageSpacing, 124)
        p.setFont(lbl_font)
        p.setPen(QPen(TEXT_HI))
        lbl_x = num_w + 10
        # 11pt Rajdhani — baseline at y=17 centers it in the 26px box
        p.drawText(lbl_x, 17, self._label)
        lbl_w = p.fontMetrics().horizontalAdvance(self._label)

        # Gradient line on the right (vertically centered with text mid)
        line_x = lbl_x + lbl_w + 10
        line_y = 14
        line_w = max(0, self.width() - line_x)
        if line_w > 0:
            grad = QLinearGradient(line_x, 0, line_x + line_w, 0)
            mid = QColor(LINE_MID)  # rgba(138,149,172,0.22) — close to spec 0.25
            grad.setColorAt(0.0, mid)
            grad.setColorAt(1.0, QColor(138, 149, 172, 0))
            p.fillRect(line_x, line_y, line_w, 1, grad)

        # Subtle bottom border for the section (mirrors the JSX borderBottom)
        bottom_pen = QPen(QColor(138, 149, 172, int(0.18 * 255)))
        bottom_pen.setWidthF(1)
        p.setPen(bottom_pen)
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class _Field(QWidget):
    """96px label column + flex value, baseline aligned. Optional hint right side."""
    def __init__(self, label: str, value_widget: QWidget,
                 hint: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(28)
        self._hint = hint

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 4, 0, 4)
        h.setSpacing(12)

        # Label column
        lbl = QLabel(label.upper())
        f = QFont(FONT_RAJDHANI)
        f.setPointSize(8)
        f.setWeight(QFont.Medium)
        f.setLetterSpacing(QFont.PercentageSpacing, 114)
        lbl.setFont(f)
        lbl.setStyleSheet(f"color: {TEXT_MID.name()};")
        lbl.setFixedWidth(96)
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h.addWidget(lbl, 0)

        # Value (+ hint at the right edge)
        value_widget.setSizePolicy(QSizePolicy.Expanding, value_widget.sizePolicy().verticalPolicy())
        h.addWidget(value_widget, 1)

        if hint:
            hint_lbl = QLabel(hint)
            hf = QFont(FONT_MONO)
            hf.setPointSize(8)  # design min 8pt
            hf.setStyleHint(QFont.Monospace)
            hint_lbl.setFont(hf)
            hint_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
            h.addWidget(hint_lbl, 0)
            self._hint_label = hint_lbl
        else:
            self._hint_label = None


class _StyledCombo(QComboBox):
    """QComboBox styled to match the JSX Select widget."""
    _QSS = """
    QComboBox {
        background-color: rgba(138, 149, 172, 15);
        border: 1px solid rgba(138, 149, 172, 56);
        color: %(text_hi)s;
        font-family: 'JetBrains Mono';
        font-size: 8pt;
        padding-left: 10px;
        padding-right: 22px;
        min-height: 24px;
    }
    QComboBox:focus { border: 1px solid %(accent)s; }
    QComboBox::drop-down {
        border: none;
        width: 18px;
        subcontrol-position: right center;
    }
    QComboBox::down-arrow {
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid %(accent)s;
        width: 0;
        height: 0;
        margin-right: 6px;
    }
    QComboBox QAbstractItemView {
        background-color: %(surface2)s;
        color: %(text_mid)s;
        selection-background-color: rgba(138, 149, 172, 32);
        selection-color: %(accent)s;
        border: 1px solid rgba(138, 149, 172, 72);
        outline: none;
        font-family: 'JetBrains Mono';
        font-size: 8pt;
        padding: 2px 0;
    }
    QComboBox QAbstractItemView::item {
        padding: 5px 10px;
        min-height: 18px;
    }
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(self._QSS % {
            "accent":   ACCENT.name(),
            "text_hi":  TEXT_HI.name(),
            "text_mid": TEXT_MID.name(),
            "surface2": SURFACE_2.name(),
        })
        self.setMinimumHeight(24)
        self.setMaximumHeight(24)


class _LinearSlider(QWidget):
    """Horizontal 2px track with 5 ticks, accent fill from 0→value, rect thumb,
    value label to the right. Click + drag the track."""
    value_changed = Signal(float)

    def __init__(self, value: float, vmin: float, vmax: float,
                 step: Optional[float] = None,
                 formatter: Optional[Callable[[float], str]] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._min = vmin
        self._max = vmax
        self._step = step
        self._value = max(vmin, min(vmax, value))
        self._formatter = formatter or (lambda v: f"{v:.2f}")
        self._dragging = False

        self.setFixedHeight(20)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    # ---- API ----
    def value(self) -> float:
        return self._value

    def set_value(self, v: float) -> None:
        v = max(self._min, min(self._max, v))
        if self._step:
            v = round(v / self._step) * self._step
        if v != self._value:
            self._value = v
            self.update()
            self.value_changed.emit(v)

    # ---- Geometry helpers ----
    def _track_rect(self) -> QRect:
        # leave room on the right for the value label (~52 px)
        return QRect(0, 0, max(40, self.width() - 56), self.height())

    def _value_label_rect(self) -> QRect:
        tr = self._track_rect()
        return QRect(tr.right() + 6, 0, self.width() - tr.right() - 6, self.height())

    def _pct(self) -> float:
        return (self._value - self._min) / (self._max - self._min) if self._max > self._min else 0.0

    def _value_from_x(self, x: int) -> float:
        tr = self._track_rect()
        p = max(0.0, min(1.0, (x - tr.left()) / max(1, tr.width())))
        return self._min + p * (self._max - self._min)

    # ---- Mouse ----
    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self.set_value(self._value_from_x(ev.position().toPoint().x()))

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._dragging:
            self.set_value(self._value_from_x(ev.position().toPoint().x()))

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._dragging = False

    # ---- Paint ----
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        tr = self._track_rect()
        cy = tr.center().y()
        x0, x1 = tr.left(), tr.right()
        accent = ACCENT

        # Track
        p.fillRect(x0, cy - 1, tr.width(), 2, QColor(138, 149, 172, int(0.18 * 255)))

        # Tick marks
        p.setPen(QPen(QColor(138, 149, 172, int(0.28 * 255))))
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            tx = int(x0 + t * tr.width())
            p.drawLine(tx, cy - 3, tx, cy + 3)

        # Fill
        pct = self._pct()
        fw = int(tr.width() * pct)
        p.fillRect(x0, cy - 1, fw, 2, accent)

        # Thumb 10x14
        tx = x0 + fw
        thumb = QRect(tx - 5, cy - 7, 10, 14)
        p.fillRect(thumb, SURFACE_0)
        pen = QPen(accent)
        pen.setWidthF(1)
        p.setPen(pen)
        p.drawRect(thumb)

        # Value label — Mono Medium for tabular numerics
        vlr = self._value_label_rect()
        vf = QFont(FONT_MONO)
        vf.setPointSize(9)  # was 8 — slightly more legible numeric readout
        vf.setWeight(QFont.Medium)
        vf.setStyleHint(QFont.Monospace)
        p.setFont(vf)
        p.setPen(QPen(TEXT_HI))
        p.drawText(vlr, Qt.AlignVCenter | Qt.AlignRight, self._formatter(self._value))


class _GainSlider(QWidget):
    """Log-scale slider 0.5×–5× with 1× marker and 3× CLIP marker.
    Below: LIVE/HOT label + 28-bar PreviewBars + numeric value."""
    value_changed = Signal(float)

    GMIN = 0.5
    GMAX = 5.0
    LMIN = math.log(0.5)
    LMAX = math.log(5.0)

    def __init__(self, value: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = max(self.GMIN, min(self.GMAX, value))
        self._dragging = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self._track = _GainTrack(self)
        self._track.value_changed.connect(self._on_track_changed)
        v.addWidget(self._track)

        # Live preview row: label + bars + numeric value
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._live_lbl = QLabel("LIVE")
        lf = QFont(FONT_RAJDHANI)
        lf.setPointSize(8)  # design min 8pt
        lf.setWeight(QFont.DemiBold)
        lf.setLetterSpacing(QFont.PercentageSpacing, 118)
        self._live_lbl.setFont(lf)
        self._live_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
        self._live_lbl.setFixedWidth(32)
        row.addWidget(self._live_lbl)

        self._bars = _PreviewBars(self._value, self)
        row.addWidget(self._bars)

        row.addStretch()

        self._val_lbl = QLabel(f"{self._value:.2f}×")
        vf = QFont(FONT_MONO)
        vf.setPointSize(9)  # numeric readout
        vf.setWeight(QFont.Medium)
        vf.setStyleHint(QFont.Monospace)
        self._val_lbl.setFont(vf)
        self._val_lbl.setStyleSheet(f"color: {TEXT_HI.name()};")
        self._val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._val_lbl.setFixedWidth(48)
        row.addWidget(self._val_lbl)

        v.addLayout(row)

        self._refresh_value_views()

    # ---- API ----
    def value(self) -> float:
        return self._value

    def set_value(self, v: float) -> None:
        v = max(self.GMIN, min(self.GMAX, v))
        v = round(v * 20) / 20.0  # 0.05 step
        if v != self._value:
            self._value = v
            self._track.set_value(v)
            self._refresh_value_views()
            self.value_changed.emit(v)

    def _on_track_changed(self, v: float) -> None:
        self._value = v
        self._refresh_value_views()
        self.value_changed.emit(v)

    def _refresh_value_views(self) -> None:
        in_hot = self._value > 3.0
        self._val_lbl.setText(f"{self._value:.2f}×")
        self._live_lbl.setText("HOT" if in_hot else "LIVE")
        col = CRIMSON.name() if in_hot else TEXT_DIM.name()
        self._live_lbl.setStyleSheet(f"color: {col};")
        self._bars.set_gain(self._value)


class _GainTrack(QWidget):
    """The actual sliding track for _GainSlider. Log-scale, 1× and 3× markers,
    accent fill below 3×, crimson fill above."""
    value_changed = Signal(float)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 1.0
        self._dragging = False
        self.setFixedHeight(34)  # track + room for "1×" / "CLIP" labels
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(180)
        self.setCursor(Qt.PointingHandCursor)

    def set_value(self, v: float) -> None:
        self._value = v
        self.update()

    def _pct(self, v: float) -> float:
        lv = math.log(max(_GainSlider.GMIN, min(_GainSlider.GMAX, v)))
        return (lv - _GainSlider.LMIN) / (_GainSlider.LMAX - _GainSlider.LMIN)

    def _value_from_x(self, x: int) -> float:
        tr = self._track_rect()
        p = max(0.0, min(1.0, (x - tr.left()) / max(1, tr.width())))
        v = math.exp(_GainSlider.LMIN + p * (_GainSlider.LMAX - _GainSlider.LMIN))
        return round(v * 20) / 20.0

    def _track_rect(self) -> QRect:
        # leave ~52px on the right so the right edge doesn't run into the
        # parent's hint/value column — but value is shown below, so use full width
        return QRect(2, 0, max(40, self.width() - 4), 22)

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            v = self._value_from_x(ev.position().toPoint().x())
            self._value = v
            self.update()
            self.value_changed.emit(v)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:
        if self._dragging:
            v = self._value_from_x(ev.position().toPoint().x())
            self._value = v
            self.update()
            self.value_changed.emit(v)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:
        self._dragging = False

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        tr = self._track_rect()
        cy = tr.center().y()
        x0 = tr.left()
        accent = ACCENT
        in_hot = self._value > 3.0
        pct = self._pct(self._value)
        pct1 = self._pct(1.0)
        pct3 = self._pct(3.0)

        # Track
        p.fillRect(x0, cy - 1, tr.width(), 2, QColor(138, 149, 172, int(0.18 * 255)))

        # Safe-zone fill (accent)
        safe_pct = min(pct, pct3)
        p.fillRect(x0, cy - 1, int(tr.width() * safe_pct), 2, accent)

        # Hot-zone fill (crimson)
        if in_hot:
            hot_start = int(x0 + tr.width() * pct3)
            hot_w = int(tr.width() * (pct - pct3))
            p.fillRect(hot_start, cy - 1, hot_w, 2, CRIMSON)

        # 1× marker (vertical line, full track height)
        mk1_x = int(x0 + tr.width() * pct1)
        p.setPen(QPen(QColor(205, 215, 235, int(0.35 * 255))))
        p.drawLine(mk1_x, 0, mk1_x, 22)

        # 3× marker
        mk3_x = int(x0 + tr.width() * pct3)
        p.setPen(QPen(QColor(255, 71, 87, int(0.4 * 255))))
        p.drawLine(mk3_x, 0, mk3_x, 22)

        # Labels under the markers
        mf = QFont(FONT_MONO)
        mf.setPointSize(8)  # design min 8pt
        mf.setStyleHint(QFont.Monospace)
        p.setFont(mf)
        p.setPen(QPen(TEXT_DIM))
        # Approximate centering
        p.drawText(mk1_x - 6, 33, "1×")
        p.setPen(QPen(QColor(255, 71, 87, int(0.7 * 255))))
        p.drawText(mk3_x - 14, 33, "CLIP")

        # Thumb
        tx = int(x0 + tr.width() * pct)
        thumb = QRect(tx - 5, cy - 7, 10, 14)
        p.fillRect(thumb, SURFACE_0)
        pen = QPen(CRIMSON if in_hot else accent)
        pen.setWidthF(1)
        p.setPen(pen)
        p.drawRect(thumb)


class _PreviewBars(QWidget):
    """28-segment animated preview, 140x10. Sine wave * gain.
    Cells > 0.85 amp → crimson; > 0.5 amp → accent; else dim gray."""
    BARS = 28

    def __init__(self, gain: float, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._gain = gain
        self.setFixedSize(140, 10)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(16)  # ~60 fps

    def set_gain(self, g: float) -> None:
        self._gain = g

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        W, H = self.width(), self.height()
        bar_w = max(1, (W - self.BARS) // self.BARS)
        now_ms = (time.monotonic() - self._t0) * 1000.0
        accent = ACCENT
        for i in range(self.BARS):
            env = (math.sin(now_ms * 0.005 + i * 0.6) + 1.0) / 2.0
            amp = min(1.0, env * 0.5 * self._gain)
            x = i * (bar_w + 1)
            h = max(1, int(amp * H))
            if amp > 0.85:
                col = CRIMSON
            elif amp > 0.5:
                col = accent
            else:
                col = QColor(138, 149, 172, int(0.45 * 255))
            p.fillRect(x, (H - h) // 2, bar_w, h, col)


class _Toggle(QWidget):
    """32x16 pill toggle. Click anywhere to flip. Emits toggled(bool)."""
    toggled = Signal(bool)

    def __init__(self, on: bool, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on = on
        self.setFixedSize(32, 16)
        self.setCursor(Qt.PointingHandCursor)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool) -> None:
        if on != self._on:
            self._on = on
            self.update()
            self.toggled.emit(on)

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.LeftButton:
            self.set_on(not self._on)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect().adjusted(0, 0, -1, -1)
        if self._on:
            bg = QColor(ACCENT)
            bg.setAlpha(int(0.22 * 255))
            border = ACCENT
            marker = ACCENT
        else:
            bg = QColor(138, 149, 172, int(0.12 * 255))
            border = QColor(138, 149, 172, int(0.28 * 255))
            marker = TEXT_DIM

        p.fillRect(r, bg)
        pen = QPen(border); pen.setWidthF(1)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRect(r)

        # 10x10 marker inset by 2
        mx = r.right() - 11 if self._on else r.left() + 2
        my = r.center().y() - 5
        p.fillRect(QRect(mx, my, 10, 10), marker)


class _HotkeyInput(QWidget):
    """`›  <key>           REBIND`  — looks like an inline-flex pill.
    Clicking REBIND swaps the central text for 'press combo…' until
    keyboard.read_hotkey returns. Emits rebind_requested when clicked."""
    rebind_requested = Signal()

    def __init__(self, value: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = value
        self.setFixedHeight(24)
        self.setMinimumWidth(180)

        h = QHBoxLayout(self)
        h.setContentsMargins(8, 3, 8, 3)
        h.setSpacing(6)

        chev = QLabel("›")
        cf = QFont(FONT_MONO); cf.setPointSize(9)
        chev.setFont(cf)
        chev.setStyleSheet(f"color: {TEXT_DIM.name()};")
        h.addWidget(chev)

        self._value_lbl = QLabel(value)
        vf = QFont(FONT_MONO); vf.setPointSize(8)
        vf.setLetterSpacing(QFont.PercentageSpacing, 108)
        self._value_lbl.setFont(vf)
        self._value_lbl.setStyleSheet(f"color: {TEXT_HI.name()};")
        h.addWidget(self._value_lbl, 1)

        self._rebind_btn = QPushButton("REBIND")
        rf = QFont(FONT_MONO); rf.setPointSize(8)  # design min 8pt
        rf.setWeight(QFont.Bold)
        rf.setStyleHint(QFont.Monospace)
        rf.setLetterSpacing(QFont.PercentageSpacing, 118)
        self._rebind_btn.setFont(rf)
        self._rebind_btn.setCursor(Qt.PointingHandCursor)
        self._rebind_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {ACCENT.name()}; padding: 0; }}"
            f"QPushButton:hover {{ color: {TEXT_HI.name()}; }}"
        )
        self._rebind_btn.clicked.connect(self.rebind_requested.emit)
        h.addWidget(self._rebind_btn, 0)

    def value(self) -> str:
        return self._value

    def set_value(self, v: str) -> None:
        self._value = v
        self._value_lbl.setText(v)

    def show_listening(self) -> None:
        self._value_lbl.setText("press combo…")
        self._rebind_btn.setText("LISTENING…")

    def show_idle(self) -> None:
        self._value_lbl.setText(self._value)
        self._rebind_btn.setText("REBIND")

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        r = self.rect().adjusted(0, 0, -1, -1)
        p.fillRect(r, QColor(138, 149, 172, int(0.04 * 255)))
        pen = QPen(QColor(138, 149, 172, int(0.28 * 255)))
        pen.setWidthF(1)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRect(r)


# ---- The dialog ------------------------------------------------------------


class SettingsDialog(QDialog):
    hotkey_captured = Signal(str)

    DIALOG_W = 496
    DIALOG_H = 620

    def __init__(self, current: Settings, on_save: Callable[[Settings], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = current
        self._on_save = on_save

        # Frameless + modal — we paint everything ourselves (corner brackets, etc.)
        self.setWindowTitle("Dict — settings")
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setFixedSize(self.DIALOG_W, self.DIALOG_H)
        self.setModal(True)
        self.setStyleSheet(self._dialog_qss())

        self._build_ui()
        self.hotkey_captured.connect(self._apply_captured_hotkey)

        # Center on parent
        if parent is not None:
            pg = parent.frameGeometry()
            self.move(pg.center().x() - self.DIALOG_W // 2,
                      pg.center().y() - self.DIALOG_H // 2)

    # ---- styling --------------------------------------------------------

    def _dialog_qss(self) -> str:
        return f"""
        QDialog {{
            background-color: {SURFACE_1.name()};
        }}
        QScrollArea {{
            background-color: transparent;
            border: none;
        }}
        QScrollArea > QWidget > QWidget {{ background-color: transparent; }}
        QScrollBar:vertical {{
            background: transparent;
            width: 6px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: rgba(138, 149, 172, 56);
            border-radius: 3px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: rgba(138, 149, 172, 96);
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: transparent; height: 0; border: none;
        }}
        """

    # ---- layout ---------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._h_divider(), 0)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(20, 16, 20, 16)
        body_l.setSpacing(0)
        self._build_body(body_l)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        root.addWidget(self._h_divider(), 0)
        root.addWidget(self._build_footer())

    def _h_divider(self) -> QWidget:
        d = QFrame()
        d.setFixedHeight(1)
        d.setStyleSheet(f"background-color: rgba(138, 149, 172, 46);")
        return d

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(36)
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 0, 8, 0)
        h.setSpacing(10)

        # CFG/
        cfg = QLabel("CFG/")
        f1 = QFont(FONT_MONO); f1.setPointSize(8)  # design min 8pt
        f1.setStyleHint(QFont.Monospace)
        f1.setLetterSpacing(QFont.PercentageSpacing, 112)
        cfg.setFont(f1)
        cfg.setStyleSheet(f"color: {TEXT_DIM.name()};")
        h.addWidget(cfg)

        # SETTINGS
        title = QLabel("SETTINGS")
        f2 = QFont(FONT_RAJDHANI); f2.setPointSize(11); f2.setWeight(QFont.DemiBold)
        f2.setLetterSpacing(QFont.PercentageSpacing, 128)
        title.setFont(f2)
        title.setStyleSheet(f"color: {TEXT_HI.name()};")
        h.addWidget(title)

        h.addStretch()

        # × close button
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 20)
        close_btn.setCursor(Qt.PointingHandCursor)
        cf = QFont(); cf.setPointSize(12)
        close_btn.setFont(cf)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {TEXT_MID.name()}; }}"
            f"QPushButton:hover {{ color: {TEXT_HI.name()}; }}"
        )
        close_btn.clicked.connect(self.reject)
        h.addWidget(close_btn)
        return w

    def _build_body(self, layout: QVBoxLayout) -> None:
        # §01 AUDIO
        layout.addWidget(_SectionTitle("01", "AUDIO"))
        layout.addSpacing(12)

        self._input_combo = _StyledCombo()
        # Microphone selection isn't wired through Settings yet — show a single
        # entry so the field renders but is read-only.
        self._input_combo.addItems(["default (system input)"])
        layout.addWidget(_Field("INPUT", self._input_combo))

        self._gain_slider = _GainSlider(self._current.mic_gain)
        layout.addWidget(_Field("MIC GAIN", self._gain_slider))

        self._vol_slider = _LinearSlider(
            self._current.volume, 0.0, 1.0, step=0.01,
            formatter=lambda v: f"{int(round(v * 100))}%",
        )
        layout.addWidget(_Field("VOLUME", self._vol_slider, hint="playback"))

        layout.addSpacing(16)

        # §02 HOTKEY
        layout.addWidget(_SectionTitle("02", "HOTKEY"))
        layout.addSpacing(12)

        self._hotkey_input = _HotkeyInput(self._current.hotkey)
        self._hotkey_input.rebind_requested.connect(self._start_capture)
        layout.addWidget(_Field("TRIGGER", self._hotkey_input))

        # Mode (cosmetic — push-to-talk not actually wired yet)
        mode_row = QWidget()
        mr = QHBoxLayout(mode_row)
        mr.setContentsMargins(0, 0, 0, 0); mr.setSpacing(8)
        self._mode_toggle = _Toggle(on=False)
        self._mode_toggle.toggled.connect(self._on_mode_toggled)
        mr.addWidget(self._mode_toggle)
        self._mode_lbl = QLabel("toggle · tap")
        mlf = QFont(FONT_MONO); mlf.setPointSize(8)
        self._mode_lbl.setFont(mlf)
        self._mode_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
        mr.addWidget(self._mode_lbl)
        mr.addStretch()
        layout.addWidget(_Field("MODE", mode_row))

        # Auto-paste — saves
        ap_row = QWidget()
        apr = QHBoxLayout(ap_row)
        apr.setContentsMargins(0, 0, 0, 0); apr.setSpacing(8)
        self._auto_paste_toggle = _Toggle(on=self._current.auto_paste)
        self._auto_paste_toggle.toggled.connect(self._on_auto_paste_toggled)
        apr.addWidget(self._auto_paste_toggle)
        self._ap_lbl = QLabel("on" if self._current.auto_paste else "off")
        self._ap_lbl.setFont(mlf)
        self._ap_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")
        apr.addWidget(self._ap_lbl)
        apr.addStretch()
        layout.addWidget(_Field("AUTO-PASTE", ap_row, hint="ctrl+v into focus"))

        layout.addSpacing(16)

        # §03 MODEL
        layout.addWidget(_SectionTitle("03", "MODEL"))
        layout.addSpacing(12)

        self._model_combo = _StyledCombo()
        self._model_combo.addItems(MODEL_CHOICES)
        if self._current.model_size in MODEL_CHOICES:
            self._model_combo.setCurrentText(self._current.model_size)
        layout.addWidget(_Field("ENGINE", self._model_combo))

        self._lang_combo = _StyledCombo()
        self._lang_combo.addItems([lbl for lbl, _ in LANGUAGE_CHOICES])
        self._lang_combo.setCurrentText(_lang_label(self._current.language))
        layout.addWidget(_Field("LANGUAGE", self._lang_combo))

        layout.addStretch(1)

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(40)
        h = QHBoxLayout(w)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(8)

        esc = QLabel("ESC · CLOSE")
        ef = QFont(FONT_MONO); ef.setPointSize(8)  # design min 8pt
        ef.setStyleHint(QFont.Monospace)
        ef.setLetterSpacing(QFont.PercentageSpacing, 108)
        esc.setFont(ef)
        esc.setStyleSheet(f"color: {TEXT_DIM.name()};")
        h.addWidget(esc)

        h.addStretch()

        apply_btn = QPushButton("APPLY")
        af = QFont(FONT_RAJDHANI); af.setPointSize(9); af.setWeight(QFont.Bold)
        af.setLetterSpacing(QFont.PercentageSpacing, 120)
        apply_btn.setFont(af)
        apply_btn.setCursor(Qt.PointingHandCursor)
        # Accent-tinted fill + accent border + accent text
        accent_hex = ACCENT.name()
        accent_tint = QColor(ACCENT); accent_tint.setAlpha(int(0.18 * 255))
        apply_btn.setStyleSheet(
            f"QPushButton {{"
            f" background-color: rgba({ACCENT.red()}, {ACCENT.green()}, {ACCENT.blue()}, 46);"
            f" border: 1px solid {accent_hex};"
            f" color: {accent_hex};"
            f" padding: 4px 18px;"
            f"}}"
            f"QPushButton:hover {{ background-color: rgba({ACCENT.red()}, {ACCENT.green()}, {ACCENT.blue()}, 72); }}"
        )
        apply_btn.clicked.connect(self._save)
        h.addWidget(apply_btn)
        return w

    # ---- paint border + corner brackets --------------------------------

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        # Outer 1px border at rgba(138,149,172,0.3)
        pen = QPen(QColor(138, 149, 172, int(0.3 * 255)))
        pen.setWidthF(1)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        # Corner brackets in accent
        paint_corner_brackets(p, self.rect().adjusted(0, 0, -1, -1), ACCENT, size=10, width=1.5)

    # ---- toggle handlers -----------------------------------------------

    def _on_mode_toggled(self, on: bool) -> None:
        self._mode_lbl.setText("push-to-talk · hold" if on else "toggle · tap")

    def _on_auto_paste_toggled(self, on: bool) -> None:
        self._ap_lbl.setText("on" if on else "off")

    # ---- hotkey capture (preserved from original) -----------------------

    def _start_capture(self) -> None:
        self._hotkey_input.show_listening()

        def capture() -> None:
            try:
                raw = kb.read_hotkey(suppress=False)
            except Exception:
                log.exception("hotkey capture failed")
                raw = self._current.hotkey
            combo = normalize_combo(raw)
            if not is_valid_combo(combo):
                log.warning("captured unparseable combo %r -> %r, keeping old",
                            raw, combo)
                combo = self._current.hotkey
            self.hotkey_captured.emit(combo)

        threading.Thread(target=capture, name="hotkey-capture", daemon=True).start()

    def _apply_captured_hotkey(self, combo: str) -> None:
        self._hotkey_input.set_value(combo)
        self._hotkey_input.show_idle()

    # ---- save -----------------------------------------------------------

    def _save(self) -> None:
        combo = self._hotkey_input.value().strip()
        if not combo or combo.startswith("press"):
            combo = self._current.hotkey
        combo = normalize_combo(combo)
        if not is_valid_combo(combo):
            log.warning("invalid combo %r, reverting to %r",
                        combo, self._current.hotkey)
            combo = self._current.hotkey

        lang_label_val = self._lang_combo.currentText()
        lang_value = next((v for lbl, v in LANGUAGE_CHOICES if lbl == lang_label_val),
                          self._current.language)

        new = Settings(
            hotkey=combo,
            model_size=self._model_combo.currentText(),
            language=lang_value,
            volume=self._vol_slider.value(),
            mic_gain=self._gain_slider.value(),
            auto_paste=self._auto_paste_toggle.is_on(),
        )
        try:
            self._on_save(new)
        finally:
            self.accept()


# ---- helpers ---------------------------------------------------------------


def _lang_label(value: str | None) -> str:
    for lbl, v in LANGUAGE_CHOICES:
        if v == value:
            return lbl
    return LANGUAGE_CHOICES[0][0]
