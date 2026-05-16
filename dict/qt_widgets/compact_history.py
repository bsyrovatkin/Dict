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
                font-size: 10pt;  /* design: body 12–13px, list rows can be 10–11pt */
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
        # Inner label: Rajdhani SemiBold 9pt
        ft = QFont(FONT_RAJDHANI); ft.setPointSize(9); ft.setWeight(QFont.DemiBold)
        ft.setLetterSpacing(QFont.PercentageSpacing, 122)
        title.setFont(ft); title.setStyleSheet(f"color: {TEXT_HI.name()};")

        self._count_label = QLabel(f"· {len(self._history.items())} ENTRIES")
        fc = QFont(FONT_MONO); fc.setPointSize(8)  # design min 8pt
        fc.setStyleHint(QFont.Monospace)
        fc.setLetterSpacing(QFont.PercentageSpacing, 108)
        self._count_label.setFont(fc); self._count_label.setStyleSheet(f"color: {TEXT_DIM.name()};")

        self._toggle_btn = QPushButton("▾")
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setCursor(Qt.PointingHandCursor)
        self._toggle_btn.setStyleSheet(f"color: {TEXT_MID.name()}; background: transparent; border: none; font-size: 10pt;")
        self._toggle_btn.setFixedWidth(20)
        self._toggle_btn.clicked.connect(self.toggle_collapsed)

        engine_lbl = QLabel("WHISPER L-V3")
        engine_lbl.setFont(fc); engine_lbl.setStyleSheet(f"color: {TEXT_DIM.name()};")

        hh.addWidget(title); hh.addWidget(self._count_label); hh.addStretch(1)
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
        # Keep count label in sync
        if hasattr(self, "_count_label"):
            self._count_label.setText(f"· {len(self._history.items())} ENTRIES")

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
