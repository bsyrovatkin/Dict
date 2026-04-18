"""Modal-style settings dialog (Toplevel) in the same Jarvis theme.

Runs on the same Tk thread as the main window. Use
`SettingsWindow(parent_root, current_settings, on_save).open()` to show it.
Saving calls `on_save(new_settings)` and closes the dialog.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

import keyboard as kb  # type: ignore[import]

from dict.settings import Settings
from dict.utils_logging import get_logger
from dict.window import (  # reuse the palette
    BG, BG_PANEL, CYAN, CYAN_DIM, FG, FG_DIM, MONO,
)

log = get_logger(__name__)


MODEL_CHOICES = ["tiny", "base", "small", "medium", "large-v3"]
LANGUAGE_CHOICES = [("auto-detect", None), ("Russian (ru)", "ru"),
                    ("English (en)", "en")]


class SettingsWindow:
    def __init__(
        self,
        parent: tk.Tk,
        current: Settings,
        on_save: Callable[[Settings], None],
    ) -> None:
        self._parent = parent
        self._current = current
        self._on_save = on_save
        self._top: tk.Toplevel | None = None
        self._hotkey_var = tk.StringVar(value=current.hotkey)
        self._model_var = tk.StringVar(value=current.model_size)
        self._lang_var = tk.StringVar(value=_lang_label(current.language))
        self._volume_var = tk.DoubleVar(value=current.volume)
        self._capture_btn: tk.Button | None = None
        self._hotkey_capture_handle: int | None = None

    def open(self) -> None:
        if self._top is not None and self._top.winfo_exists():
            self._top.lift()
            return
        top = tk.Toplevel(self._parent)
        top.title("Dict — settings")
        top.geometry("420x340")
        top.resizable(False, False)
        top.configure(bg=BG)
        top.transient(self._parent)
        top.grab_set()
        self._top = top

        tk.Label(top, text="◉  SETTINGS", font=(MONO, 14, "bold"),
                 fg=CYAN, bg=BG).pack(fill="x", padx=20, pady=(16, 10))

        panel = tk.Frame(top, bg=BG_PANEL, padx=16, pady=14)
        panel.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        self._row(panel, "HOTKEY", self._build_hotkey(panel))
        self._row(panel, "MODEL",  self._build_model(panel))
        self._row(panel, "LANG",   self._build_lang(panel))
        self._row(panel, "VOLUME", self._build_volume(panel))

        btns = tk.Frame(top, bg=BG)
        btns.pack(fill="x", padx=20, pady=(0, 16))
        _Btn(btns, "CANCEL", self._cancel, accent=False).pack(side="right", padx=(6, 0))
        _Btn(btns, "SAVE",   self._save,   accent=True ).pack(side="right")

        top.protocol("WM_DELETE_WINDOW", self._cancel)

    # ---------------- row builders ----------------

    def _row(self, parent: tk.Frame, label: str, widget: tk.Widget) -> None:
        row = tk.Frame(parent, bg=BG_PANEL)
        row.pack(fill="x", pady=5)
        tk.Label(row, text=label, font=(MONO, 9, "bold"),
                 fg=CYAN_DIM, bg=BG_PANEL, width=8, anchor="w").pack(side="left")
        widget.pack(side="left", fill="x", expand=True)

    def _build_hotkey(self, parent: tk.Frame) -> tk.Widget:
        frame = tk.Frame(parent, bg=BG_PANEL)
        entry = tk.Label(
            frame, textvariable=self._hotkey_var,
            font=(MONO, 11, "bold"),
            fg=FG, bg=BG, relief="flat",
            padx=10, pady=6, anchor="w",
        )
        entry.pack(side="left", fill="x", expand=True)

        def start_capture() -> None:
            if self._capture_btn is None:
                return
            self._capture_btn.configure(text="LISTENING…", fg=CYAN)
            self._hotkey_var.set("press any combination…")
            # Use keyboard.read_hotkey() in a background thread since
            # it blocks until the user releases.
            import threading

            def capture() -> None:
                try:
                    combo = kb.read_hotkey(suppress=False)
                except Exception:
                    log.exception("hotkey capture failed")
                    combo = self._current.hotkey

                def apply() -> None:
                    self._hotkey_var.set(combo)
                    if self._capture_btn is not None:
                        self._capture_btn.configure(text="REBIND", fg=CYAN)

                if self._top is not None:
                    self._top.after(0, apply)

            threading.Thread(target=capture, name="hotkey-capture", daemon=True).start()

        self._capture_btn = _Btn(frame, "REBIND", start_capture, accent=False)
        self._capture_btn.pack(side="right", padx=(8, 0))
        return frame

    def _build_model(self, parent: tk.Frame) -> tk.Widget:
        frame = tk.Frame(parent, bg=BG_PANEL)
        cb = ttk.Combobox(frame, textvariable=self._model_var,
                          values=MODEL_CHOICES, state="readonly",
                          font=(MONO, 10))
        cb.pack(side="left", fill="x", expand=True)
        return frame

    def _build_lang(self, parent: tk.Frame) -> tk.Widget:
        frame = tk.Frame(parent, bg=BG_PANEL)
        cb = ttk.Combobox(frame, textvariable=self._lang_var,
                          values=[lbl for lbl, _ in LANGUAGE_CHOICES],
                          state="readonly", font=(MONO, 10))
        cb.pack(side="left", fill="x", expand=True)
        return frame

    def _build_volume(self, parent: tk.Frame) -> tk.Widget:
        frame = tk.Frame(parent, bg=BG_PANEL)
        scale = tk.Scale(
            frame, from_=0.0, to=1.0, resolution=0.05, orient="horizontal",
            variable=self._volume_var,
            bg=BG_PANEL, fg=FG_DIM, highlightthickness=0,
            troughcolor=BG, activebackground=CYAN,
            sliderrelief="flat", sliderlength=16,
            showvalue=True, font=(MONO, 8),
        )
        scale.pack(fill="x", expand=True)
        return frame

    # ---------------- actions ----------------

    def _save(self) -> None:
        combo = self._hotkey_var.get().strip()
        if not combo or combo.startswith("press"):
            combo = self._current.hotkey
        label = self._lang_var.get()
        lang_value = next((v for lbl, v in LANGUAGE_CHOICES if lbl == label),
                          self._current.language)
        new = Settings(
            hotkey=combo,
            model_size=self._model_var.get() or self._current.model_size,
            language=lang_value,
            volume=float(self._volume_var.get()),
        )
        try:
            self._on_save(new)
        finally:
            self._close()

    def _cancel(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._top is not None:
            try:
                self._top.grab_release()
            except Exception:
                pass
            self._top.destroy()
            self._top = None


def _lang_label(value: str | None) -> str:
    for lbl, v in LANGUAGE_CHOICES:
        if v == value:
            return lbl
    return LANGUAGE_CHOICES[0][0]


class _Btn(tk.Button):
    """Flat themed button used in the dialog."""

    def __init__(self, parent: tk.Widget, text: str, command: Callable[[], None],
                 accent: bool = False) -> None:
        colour = CYAN if accent else FG_DIM
        super().__init__(
            parent, text=text, command=command,
            font=(MONO, 9, "bold"),
            fg=BG if accent else colour,
            bg=colour if accent else BG_PANEL,
            activebackground=CYAN if accent else BG,
            activeforeground=BG if accent else CYAN,
            relief="flat", padx=16, pady=6, borderwidth=0, cursor="hand2",
        )
