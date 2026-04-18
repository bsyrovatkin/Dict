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
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, Signal,
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


# ---------- Record widget (QPainter circle + VU ring + spinner) ------------

class RecordWidget(QWidget):
    clicked = Signal()

    VU_SEGMENTS = 54
    CORE_RADIUS = 54
    RING_INNER = 86
    RING_OUTER = 140
    SPIN_ARC = 60  # degrees

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setCursor(Qt.PointingHandCursor)
        self._state = "loading"
        self._level = 0.0
        self._level_target = 0.0
        self._spin_angle = 0.0
        self._pulse_phase = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    def set_state(self, state: str) -> None:
        self._state = state

    def set_level(self, level: float) -> None:
        self._level_target = max(0.0, min(1.0, level))

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt name)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _tick(self) -> None:
        # Smooth level
        self._level += (self._level_target - self._level) * 0.35
        if self._state != "recording":
            self._level *= 0.90
        # Animation counters
        self._spin_angle = (self._spin_angle + 6) % 360
        self._pulse_phase = (self._pulse_phase + 0.12) % (2 * math.pi)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w = self.width()
        h = self.height()
        cx = w / 2
        cy = h / 2

        self._paint_grid(p, cx, cy)
        self._paint_vu_ring(p, cx, cy)
        self._paint_spinner(p, cx, cy)
        self._paint_pulse(p, cx, cy)
        self._paint_core(p, cx, cy)

    # ---- paint helpers ----

    def _paint_grid(self, p: QPainter, cx: float, cy: float) -> None:
        pen = QPen(GRID_DIM, 1)
        p.setPen(pen)
        for r in (self.RING_OUTER + 16, self.RING_OUTER + 38, self.RING_OUTER + 60):
            p.drawEllipse(QPoint(int(cx), int(cy)), r, r)
        # cardinal tick marks
        pen2 = QPen(CYAN_DIM, 1)
        p.setPen(pen2)
        for deg in (0, 90, 180, 270):
            a = math.radians(deg)
            r1 = self.RING_OUTER + 16
            r2 = self.RING_OUTER + 62
            p.drawLine(int(cx + r1 * math.cos(a)), int(cy + r1 * math.sin(a)),
                       int(cx + r2 * math.cos(a)), int(cy + r2 * math.sin(a)))

    def _paint_vu_ring(self, p: QPainter, cx: float, cy: float) -> None:
        level = max(0.0, min(1.0, self._level))
        lit_count = int(level * self.VU_SEGMENTS)
        colour = STATE_COLOR.get(self._state, CYAN)
        dim_colour = QColor(colour)
        dim_colour.setAlpha(70)

        for i in range(self.VU_SEGMENTS):
            a = 2 * math.pi * i / self.VU_SEGMENTS - math.pi / 2
            # Per-segment modulation to make it feel alive even when quiet
            seg_level = level * (0.55 + 0.45 * math.sin(i * 0.5 + self._spin_angle * 0.1))
            seg_level = max(0.0, seg_level)
            r1 = self.RING_INNER
            r2 = self.RING_INNER + 6 + (self.RING_OUTER - self.RING_INNER) * seg_level
            pen = QPen(colour if i < lit_count else dim_colour, 3)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(int(cx + r1 * math.cos(a)), int(cy + r1 * math.sin(a)),
                       int(cx + r2 * math.cos(a)), int(cy + r2 * math.sin(a)))

    def _paint_spinner(self, p: QPainter, cx: float, cy: float) -> None:
        if self._state not in ("busy", "transcribing", "loading"):
            return
        r = self.RING_OUTER + 12
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        colour = YELLOW if self._state != "loading" else CYAN
        pen = QPen(colour, 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-self._spin_angle * 16), int(self.SPIN_ARC * 16))

    def _paint_pulse(self, p: QPainter, cx: float, cy: float) -> None:
        if self._state != "recording":
            return
        breath = 0.5 + 0.5 * math.sin(self._pulse_phase)
        r = self.CORE_RADIUS + 14 + 14 * breath
        # Radial gradient for soft glow
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        glow = QColor(RED)
        glow.setAlpha(int(160 * (1 - breath * 0.5)))
        grad.setColorAt(0.7, glow)
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(int(cx), int(cy)), int(r), int(r))

    def _paint_core(self, p: QPainter, cx: float, cy: float) -> None:
        colour = STATE_COLOR.get(self._state, CYAN)
        r = self.CORE_RADIUS

        # Outer glow
        glow = QRadialGradient(cx, cy, r + 26)
        glow_colour = QColor(colour)
        glow_colour.setAlpha(110)
        glow.setColorAt(0.6, glow_colour)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(int(cx), int(cy)), r + 26, r + 26)

        # Core fill: subtle radial gradient
        if self._state == "recording":
            fill_grad = QRadialGradient(cx, cy, r)
            fill_grad.setColorAt(0.0, QColor(255, 90, 120))
            fill_grad.setColorAt(1.0, RED)
            p.setBrush(QBrush(fill_grad))
        else:
            p.setBrush(QBrush(QColor(10, 15, 28)))
        pen = QPen(colour, 3)
        p.setPen(pen)
        p.drawEllipse(QPoint(int(cx), int(cy)), r, r)

        # Mic glyph
        p.setPen(QPen(QColor(5, 7, 15) if self._state == "recording" else colour, 2))
        f = QFont(MONO, 26, QFont.Bold)
        p.setFont(f)
        glyph = "◉" if self._state == "recording" else "▶"
        p.drawText(self.rect(), Qt.AlignCenter, glyph)


# ---------- Main window ----------------------------------------------------

class MainWindow(QWidget):
    # Thread-safe signals
    state_changed = Signal(str)
    level_updated = Signal(float)
    history_refresh_signal = Signal()
    hotkey_label_changed = Signal(str)
    show_requested = Signal()
    toggle_requested = Signal()

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
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
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

        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setObjectName("iconbtn")
        self._settings_btn.setFixedSize(28, 28)
        self._settings_btn.setCursor(Qt.PointingHandCursor)
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
        self.show()
        self.raise_()
        self.activateWindow()

    def _apply_toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self._apply_show()

    def _on_history_item(self, item: QListWidgetItem) -> None:
        text = item.text().strip()
        # Drop the timestamp prefix: "HH:MM:SS   <text>"
        parts = text.split("   ", 1)
        payload = parts[1] if len(parts) == 2 else text
        try:
            self._on_copy(payload)
        except Exception:
            log.exception("on_copy failed")
