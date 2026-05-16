# HUD Redesign — pixel-perfect adoption of Claude Design output

> **For agentic workers:** Use superpowers:subagent-driven-development. Each task references the design source under `docs/superpowers/design-source/` — READ those files first when implementing the matching task.

**Goal:** Replace the current Jarvis-style window with the new HUD design (cyan accent default; auto-switches to crimson on rec / amber on decoding). 560×680 window, Rajdhani + JetBrains Mono fonts, new palette, full layout: header / capture-zone / CTA bar / transcript panel / compact history. All sci-fi decorations included (corner brackets, ticks, radar sweep, peak chevron, cadence dots).

**Architecture:** Reuse the existing Qt window shell and signal wiring; replace internals piece by piece. The record widget remains a QPainter widget (rewrite its paint code). New widgets: `StatusStrip` (vertical metrics column), `CTABar`, `TranscriptPanel` (replaces the current QLabel partials box), `CompactHistory` (replaces current history list).

**Tech stack:** PySide6, QPainter, Qt stylesheets, bundled TTF fonts loaded via `QFontDatabase.addApplicationFont`.

**Design source (READ THESE when implementing):**
- `docs/superpowers/design-source/dict.html` — root, palette CSS variables, fonts
- `docs/superpowers/design-source/src/app.jsx` — overall layout, accent map, corner brackets
- `docs/superpowers/design-source/src/header.jsx` — header with brand + hotkey slab + status pill + window controls
- `docs/superpowers/design-source/src/record-widget.jsx` — canvas widget (all geometry math)
- `docs/superpowers/design-source/src/status-strip.jsx` — compact ring + level meter helpers
- `docs/superpowers/design-source/src/transcript.jsx` — streaming transcript panel
- `docs/superpowers/design-source/src/history.jsx` — `CompactHistory` (the small variant we want)
- `docs/superpowers/design-source/src/settings.jsx` — settings dialog with sections + mic gain log slider

**Out of scope** (the design has them as "tweaks" / demo affordances only):
- Accent picker UI (we hard-code cyan)
- Ring density picker (we hard-code 54)
- Wave-strip toggle (we always show)
- Grid overlay (debug only)
- Auto-fading-fresh-chunk animation on partials (Qt label can't do background transition cleanly without QPropertyAnimation; we just append plain text and let the existing accumulator pattern continue — visual polish only, not behavior)

---

## File map

**Modify:**
- `dict/qt_window.py` — palette, layout, fonts, RecordWidget paint
- `dict/qt_settings.py` — section-based layout with mic gain log slider
- `dict/__main__.py` — register bundled fonts at startup

**Create:**
- `assets/fonts/Rajdhani-Regular.ttf`, `Rajdhani-Medium.ttf`, `Rajdhani-SemiBold.ttf`, `Rajdhani-Bold.ttf` — downloaded from Google Fonts
- `assets/fonts/JetBrainsMono-Light.ttf`, `JetBrainsMono-Regular.ttf`, `JetBrainsMono-Medium.ttf`, `JetBrainsMono-SemiBold.ttf` — downloaded from Google Fonts
- `dict/qt_design.py` — palette constants + font names + helper paint utilities (corner brackets, dashed circles, ticks)
- `dict/qt_widgets/__init__.py`, `transcript_panel.py`, `compact_history.py`, `status_strip.py`, `cta_bar.py` — extracted widget modules

**Update:**
- `dict.spec` — include `assets/fonts/*.ttf` in datas

---

## Task 1: Bundle fonts + load at startup

**Files:**
- Create: `assets/fonts/*.ttf` (8 files: 4 Rajdhani + 4 JetBrains Mono)
- Modify: `dict/__main__.py` — register fonts before constructing widgets
- Modify: `dict/qt_design.py` — new file exporting `FONT_RAJDHANI` and `FONT_MONO` constants
- Modify: `dict.spec` — include fonts dir

- [ ] **Step 1: Download Rajdhani TTFs from Google Fonts**

```bash
cd assets && mkdir -p fonts && cd fonts
for w in Regular Medium SemiBold Bold; do
  curl -fsSLO "https://github.com/google/fonts/raw/main/ofl/rajdhani/Rajdhani-${w}.ttf"
done
ls -la
```

Expected: 4 TTFs ~50–80 KB each. If curl fails (corporate proxy), download manually from https://fonts.google.com/specimen/Rajdhani and drop the files in `assets/fonts/`.

- [ ] **Step 2: Download JetBrains Mono TTFs**

```bash
cd assets/fonts
for w in Light Regular Medium SemiBold; do
  curl -fsSLO "https://github.com/JetBrains/JetBrainsMono/raw/master/fonts/ttf/JetBrainsMono-${w}.ttf"
done
ls -la
```

Expected: 4 TTFs.

- [ ] **Step 3: Create `dict/qt_design.py`**

```python
"""Centralized design tokens for the HUD: palette, fonts, paint helpers.

Mirrors the CSS variables in docs/superpowers/design-source/dict.html.
Keep in sync with the JSX inline styles — when the design changes, update
this file first; widgets read from here.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontDatabase, QPainter, QPen

# ---- Palette (oklab/hex equivalents from dict.html :root) -----------------

BG          = QColor("#03040a")
SURFACE_0   = QColor("#070a14")
SURFACE_1   = QColor("#0a0e1a")
SURFACE_2   = QColor("#0d1220")

LINE_DIM    = QColor(138, 149, 172, int(0.12 * 255))
LINE_MID    = QColor(138, 149, 172, int(0.22 * 255))
LINE_HI     = QColor(205, 215, 235, int(0.45 * 255))

TEXT_HI     = QColor("#e6edf7")
TEXT_MID    = QColor("#8a95ac")
TEXT_DIM    = QColor("#4a5268")

CYAN        = QColor("#7be4ff")
CYAN_DEEP   = QColor("#2ea8c9")
CYAN_INK    = QColor(123, 228, 255, int(0.45 * 255))
CYAN_DIM    = QColor(123, 228, 255, int(0.18 * 255))

AMBER       = QColor("#ffb340")
AMBER_DEEP  = QColor("#c47a14")
AMBER_INK   = QColor(255, 179, 64, int(0.45 * 255))
AMBER_DIM   = QColor(255, 179, 64, int(0.18 * 255))

CRIMSON     = QColor("#ff4757")
CRIMSON_DEEP= QColor("#b4202e")
CRIMSON_INK = QColor(255, 71, 87, int(0.45 * 255))
CRIMSON_DIM = QColor(255, 71, 87, int(0.18 * 255))

VIOLET      = QColor("#c7a8ff")
VIOLET_DEEP = QColor("#7a4fd1")
GREEN       = QColor("#6bffb3")
GREEN_DEEP  = QColor("#1fa36a")

# Hard-coded accent for this build (the design exposes a picker; we don't).
ACCENT      = CYAN
ACCENT_DEEP = CYAN_DEEP
ACCENT_INK  = CYAN_INK
ACCENT_DIM  = CYAN_DIM


def state_color(state: str) -> QColor:
    """Map a controller-state string to the headline color used by widgets,
    matching app.jsx::stateColor."""
    if state in ("recording", "rec"):
        return CRIMSON
    if state in ("busy", "transcribing", "decoding"):
        return AMBER
    return ACCENT


def state_color_ink(state: str) -> QColor:
    if state in ("recording", "rec"):
        return CRIMSON_INK
    if state in ("busy", "transcribing", "decoding"):
        return AMBER_INK
    return ACCENT_INK


# ---- Font registration ----------------------------------------------------

FONT_RAJDHANI = "Rajdhani"      # display
FONT_MONO     = "JetBrains Mono"  # mono + tabular numerics


def load_application_fonts(fonts_dir) -> None:
    """Register bundled TTF fonts so they're available everywhere via
    QFont('Rajdhani') / QFont('JetBrains Mono'). Idempotent — calling twice
    is a no-op past the first registration."""
    from pathlib import Path
    fonts_path = Path(fonts_dir)
    if not fonts_path.exists():
        return
    for ttf in sorted(fonts_path.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(ttf))


# ---- Paint helpers (used by RecordWidget, TranscriptPanel, etc.) ----------

def paint_corner_brackets(p: QPainter, rect, color: QColor, size: int = 12, width: float = 1.5) -> None:
    """Draw 4 small L-shape brackets in each corner of `rect`. Mirrors
    `app.jsx::CornerBrackets` (offset by -1 in the JSX to sit on the border)."""
    pen = QPen(color)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    s = size
    # Top-left
    p.drawLine(x, y, x + s, y)
    p.drawLine(x, y, x, y + s)
    # Top-right
    p.drawLine(x + w, y, x + w - s, y)
    p.drawLine(x + w, y, x + w, y + s)
    # Bottom-right
    p.drawLine(x + w, y + h, x + w - s, y + h)
    p.drawLine(x + w, y + h, x + w, y + h - s)
    # Bottom-left
    p.drawLine(x, y + h, x + s, y + h)
    p.drawLine(x, y + h, x, y + h - s)


def font_display(size: int, weight: int = QFont.Bold, letter_spacing: float = 0.0) -> QFont:
    f = QFont(FONT_RAJDHANI)
    f.setPointSize(size)
    f.setWeight(weight)
    if letter_spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return f


def font_mono(size: int, weight: int = QFont.Normal, letter_spacing: float = 0.0) -> QFont:
    f = QFont(FONT_MONO)
    f.setPointSize(size)
    f.setWeight(weight)
    f.setStyleHint(QFont.Monospace)
    if letter_spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, letter_spacing)
    return f
```

- [ ] **Step 4: Call `load_application_fonts` from `__main__.py`**

In `dict/__main__.py`, just after `app = QApplication(sys.argv)`:

```python
        from dict.qt_design import load_application_fonts
        load_application_fonts(config.ASSETS_DIR / "fonts")
```

(`config.ASSETS_DIR` is already imported.)

- [ ] **Step 5: Update `dict.spec` datas**

In `dict.spec`, in the `datas=[...]` block, add:

```python
        ("assets/fonts/*.ttf", "assets/fonts"),
```

- [ ] **Step 6: Sanity check**

Launch the app and grep the log for font load:

```bash
.venv/Scripts/python.exe -m dict &
sleep 3
.venv/Scripts/python.exe -c "from PySide6.QtGui import QFontDatabase; from PySide6.QtWidgets import QApplication; import sys; a = QApplication(sys.argv); from dict.qt_design import load_application_fonts; from dict import config; load_application_fonts(config.ASSETS_DIR / 'fonts'); print('Rajdhani' in QFontDatabase.families()); print('JetBrains Mono' in QFontDatabase.families())"
```

Expected: `True\nTrue`.

- [ ] **Step 7: Commit**

```bash
git add assets/fonts/ dict/qt_design.py dict/__main__.py dict.spec
git commit -m "feat(design): bundle Rajdhani + JetBrains Mono fonts + qt_design tokens"
```

---

## Task 2: Rewrite `RecordWidget` paint to match design

**Files:**
- Modify: `dict/qt_window.py` (the `RecordWidget` class)

Read `docs/superpowers/design-source/src/record-widget.jsx` first. The canvas paint code maps directly to a QPainter implementation. The widget is 200×200 displayed (sized parameter), internal coordinate system is 360×360 (so use `painter.scale(200/360, 200/360)` then paint in 360-space).

**Layers (in order, all inside one paintEvent):**

1. **Outer reticle frame** — 4 cardinal tick marks at N/E/S/W reaching from r=160 to r=174.
2. **Corner brackets** — 4 small L-shape brackets at corners of a `BR` square (BR = R_OUT + 8 = 178), inset 68% from center.
3. **3 concentric dotted rings** — radii 165, 140, 120; pen `LINE_DIM`, dash pattern `[1, 3]`.
4. **Degree ticks every 15°** on inner ring (r=120). Major (every 45°) extends 6 px inward; minor 3 px. Pen color rgba(138,149,172,0.35).
5. **Radar sweep (idle only)** — conic gradient simulating a sweep, animated by an internal time counter (rotates 0.6 rad/s).
6. **Decoding spinner (decoding only)** — 0.8π arc at r=110, animates by time, plus a fading tail behind it.
7. **VU ring** — 54 segments between r=84 and r=110 (height varies with envelope). Use a `vu_envelope: list[float]` updated on each `_tick` from the recorded level (or smoothed-randomly when in standalone preview mode).
8. **Peak/clip chevron (rec only)** — triangle pointing inward at the peak segment, white if v>0.92 else accent.
9. **Inner core ring** — r=58. Pen width 2 in rec, 1.25 otherwise.
10. **Pulse ring (rec only)** — sinusoidal expand 6→12 px outside core.
11. **Core glyph** — play triangle in idle, white square in rec, three pulsing dots in decoding.
12. **Center crosshair** — small `+` marker, 6px diameter total.

The widget already has `_tick` running at ~30 fps via QTimer; refactor that loop. Color is computed via `state_color()` and `state_color_ink()` from `qt_design.py`.

- [ ] **Step 1: Replace the existing RecordWidget class body**

Read the current `dict/qt_window.py::RecordWidget` to preserve the public API (`set_state`, `set_level`, `clicked` signal, the QTimer pattern, minimum size). Then rewrite `paintEvent` and the small per-state helpers as described above.

Key sizing: change `setMinimumSize(320, 320)` → `setMinimumSize(200, 200)`. Internal coordinate space stays 360×360 — apply `painter.scale(self.width()/360, self.height()/360)` at the top of paintEvent (after setting render hints).

Class attribute changes:
- `VU_SEGMENTS = 54` (unchanged)
- `CORE_RADIUS = 58` (was 54)
- `RING_INNER = 84` (was 86)
- `RING_OUTER = 110` (was 140)
- Add: `R_OUT = 170` for the cardinal frame ring
- Add: `_sweep_phase = 0.0` (idle radar sweep)

Replace all hard-coded colors (`CYAN`, `RED`, `YELLOW`, etc.) with `state_color(self._state)` / `state_color_ink(self._state)` from `qt_design`.

- [ ] **Step 2: Add a `_paint_radar_sweep` helper**

```python
    def _paint_radar_sweep(self, p: QPainter, cx: float, cy: float, col_ink: QColor) -> None:
        """Conic-gradient sweep for the idle state (faux radar)."""
        from PySide6.QtGui import QConicalGradient
        sweep_a = (self._sweep_phase * 0.6) % (2 * math.pi)
        # Conic gradient starts at the rotated angle (Qt uses degrees, 0 = 3 o'clock)
        grad = QConicalGradient(cx, cy, -math.degrees(sweep_a) + 90)
        grad.setColorAt(0.0, col_ink)
        grad.setColorAt(0.15, QColor(0, 0, 0, 0))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.NoPen)
        # Annulus 72..118 — paint disk minus inner disk using composition
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), 118, 118)
        inner = QPainterPath()
        inner.addEllipse(QPointF(cx, cy), 72, 72)
        path = path.subtracted(inner)
        p.drawPath(path)
```

- [ ] **Step 3: Update `_tick` to drive the sweep phase**

```python
        self._sweep_phase += 0.06  # ~1.8 rad/s at 30 fps
```

- [ ] **Step 4: Run the app and visually verify**

```bash
.venv/Scripts/pythonw.exe -m dict
```

Then manually: press hotkey → see crimson rec state, release → see amber decoding briefly, then back to cyan idle with radar sweep.

- [ ] **Step 5: Commit**

```bash
git add dict/qt_window.py
git commit -m "feat(widget): redesign RecordWidget — concentric arcs, radar sweep, peak chevron"
```

---

## Task 3: Rewrite window layout (capture-zone + CTA bar + transcript panel)

**Files:**
- Modify: `dict/qt_window.py` — `_build_ui`, replace `_build_record`/`_build_status`/`_build_partials`/`_build_history` order with the new structure
- Create: `dict/qt_widgets/__init__.py` (empty marker)
- Create: `dict/qt_widgets/status_strip.py` — vertical metrics column (STATE/ELAPSED/PEAK/LEVEL)
- Create: `dict/qt_widgets/cta_bar.py` — `PRESS [F9] TO START DICTATION`
- Create: `dict/qt_widgets/transcript_panel.py` — bordered panel with header, scroll body, cadence footer
- Create: `dict/qt_widgets/compact_history.py` — collapsible 140px history

Read `docs/superpowers/design-source/src/app.jsx` for the full layout. Layout sequence inside the panel:

1. **Header** (existing `_build_header`, restyled in Task 4) — height ~44px
2. **Capture zone** — `QHBoxLayout`: RecordWidget (200×200) on the left, StatusStrip (1fr) on the right. Padding 12/18/8/18. Bottom border `LINE_DIM`.
3. **CTA bar** — 1-line `PRESS [F9] TO START DICTATION`. Centered, mono font 10pt, dim text. Hotkey slab uses clipped polygon path. Bottom border `LINE_DIM`.
4. **Transcript panel** — flex:1, min-height:0. Margins 0/16. Bordered `LINE_MID`. Contains header, scroll body, cadence footer.
5. **Compact history** — fixed height 140 (or 32 if collapsed), bottom of panel.

The window background is `SURFACE_1`. Outer page is a `radial-gradient` — Qt: paint in the outer widget's `paintEvent`.

### Subtask 3a: StatusStrip widget

`dict/qt_widgets/status_strip.py`:

```python
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
        font = QFont(FONT_RAJDHANI); font.setPointSize(13); font.setWeight(QFont.Bold)
        font.setLetterSpacing(QFont.PercentageSpacing, 122)
        self._state_value.setFont(font)
        self._state_value.setStyleSheet(f"color: {state_color('idle').name()};")

        self._elapsed_label_l = self._label_dim("ELAPSED")
        self._elapsed_value = QLabel("00:00.0")
        m = QFont(FONT_MONO); m.setPointSize(10)
        self._elapsed_value.setFont(m)
        self._elapsed_value.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._peak_label_l = self._label_dim("PEAK")
        self._peak_value = QLabel("-∞ dB")
        self._peak_value.setFont(m)
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
            lbl.setFixedWidth(56)
            row.addWidget(lbl, 0)
            row.addWidget(val, 1, Qt.AlignLeft | Qt.AlignVCenter)
            v.addLayout(row)
            v.addWidget(self._divider())

        # Drop the final divider
        v.takeAt(v.count() - 1)

    def _label_dim(self, text: str) -> QLabel:
        lbl = QLabel(text)
        f = QFont(FONT_MONO); f.setPointSize(7)
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
```

### Subtask 3b: CTABar

`dict/qt_widgets/cta_bar.py`:

```python
"""Single line: PRESS [hotkey] TO START DICTATION.
Hotkey badge uses a clipped polygon (slab-style)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from dict.qt_design import (
    LINE_MID, TEXT_DIM, TEXT_HI,
    FONT_MONO,
    state_color,
)


class _HotkeyBadge(QLabel):
    """Slab badge (clipped corners) showing the hotkey."""
    def __init__(self, label: str = "F9", parent=None) -> None:
        super().__init__(label.upper(), parent)
        f = QFont(FONT_MONO); f.setPointSize(8); f.setWeight(QFont.DemiBold)
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

        f_mono_sm = QFont(FONT_MONO); f_mono_sm.setPointSize(7)
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

        self.setStyleSheet(f"QWidget {{ border-bottom: 1px solid {LINE_DIM.name(QColor.HexArgb)}; }}")

    def set_state(self, state: str) -> None:
        self._badge.set_state(state)
        self._post.setText(
            "TO STOP & TRANSCRIBE" if state in ("recording", "rec")
            else "TO CANCEL DECODING" if state in ("busy", "transcribing", "decoding")
            else "TO START DICTATION"
        )

    def set_hotkey(self, label: str) -> None:
        self._badge.set_label(label)
```

### Subtask 3c: TranscriptPanel — replaces partials label

`dict/qt_widgets/transcript_panel.py`:

```python
"""Streaming transcript panel — bordered + corner brackets + scrollable body
+ cadence footer. Replaces the previous QLabel partials box.

Mirrors transcript.jsx. Behaviors:
  - append_partial(text)  — appends a chunk; auto-scrolls to bottom unless
    user has scrolled up (sticky-to-bottom behavior)
  - clear()               — resets to empty placeholder
  - set_state(state)      — drives header label, footer message, cadence
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from dict.qt_design import (
    LINE_DIM, LINE_MID, SURFACE_2, TEXT_DIM, TEXT_HI, TEXT_MID,
    FONT_MONO, FONT_RAJDHANI,
    paint_corner_brackets, state_color,
)


class _ActivityDots(QWidget):
    """3 dots animating in a row, mirroring transcript.jsx::ActivityDots."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 6)
        self._phase = 0.0
        self._state = "idle"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(80)

    def set_state(self, state: str) -> None:
        self._state = state
        self.setVisible(state != "idle")

    def _tick(self) -> None:
        self._phase += 0.18
        self.update()

    def paintEvent(self, _ev) -> None:
        if self._state == "idle":
            return
        import math
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = state_color(self._state)
        for i in range(3):
            phase = self._phase - i * 0.6
            v = (math.sin(phase) + 1) / 2
            alpha = int(64 + 191 * v)
            c = QColor(col); c.setAlpha(alpha)
            p.setBrush(c); p.setPen(Qt.NoPen)
            x = 3 + i * 6
            r = 1.6 + 0.7 * v
            p.drawEllipse(int(x - r), int(self.height()/2 - r), int(r * 2), int(r * 2))


class _CadenceTrack(QWidget):
    """24-cell strip showing chunk-arrival history. Filled cell = chunk arrived
    in that ~500ms window."""
    CELLS = 24
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(8)
        self.setMinimumWidth(80)
        self._bars = [0] * self.CELLS
        self._state = "idle"
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._auto_tick)
        self._tick_timer.start(500)

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "idle":
            self._bars = [0] * self.CELLS
            self.update()

    def mark(self) -> None:
        """Call when a chunk arrives. Shifts and adds a 1 at the end."""
        self._bars = self._bars[1:] + [1]
        self.update()

    def _auto_tick(self) -> None:
        # When idle, decay
        if self._state == "idle":
            return
        # Otherwise the controller will call mark() explicitly; nothing here.

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        col = state_color(self._state)
        dim = QColor(138, 149, 172, 46)
        cell_w = 3
        gap = 2
        for i, b in enumerate(self._bars):
            x = i * (cell_w + gap)
            c = col if b else dim
            if b:
                age_alpha = int(102 + (i / self.CELLS) * 153)
                c = QColor(col); c.setAlpha(age_alpha)
            p.fillRect(x, 1, cell_w, 6, c)


class _TranscriptBody(QTextEdit):
    """Read-only scrollable text body. Sticky-to-bottom: auto-scroll when
    user is at the bottom; preserve scroll position when they scrolled up."""
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setStyleSheet(f"background-color: {SURFACE_2.name()};")
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {SURFACE_2.name()};
                border: none;
                color: {TEXT_MID.name()};
                padding: 12px 14px;
                font-family: '{FONT_MONO}';
                font-size: 11pt;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(138,149,172,90);
                min-height: 24px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(138,149,172,140);
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    def append_chunk(self, text: str) -> None:
        bar = self.verticalScrollBar()
        was_at_bottom = (bar.value() >= bar.maximum() - 4)
        cur = self.toPlainText()
        joined = (cur + " " + text).strip() if cur else text
        self.setPlainText(joined)
        if was_at_bottom:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))


class TranscriptPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._build()

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setStyleSheet(f"""
            QWidget#transcriptFrame {{
                background-color: {SURFACE_2.name()};
                border: 1px solid {LINE_MID.name(QColor.HexArgb)};
            }}
        """)
        frame = QWidget()
        frame.setObjectName("transcriptFrame")
        vh = QVBoxLayout(frame)
        vh.setContentsMargins(0, 0, 0, 0)
        vh.setSpacing(0)

        # Header: TX/  LIVE TRANSCRIPT  ........  • • •  N WORDS
        header = QWidget()
        header.setStyleSheet(f"background-color: rgba(0,0,0,45); border-bottom: 1px solid {LINE_DIM.name(QColor.HexArgb)};")
        h = QHBoxLayout(header)
        h.setContentsMargins(12, 7, 12, 7)
        h.setSpacing(10)

        prefix = QLabel("TX/")
        f_pref = QFont(FONT_MONO); f_pref.setPointSize(7)
        f_pref.setLetterSpacing(QFont.PercentageSpacing, 112)
        prefix.setFont(f_pref); prefix.setStyleSheet(f"color: {TEXT_DIM.name()};")

        self._header_label = QLabel("LIVE TRANSCRIPT")
        f_hdr = QFont(FONT_RAJDHANI); f_hdr.setPointSize(8); f_hdr.setWeight(QFont.DemiBold)
        f_hdr.setLetterSpacing(QFont.PercentageSpacing, 122)
        self._header_label.setFont(f_hdr); self._header_label.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._activity = _ActivityDots()
        self._word_count = QLabel("0 WORDS")
        f_wc = QFont(FONT_MONO); f_wc.setPointSize(7)
        self._word_count.setFont(f_wc); self._word_count.setStyleSheet(f"color: {TEXT_MID.name()};")

        h.addWidget(prefix); h.addWidget(self._header_label); h.addStretch(1)
        h.addWidget(self._activity); h.addWidget(self._word_count)

        vh.addWidget(header)

        # Body
        self._body = _TranscriptBody()
        vh.addWidget(self._body, 1)

        # Empty-state overlay label
        self._empty_label = QLabel("waiting for audio…", self._body)
        ef = QFont(FONT_RAJDHANI); ef.setPointSize(10); ef.setItalic(True)
        ef.setLetterSpacing(QFont.PercentageSpacing, 106)
        self._empty_label.setFont(ef)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {TEXT_DIM.name()}; background: transparent;")

        # Footer with cadence + label
        footer = QWidget()
        footer.setStyleSheet(f"border-top: 1px solid {LINE_DIM.name(QColor.HexArgb)};")
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(12, 5, 12, 5)
        fh.setSpacing(10)
        self._cadence = _CadenceTrack()
        self._footer_text = QLabel("IDLE")
        f_ft = QFont(FONT_MONO); f_ft.setPointSize(7)
        f_ft.setLetterSpacing(QFont.PercentageSpacing, 110)
        self._footer_text.setFont(f_ft); self._footer_text.setStyleSheet(f"color: {TEXT_DIM.name()};")
        fh.addWidget(self._cadence); fh.addStretch(1); fh.addWidget(self._footer_text)
        vh.addWidget(footer)

        outer.addWidget(frame, 1)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._empty_label.setGeometry(self._body.rect())

    def paintEvent(self, ev) -> None:
        super().paintEvent(ev)
        # Draw faint corner brackets in the panel corners
        p = QPainter(self)
        col = state_color(self._state); col.setAlpha(150)
        paint_corner_brackets(p, self.rect().adjusted(0, 0, -1, -1), col, size=8, width=1.2)

    # ---- public API ----

    def set_state(self, state: str) -> None:
        self._state = state
        self._activity.set_state(state)
        self._cadence.set_state(state)
        if state in ("recording", "rec"):
            self._header_label.setText("LIVE TRANSCRIPT")
            self._footer_text.setText("STREAMING · 500MS")
        elif state in ("busy", "transcribing", "decoding"):
            self._header_label.setText("TRANSCRIBING")
            self._footer_text.setText("FINALIZING · 700MS")
        else:
            self._header_label.setText("LIVE TRANSCRIPT")
            self._footer_text.setText("IDLE")
        self.update()

    def append_partial(self, text: str) -> None:
        self._body.append_chunk(text)
        self._cadence.mark()
        self._empty_label.setVisible(False)
        # Update word count
        wc = len(self._body.toPlainText().split())
        self._word_count.setText(f"{wc} WORDS")

    def clear(self) -> None:
        self._body.setPlainText("")
        self._empty_label.setVisible(True)
        self._word_count.setText("0 WORDS")
        self._cadence.set_state("idle")
```

### Subtask 3d: CompactHistory

`dict/qt_widgets/compact_history.py`:

```python
"""Compact history strip — 140px expanded, 32px collapsed. Click header
to toggle. 3-4 rows visible inside scroll. Mirrors history.jsx::CompactHistory."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from dict.history import History
from dict.qt_design import (
    LINE_DIM, SURFACE_0, TEXT_DIM, TEXT_HI, TEXT_MID,
    FONT_MONO, FONT_RAJDHANI,
)


class CompactHistory(QWidget):
    item_copied = Signal(str)
    EXPANDED_H = 140
    COLLAPSED_H = 32

    def __init__(self, history: History, on_copy, parent=None) -> None:
        super().__init__(parent)
        self._history = history
        self._on_copy = on_copy
        self._collapsed = False
        self._build()

    def _build(self) -> None:
        self.setFixedHeight(self.EXPANDED_H)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.setStyleSheet(f"""
            QWidget#hHeader {{
                background-color: {SURFACE_0.name()};
                border-bottom: 1px solid {LINE_DIM.name(QColor.HexArgb)};
            }}
            QListWidget {{
                background-color: {SURFACE_0.name()};
                border: none;
                font-family: '{FONT_MONO}';
                font-size: 9pt;
            }}
            QListWidget::item {{
                padding: 4px 14px;
                border-left: 2px solid transparent;
                color: {TEXT_MID.name()};
            }}
            QListWidget::item:hover {{
                background-color: rgba(138,149,172,10);
                color: #cfd6e4;
                border-left: 2px solid rgba(138,149,172,89);
            }}
            QListWidget::item:selected {{
                background: rgba(123,228,255,30);
                color: {TEXT_HI.name()};
                border-left: 2px solid #7be4ff;
            }}
        """)

        # Header
        hdr = QWidget(); hdr.setObjectName("hHeader")
        hh = QHBoxLayout(hdr); hh.setContentsMargins(14, 8, 14, 6); hh.setSpacing(8)
        title = QLabel("HISTORY")
        ft = QFont(FONT_RAJDHANI); ft.setPointSize(8); ft.setWeight(QFont.DemiBold)
        ft.setLetterSpacing(QFont.PercentageSpacing, 122)
        title.setFont(ft); title.setStyleSheet(f"color: {TEXT_HI.name()};")

        count = QLabel(f"· {len(self._history.items())} ENTRIES")
        fc = QFont(FONT_MONO); fc.setPointSize(7); fc.setLetterSpacing(QFont.PercentageSpacing, 108)
        count.setFont(fc); count.setStyleSheet(f"color: {TEXT_DIM.name()};")

        self._toggle_btn = QPushButton("▾")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"color: {TEXT_MID.name()}; background: transparent; border: none; font-size: 10pt;")
        self._toggle_btn.setFixedWidth(20)
        self._toggle_btn.clicked.connect(self.toggle_collapsed)

        engine_lbl = QLabel("WHISPER L-V3")
        engine_lbl.setFont(fc); engine_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")

        hh.addWidget(title); hh.addWidget(count); hh.addStretch(1)
        hh.addWidget(engine_lbl); hh.addWidget(self._toggle_btn)

        # Make whole header clickable
        hdr.mousePressEvent = lambda ev: self.toggle_collapsed()
        hdr.setCursor(Qt.PointingHandCursor)

        v.addWidget(hdr)

        # List
        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_clicked)
        v.addWidget(self._list, 1)

        self.refresh()

    def toggle_collapsed(self) -> None:
        self._collapsed = not self._collapsed
        self.setFixedHeight(self.COLLAPSED_H if self._collapsed else self.EXPANDED_H)
        self._toggle_btn.setText("▸" if self._collapsed else "▾")
        self._list.setVisible(not self._collapsed)

    def refresh(self) -> None:
        self._list.clear()
        for i, entry in enumerate(self._history.items()):
            ts = entry.timestamp.strftime("%H:%M:%S")
            short = entry.text[:60] + ("…" if len(entry.text) > 60 else "")
            item = QListWidgetItem(f"  {i+1:02d}    {ts}    {short}")
            self._list.addItem(item)

    def _on_clicked(self, item) -> None:
        # The original text is in history entries; map by row index
        idx = self._list.row(item)
        items = self._history.items()
        if 0 <= idx < len(items):
            text = items[idx].text
            try:
                self._on_copy(text)
                self.item_copied.emit(text)
            except Exception:
                pass
```

### Subtask 3e: Wire it all into qt_window.MainWindow._build_ui

Replace the existing `_build_ui` body. Read current file first. Sequence:

```python
        # Window panel
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._panel = QWidget(self)
        self._panel.setObjectName("panel")
        # Drop shadow with state-tinted glow
        shadow = QGraphicsDropShadowEffect(self._panel)
        shadow.setBlurRadius(70)
        shadow.setColor(QColor(state_color("idle").red(), state_color("idle").green(), state_color("idle").blue(), 51))
        shadow.setOffset(0, 0)
        self._panel.setGraphicsEffect(shadow)
        self._panel_shadow = shadow
        outer.addWidget(self._panel)

        inner = QVBoxLayout(self._panel)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)

        # Header (existing; restyled in Task 4)
        inner.addLayout(self._build_header())

        # Capture zone
        cap = QWidget()
        cap.setStyleSheet(f"background-color: transparent; border-bottom: 1px solid {LINE_DIM.name(QColor.HexArgb)};")
        ch = QHBoxLayout(cap); ch.setContentsMargins(18, 12, 18, 8); ch.setSpacing(18)
        self._record_widget = RecordWidget()  # 200x200 minimum
        self._record_widget.setFixedSize(200, 200)
        self._status_strip = StatusStrip()
        ch.addWidget(self._record_widget, 0)
        ch.addWidget(self._status_strip, 1)
        inner.addWidget(cap)

        # CTA bar
        self._cta = CTABar(self._hotkey_label)
        inner.addWidget(self._cta)

        # Transcript panel
        trx_wrapper = QWidget()
        tw = QVBoxLayout(trx_wrapper)
        tw.setContentsMargins(16, 10, 16, 8)
        self._transcript_panel = TranscriptPanel()
        tw.addWidget(self._transcript_panel, 1)
        inner.addWidget(trx_wrapper, 1)

        # Compact history
        self._compact_history = CompactHistory(self._history, on_copy=self._on_copy)
        inner.addWidget(self._compact_history)
```

And update `_apply_state` to:
- call `self._record_widget.set_state(state)`
- call `self._status_strip.set_state(state)`
- call `self._cta.set_state(state)`
- call `self._transcript_panel.set_state(state)`
- update drop shadow color

Update `_apply_partial_appended` (or replace) to call `self._transcript_panel.append_partial(text)` instead of mutating the old label. Same for `_apply_partials_cleared` → `self._transcript_panel.clear()`.

Update `_apply_level` to call `self._status_strip.set_level(level)` AND `self._record_widget.set_level(level)`.

`_apply_refresh` (history) → `self._compact_history.refresh()`.

The panel background color comes from `SURFACE_1`. Add to `_apply_styles`:

```python
        #panel { background-color: SURFACE_1.name(); }
```

Drop the old history-list / partials-label / status-label styles.

- [ ] **Step 1: Create the 4 widget files** (3a, 3b, 3c, 3d) with the code above
- [ ] **Step 2: Rewrite MainWindow._build_ui and the slots**
- [ ] **Step 3: Launch, verify states render**

Manual: launch app, press hotkey twice (start+stop), see the new layout. Don't expect perfection on first try — visual iteration is expected.

- [ ] **Step 4: Commit**

```bash
git add dict/qt_widgets/ dict/qt_window.py
git commit -m "feat(ui): new HUD layout — status strip, CTA bar, transcript panel, compact history"
```

---

## Task 4: Rewrite header to match design

**Files:**
- Modify: `dict/qt_window.py` — `_build_header` + helpers

Read `docs/superpowers/design-source/src/header.jsx`. Header structure:
- Brand mark: 18×18 SVG (circle-in-circle-with-dot), tinted by state, + "DICT" text (Rajdhani, 18pt, bold, letter-spacing 0.32em)
- Hotkey slab: `HOTKEY F9`, clipped polygon, mono 7pt
- Status pill: `READY` / `REC` / `DECODING` — clipped polygon, animated dot/spinner inside
- Window controls: settings (gear), minimize (—), close (✕)

Padding 12/16/10/16, 12px gap.

The bottom 1px divider is a horizontal gradient: `transparent → LINE_MID at 10% → LINE_MID at 90% → transparent`.

Use QPainter on a custom QWidget for the status pill (clip path + animated marker), or build it from a QLabel with a paintEvent override.

- [ ] **Step 1: Replace `_build_header` (existing) with the new implementation**

Use the existing header signal hooks (`_on_open_settings`, `_minimize_btn.clicked.connect(self.hide)`, etc.). Don't break the existing API.

- [ ] **Step 2: Add `set_state(state)` to the header so it can update the brand-mark inner dot color + status pill**

Wire it from `_apply_state`: `self._header.set_state(state)`.

- [ ] **Step 3: Commit**

```bash
git add dict/qt_window.py
git commit -m "feat(ui): redesigned header — brand mark, hotkey slab, status pill, controls"
```

---

## Task 5: Redesign settings dialog

**Files:**
- Modify: `dict/qt_settings.py` — full rewrite around new sections

Read `docs/superpowers/design-source/src/settings.jsx`. The dialog:
- 496×620 max, centered modal with backdrop blur
- Corner brackets in 4 corners (accent color)
- Header: `CFG/ SETTINGS` with × close
- 3 sections:
  - **§01 AUDIO** — Input (Select), Mic Gain (custom log slider with 1× marker + CLIP marker at 3× + preview bars + live amplitude), Volume (linear slider)
  - **§02 HOTKEY** — Trigger (rebind input), Mode (toggle: push-to-talk vs tap)
  - **§03 MODEL** — Engine (Select), Language (Select)
- Footer: `ESC · CLOSE` left, `APPLY` button right

Mic gain log slider math:
```
MIN = 0.5, MAX = 5
LMIN = ln(MIN), LMAX = ln(MAX)
slider_pos -> value: exp(LMIN + pos * (LMAX - LMIN))
value -> slider_pos: (ln(value) - LMIN) / (LMAX - LMIN)
```

1× marker at `pct1x = (ln(1) - LMIN) / (LMAX - LMIN)`.
CLIP marker at `pct3x = (ln(3) - LMIN) / (LMAX - LMIN)`.

Up to CLIP marker: accent fill; past CLIP: crimson fill; thumb border: accent normally, crimson when value > 3.

PreviewBars: 28-cell horizontal bar; cell heights are a simulated envelope multiplied by gain; cells > 0.85 amplitude are crimson.

Live amplitude in the dialog: drive it from the real recorder.level callback. (Re-use the same signal the main window subscribes to.)

Add auto_paste checkbox (preserved from previous work) — fits nicely as a row in §02 HOTKEY or §01 AUDIO. Place it in §02 HOTKEY as **Auto-paste** row with a `Toggle` matching the Mode toggle.

- [ ] **Step 1: Rewrite the dialog**

This is a large rewrite — read the existing `dict/qt_settings.py` first to preserve the public API (`SettingsDialog(current, on_save, parent)`, `_save` calls `on_save(new_settings)`).

- [ ] **Step 2: Visual smoke test (manual)**

Launch app, click the gear icon. Should see the new dialog with sections, sliders, etc. Save → setting change applies.

- [ ] **Step 3: Run tests, no regressions**

```bash
.venv/Scripts/python.exe -m pytest -m "not slow"
```

- [ ] **Step 4: Commit**

```bash
git add dict/qt_settings.py
git commit -m "feat(settings): redesigned dialog — sections, mic-gain log slider, accent toggles"
```

---

## Task 6: Window outer glow + corner brackets

**Files:**
- Modify: `dict/qt_window.py`

- [ ] **Step 1: Paint corner brackets on the panel**

In `MainWindow.paintEvent`, after the existing paint (if any), use `paint_corner_brackets` from `qt_design` to add brackets on the panel rect. Color = state_color(current_state).

- [ ] **Step 2: Update drop shadow color in `_apply_state`**

```python
        col = state_color(state)
        glow = QColor(col); glow.setAlpha(60)
        self._panel_shadow.setColor(glow)
```

- [ ] **Step 3: Commit**

```bash
git add dict/qt_window.py
git commit -m "feat(ui): window-level corner brackets + state-tinted drop shadow"
```

---

## Final verification checklist

- [ ] Launch app: `.venv/Scripts/pythonw.exe -m dict`
- [ ] Window is 560×680, dark with cyan accent
- [ ] Header shows brand, HOTKEY pause (or whatever is configured), READY status pill, gear/min/close buttons
- [ ] Capture zone: 200×200 widget on left with concentric arcs + slow radar sweep; right side STATE=IDLE (cyan) / ELAPSED 00:00.0 / PEAK -∞ dB / LEVEL bar at 0
- [ ] CTA: `PRESS [pause] TO START DICTATION`
- [ ] Transcript: bordered panel saying `waiting for audio…` in italic, with cadence-empty footer
- [ ] Compact history: 140px, click header to collapse to ~32px
- [ ] Press hotkey: widget turns crimson, VU bars animate, partials accumulate live in transcript, cadence dots fill
- [ ] Stop hotkey: brief amber decoding, then back to idle; auto-paste fires into focused app
- [ ] Settings: gear opens new dialog with sections + log gain slider + CLIP marker
- [ ] All tests still pass: `.venv/Scripts/python.exe -m pytest -m "not slow"`

If any visual is off, iterate on the relevant Task — visual fidelity is acceptable on second pass.

---

## Out of scope (do not implement)

- Accent picker UI (we hard-code cyan)
- Ring density picker
- Wave-strip toggle (just always show)
- Background grid overlay
- Fresh-chunk background-color fade animation (Qt label transitions are complicated; we just append text)
- Theme switching at runtime
