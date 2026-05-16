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
    user is at the bottom; preserve scroll position when they scrolled up.

    Stores a list of chunks (each with a birth-time so we can fade the
    fresh-chunk highlight) plus a single in-flight preview line.
    Rendered via setHtml() so chunks at different ages get different colors.
    """
    FRESH_MS = 380.0   # how long a freshly-committed chunk stays highlighted

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
                font-size: 12pt;  /* design: 12–13px body */
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
        # Each chunk: {"text": str, "born_ms": float (monotonic*1000)}
        self._chunks: list[dict] = []
        self._preview_text: str = ""

    @staticmethod
    def _esc(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    @staticmethod
    def _levenshtein_lite(a: str, b: str) -> int:
        """Cheap edit-distance proxy: differing chars at aligned positions +
        length diff. Used to skip preview repaints for tiny jitter."""
        if not a or not b:
            return abs(len(a) - len(b))
        n = min(len(a), len(b))
        diffs = sum(1 for i in range(n) if a[i] != b[i])
        return diffs + abs(len(a) - len(b))

    def _render(self) -> None:
        from time import monotonic
        bar = self.verticalScrollBar()
        was_at_bottom = (bar.value() >= bar.maximum() - 4)
        now_ms = monotonic() * 1000.0
        n = len(self._chunks)
        parts: list[str] = []
        for idx, ch in enumerate(self._chunks):
            age = now_ms - ch["born_ms"]
            is_fresh = age < self.FRESH_MS
            from_end = n - 1 - idx
            txt = self._esc(ch["text"])
            if is_fresh:
                # White on cyan-tinted background, mirrors design's fresh-chunk pop.
                parts.append(
                    f'<span style="background:rgba(123,228,255,0.22);'
                    f' color:#ffffff; padding:0 3px;">{txt}</span>'
                )
            elif from_end < 3:
                # Last 3 chunks: bright text
                parts.append(f'<span style="color:{TEXT_HI.name()};">{txt}</span>')
            else:
                parts.append(f'<span style="color:{TEXT_MID.name()};">{txt}</span>')
        committed_html = " ".join(parts)
        preview_html = ""
        if self._preview_text:
            sep = " " if committed_html else ""
            preview_html = (
                f"{sep}<span style='color:{TEXT_DIM.name()}; font-style: italic;'>"
                f"… {self._esc(self._preview_text)}</span>"
            )
        body = (
            f"<div style='color:{TEXT_MID.name()}; line-height:1.65;'>"
            f"{committed_html}{preview_html}"
            f"</div>"
        )
        self.setHtml(body)
        if was_at_bottom:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def append_chunk(self, text: str) -> None:
        from time import monotonic
        text = (text or "").strip()
        if not text:
            return
        self._chunks.append({"text": text, "born_ms": monotonic() * 1000.0})
        # A real commit invalidates any preview we might be showing.
        self._preview_text = ""
        self._render()
        # Schedule a repaint at ~FRESH_MS + tiny buffer so the fresh-chunk
        # highlight fades to TEXT_HI on time.
        QTimer.singleShot(int(self.FRESH_MS) + 40, self._render)

    def set_preview(self, text: str) -> None:
        text = text or ""
        old = self._preview_text or ""
        # Skip repaint if essentially unchanged — kills the "text shifts every
        # 1.5s" flicker. Only repaint when the delta is meaningful.
        if text == old:
            return
        # Skip only on truly identical text — user wants speed over flicker
        # mitigation. The change-required threshold is now ~zero (any diff
        # repaints).
        self._preview_text = text
        self._render()

    def clear_all(self) -> None:
        self._chunks = []
        self._preview_text = ""
        self.setHtml("")

    def plain_committed(self) -> str:
        return " ".join(ch["text"] for ch in self._chunks).strip()


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
        f_pref = QFont(FONT_MONO); f_pref.setPointSize(8)  # design min 8pt
        f_pref.setStyleHint(QFont.Monospace)
        f_pref.setLetterSpacing(QFont.PercentageSpacing, 112)
        prefix.setFont(f_pref); prefix.setStyleSheet(f"color: {TEXT_DIM.name()};")

        self._header_label = QLabel("LIVE TRANSCRIPT")
        # Inner panel label: Rajdhani SemiBold 9pt
        f_hdr = QFont(FONT_RAJDHANI); f_hdr.setPointSize(9); f_hdr.setWeight(QFont.DemiBold)
        f_hdr.setLetterSpacing(QFont.PercentageSpacing, 122)
        self._header_label.setFont(f_hdr); self._header_label.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._activity = _ActivityDots()
        self._word_count = QLabel("0 WORDS")
        f_wc = QFont(FONT_MONO); f_wc.setPointSize(8)  # design min 8pt
        f_wc.setStyleHint(QFont.Monospace)
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
        self._empty_label.setVisible(True)
        # Position immediately so it's centred even before the first resizeEvent
        self._empty_label.setGeometry(self._body.rect())

        # Footer with cadence + label
        footer = QWidget()
        footer.setStyleSheet(f"border-top: 1px solid {LINE_DIM.name(QColor.HexArgb)};")
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(12, 5, 12, 5)
        fh.setSpacing(10)
        self._cadence = _CadenceTrack()
        self._footer_text = QLabel("IDLE")
        f_ft = QFont(FONT_MONO); f_ft.setPointSize(8)  # design min 8pt
        f_ft.setStyleHint(QFont.Monospace)
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
        # Update word count from committed text only (preview is in-flight)
        wc = len(self._body.plain_committed().split())
        self._word_count.setText(f"{wc} WORDS")

    def set_preview(self, text: str) -> None:
        """Show an in-flight preview line (dim italic) after the committed
        text. Replaces any previous preview. Cleared automatically when
        append_partial commits a real chunk."""
        self._body.set_preview(text)
        if text:
            self._empty_label.setVisible(False)

    def clear(self) -> None:
        self._body.clear_all()
        self._empty_label.setVisible(True)
        self._word_count.setText("0 WORDS")
        self._cadence.set_state("idle")
