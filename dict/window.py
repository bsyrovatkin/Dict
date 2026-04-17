"""tkinter history window.

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


class HistoryWindow:
    def __init__(self, history: History, on_copy: Callable[[str], None]) -> None:
        self._history = history
        self._on_copy = on_copy
        self._root: tk.Tk | None = None
        self._listbox: tk.Listbox | None = None
        self._hide_after_id: str | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tk-ui", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Dict - history")
        root.geometry("420x180")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._hide_now)

        listbox = tk.Listbox(root, activestyle="dotbox", font=("Segoe UI", 10))
        listbox.pack(fill="both", expand=True, padx=6, pady=6)
        listbox.bind("<<ListboxSelect>>", self._on_select)
        listbox.bind("<Double-Button-1>", self._on_select)

        self._root = root
        self._listbox = listbox
        root.withdraw()
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
        if self._root is None:
            return
        self._show_now()
        if self._hide_after_id is not None:
            self._root.after_cancel(self._hide_after_id)
        self._hide_after_id = self._root.after(int(seconds * 1000), self._hide_now)

    def _show_now(self) -> None:
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _hide_now(self) -> None:
        if self._root is None:
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

    def stop(self) -> None:
        self.schedule(self._stop_now)

    def _stop_now(self) -> None:
        # `quit()` breaks the mainloop; the Tk interpreter is torn down
        # cleanly by the UI thread when it returns. Calling `destroy()`
        # from outside that thread triggers `Tcl_AsyncDelete`.
        if self._root is not None:
            self._root.quit()
            self._root = None
