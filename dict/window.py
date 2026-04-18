"""tkinter history window with Start/Stop button.

The tkinter event loop runs in its own thread so the pystray main loop
on the main thread is not blocked. All Tk calls must go through
`schedule()` (Tk objects are not thread-safe).
"""
from __future__ import annotations

import threading
import tkinter as tk
from typing import Callable

from dict.history import History
from dict.utils_logging import get_logger

log = get_logger(__name__)


# Visual state config: (button text, bg color, enabled)
_STATE_STYLES: dict[str, tuple[str, str, bool]] = {
    "idle":         ("● Start  (Win+B)",   "#2b8a3e", True),
    "recording":    ("■ Stop   (Win+B)",   "#c92a2a", True),
    "transcribing": ("Transcribing…",      "#888888", False),
    "busy":         ("Transcribing…",      "#888888", False),
    "error":        ("● Start  (error)",   "#8e6e00", True),
}


class HistoryWindow:
    def __init__(
        self,
        history: History,
        on_copy: Callable[[str], None],
        on_toggle: Callable[[], None] | None = None,
    ) -> None:
        self._history = history
        self._on_copy = on_copy
        self._on_toggle = on_toggle or (lambda: None)
        self._root: tk.Tk | None = None
        self._listbox: tk.Listbox | None = None
        self._button: tk.Button | None = None
        self._state_label: tk.Label | None = None
        self._hide_after_id: str | None = None
        self._current_state = "idle"
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tk-ui", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Dict - voice transcriber")
        root.geometry("460x260")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._hide_now)

        # Top: big Start/Stop button
        button = tk.Button(
            root,
            text="● Start",
            font=("Segoe UI", 14, "bold"),
            bg="#2b8a3e",
            fg="white",
            activebackground="#37b24d",
            activeforeground="white",
            relief="flat",
            padx=14,
            pady=10,
            command=self._on_button_click,
        )
        button.pack(fill="x", padx=8, pady=(8, 4))

        # History label
        header = tk.Label(
            root,
            text="Recent transcriptions (click to copy):",
            font=("Segoe UI", 9),
            fg="#555",
            anchor="w",
        )
        header.pack(fill="x", padx=10, pady=(4, 0))

        listbox = tk.Listbox(root, activestyle="dotbox", font=("Segoe UI", 10))
        listbox.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        listbox.bind("<<ListboxSelect>>", self._on_select)
        listbox.bind("<Double-Button-1>", self._on_select)

        self._root = root
        self._listbox = listbox
        self._button = button
        # Start shown (so user can see it works even if hotkey is flaky);
        # will still auto-hide after 2 s following a successful transcription.
        # Caller can call `hide()` if they prefer the old behavior.
        root.deiconify()
        self._ready.set()
        root.mainloop()

    def schedule(self, fn: Callable[[], None]) -> None:
        if self._root is None:
            return
        self._root.after(0, fn)

    def refresh(self) -> None:
        self.schedule(self._refresh_now)

    def _refresh_now(self) -> None:
        if self._listbox is None:
            return
        self._listbox.delete(0, tk.END)
        for entry in self._history.items():
            line = f"[{entry.timestamp.strftime('%H:%M:%S')}]  {entry.text}"
            self._listbox.insert(tk.END, line)

    def set_state(self, state: str) -> None:
        """Update the Start/Stop button to reflect the controller state."""
        self.schedule(lambda: self._set_state_now(state))

    def _set_state_now(self, state: str) -> None:
        if self._button is None:
            return
        style = _STATE_STYLES.get(state, _STATE_STYLES["idle"])
        text, color, enabled = style
        self._button.configure(
            text=text,
            bg=color,
            activebackground=color,
            state="normal" if enabled else "disabled",
        )
        self._current_state = state

    def toggle(self) -> None:
        self.schedule(self._toggle_now)

    def _toggle_now(self) -> None:
        if self._root is None:
            return
        if self._root.state() == "withdrawn":
            self._show_now()
        else:
            self._hide_now()

    def show_for(self, seconds: float) -> None:
        self.schedule(lambda: self._show_for_now(seconds))

    def _show_for_now(self, seconds: float) -> None:
        # Simplified: always show, never auto-hide. The user explicitly
        # controls visibility via the tray click or window close button.
        # Auto-hide was confusing during smoke tests (results flashed).
        del seconds
        if self._root is None:
            return
        self._show_now()

    def _show_now(self) -> None:
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _hide_now(self) -> None:
        if self._root is None:
            return
        # Do not auto-hide while actively recording — the user needs to see the Stop button.
        if self._current_state == "recording":
            return
        self._root.withdraw()

    def _on_select(self, _event) -> None:
        if self._listbox is None:
            return
        idx = self._listbox.curselection()
        if not idx:
            return
        entries = self._history.items()
        i = idx[0]
        if 0 <= i < len(entries):
            self._on_copy(entries[i].text)

    def _on_button_click(self) -> None:
        log.info("start/stop button clicked (state=%s)", self._current_state)
        try:
            self._on_toggle()
        except Exception:
            log.exception("button toggle handler raised")

    def stop(self) -> None:
        self.schedule(self._stop_now)

    def _stop_now(self) -> None:
        # `quit()` breaks the mainloop; the Tk interpreter is torn down
        # cleanly by the UI thread when it returns. Calling `destroy()`
        # from outside that thread triggers `Tcl_AsyncDelete`.
        if self._root is not None:
            self._root.quit()
            self._root = None
