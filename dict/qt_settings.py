"""PySide6 settings dialog in Jarvis style."""
from __future__ import annotations

import threading
from typing import Callable

import keyboard as kb  # type: ignore[import]
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSlider, QVBoxLayout, QWidget,
)

from dict.hotkey import is_valid_combo, normalize_combo
from dict.settings import Settings
from dict.utils_logging import get_logger

log = get_logger(__name__)


MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3"]
LANGUAGE_CHOICES: list[tuple[str, str | None]] = [
    ("auto-detect", None),
    ("Russian (ru)", "ru"),
    ("English (en)", "en"),
]


class SettingsDialog(QDialog):
    hotkey_captured = Signal(str)

    def __init__(self, current: Settings, on_save: Callable[[Settings], None],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = current
        self._on_save = on_save
        self.setWindowTitle("Dict — settings")
        self.setFixedSize(440, 360)
        self.setModal(True)
        self.setStyleSheet(_QSS)

        self._build_ui()
        self.hotkey_captured.connect(self._apply_captured_hotkey)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("◉  SETTINGS")
        title.setObjectName("title")
        root.addWidget(title)

        # Hotkey row
        root.addLayout(self._hotkey_row())
        # Model row
        root.addLayout(self._combo_row("MODEL", MODEL_CHOICES, self._current.model_size,
                                       attr="_model_combo"))
        # Language row
        lang_label = _lang_label(self._current.language)
        root.addLayout(self._combo_row("LANG", [l for l, _ in LANGUAGE_CHOICES],
                                       lang_label, attr="_lang_combo"))
        # Volume row
        root.addLayout(self._volume_row())

        root.addStretch()

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("CANCEL")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("SAVE")
        save.setObjectName("primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        root.addLayout(btn_row)

    def _hotkey_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("HOTKEY")
        label.setObjectName("field")
        label.setFixedWidth(70)
        row.addWidget(label)

        self._hotkey_edit = QLineEdit(self._current.hotkey)
        self._hotkey_edit.setReadOnly(True)
        self._hotkey_edit.setObjectName("value")
        row.addWidget(self._hotkey_edit, 1)

        self._rebind_btn = QPushButton("REBIND")
        self._rebind_btn.setObjectName("secondary")
        self._rebind_btn.clicked.connect(self._start_capture)
        row.addWidget(self._rebind_btn)
        return row

    def _combo_row(self, label_text: str, choices: list[str], initial: str,
                   attr: str) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel(label_text)
        label.setObjectName("field")
        label.setFixedWidth(70)
        row.addWidget(label)

        combo = QComboBox()
        combo.setObjectName("combo")
        combo.addItems(choices)
        if initial in choices:
            combo.setCurrentText(initial)
        setattr(self, attr, combo)
        row.addWidget(combo, 1)
        return row

    def _volume_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        label = QLabel("VOLUME")
        label.setObjectName("field")
        label.setFixedWidth(70)
        row.addWidget(label)

        self._vol_slider = QSlider(Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(int(self._current.volume * 100))
        self._vol_slider.setObjectName("volume")
        row.addWidget(self._vol_slider, 1)

        self._vol_label = QLabel(f"{int(self._current.volume * 100)}%")
        self._vol_label.setObjectName("value")
        self._vol_label.setFixedWidth(40)
        self._vol_slider.valueChanged.connect(
            lambda v: self._vol_label.setText(f"{v}%")
        )
        row.addWidget(self._vol_label)
        return row

    # ---- hotkey capture ----

    def _start_capture(self) -> None:
        self._rebind_btn.setText("LISTENING…")
        self._hotkey_edit.setText("press any combination…")

        def capture() -> None:
            try:
                raw = kb.read_hotkey(suppress=False)
            except Exception:
                log.exception("hotkey capture failed")
                raw = self._current.hotkey
            # Latinise (Cyrillic -> QWERTY) and validate before showing.
            combo = normalize_combo(raw)
            if not is_valid_combo(combo):
                log.warning("captured unparseable combo %r -> %r, keeping old",
                            raw, combo)
                combo = self._current.hotkey
            self.hotkey_captured.emit(combo)

        threading.Thread(target=capture, name="hotkey-capture", daemon=True).start()

    def _apply_captured_hotkey(self, combo: str) -> None:
        self._hotkey_edit.setText(combo)
        self._rebind_btn.setText("REBIND")

    # ---- save ----

    def _save(self) -> None:
        combo = self._hotkey_edit.text().strip()
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
            volume=self._vol_slider.value() / 100.0,
        )
        try:
            self._on_save(new)
        finally:
            self.accept()


def _lang_label(value: str | None) -> str:
    for lbl, v in LANGUAGE_CHOICES:
        if v == value:
            return lbl
    return LANGUAGE_CHOICES[0][0]


_QSS = """
QDialog {
    background-color: #05070f;
    color: #c8f0ff;
}
QLabel#title {
    color: #00e5ff;
    font-family: 'Consolas';
    font-size: 16px;
    font-weight: bold;
    letter-spacing: 3px;
}
QLabel#field {
    color: #0091a8;
    font-family: 'Consolas';
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 1px;
}
QLineEdit#value, QLabel#value {
    background-color: #0a0f1a;
    color: #c8f0ff;
    border: 1px solid #122030;
    border-radius: 4px;
    padding: 6px 10px;
    font-family: 'Consolas';
    font-size: 11px;
}
QComboBox#combo {
    background-color: #0a0f1a;
    color: #c8f0ff;
    border: 1px solid #122030;
    border-radius: 4px;
    padding: 4px 10px;
    font-family: 'Consolas';
    font-size: 11px;
}
QComboBox#combo::drop-down {
    border: none;
    width: 20px;
}
QComboBox#combo::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid #00e5ff;
    width: 0; height: 0;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background-color: #0a0f1a;
    color: #c8f0ff;
    selection-background-color: #00e5ff;
    selection-color: #05070f;
    border: 1px solid #1a3a5a;
}
QSlider#volume::groove:horizontal {
    height: 4px;
    background: #122030;
    border-radius: 2px;
}
QSlider#volume::sub-page:horizontal {
    background: #00e5ff;
    border-radius: 2px;
}
QSlider#volume::handle:horizontal {
    background: #00e5ff;
    width: 14px;
    height: 14px;
    margin: -6px 0;
    border-radius: 7px;
}
QPushButton#primary {
    background-color: #00e5ff;
    color: #05070f;
    border: none;
    border-radius: 4px;
    padding: 8px 22px;
    font-family: 'Consolas';
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 2px;
}
QPushButton#primary:hover {
    background-color: #1ef0ff;
}
QPushButton#secondary {
    background-color: transparent;
    color: #4a6978;
    border: 1px solid #4a6978;
    border-radius: 4px;
    padding: 8px 18px;
    font-family: 'Consolas';
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 2px;
}
QPushButton#secondary:hover {
    color: #00e5ff;
    border-color: #00e5ff;
}
"""
