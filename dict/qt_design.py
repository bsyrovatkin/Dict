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

FONT_RAJDHANI = "Rajdhani"       # display
FONT_MONO     = "JetBrains Mono"  # mono + tabular numerics


def load_application_fonts(fonts_dir) -> None:
    """Register bundled TTF fonts so they're available everywhere via
    QFont('Rajdhani') / QFont('JetBrains Mono'). Idempotent — calling twice
    is a no-op past the first registration.

    Logs each registered file + the resulting font families so that
    dict-debug.log shows exactly what's loaded (and surfaces missing fonts
    rather than silently falling back to a system default)."""
    import logging
    from pathlib import Path
    log = logging.getLogger("dict.fonts")
    fonts_path = Path(fonts_dir)
    if not fonts_path.exists():
        log.warning("fonts dir does not exist: %s", fonts_path)
        return
    loaded: list[tuple[str, list[str]]] = []
    for ttf in sorted(fonts_path.glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(ttf))
        if font_id < 0:
            log.warning("failed to load font: %s", ttf.name)
        else:
            families = QFontDatabase.applicationFontFamilies(font_id)
            loaded.append((ttf.name, list(families)))
    log.info(
        "loaded %d font files: %s",
        len(loaded),
        ", ".join(f"{n}->{','.join(fams)}" for n, fams in loaded),
    )
    all_families = QFontDatabase.families()
    log.info("Rajdhani present: %s", FONT_RAJDHANI in all_families)
    log.info("JetBrains Mono present: %s", FONT_MONO in all_families)


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
