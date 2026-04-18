"""Jarvis-style tkinter window: neon-cyan on near-black.

Central Canvas draws:
  * A record "core" — filled circle that pulses red while recording,
    hollow cyan while idle, grey while busy.
  * A VU ring around the core, made of N short radial ticks whose
    length is driven by the live mic RMS (normalised 0–1).
  * An orbiting arc spinner while the state is `busy`.

The whole UI runs on its own thread; every Tk call goes through
`schedule()` because Tk objects are not thread-safe.
"""
from __future__ import annotations

import math
import threading
import tkinter as tk
from typing import Callable, Optional

from dict.history import History
from dict.utils_logging import get_logger

log = get_logger(__name__)


# ---------- Colour palette (Jarvis / HUD) ----------------------------------

BG           = "#05070f"      # near-black with a tiny blue tint
BG_PANEL     = "#0a0f1a"
GRID_DIM     = "#0f2a3a"
CYAN         = "#00e5ff"      # primary accent
CYAN_DIM     = "#0091a8"
CYAN_GLOW    = "#1ef0ff"
RED          = "#ff3b5c"
RED_DIM      = "#a01930"
YELLOW       = "#ffcc00"
FG           = "#c8f0ff"
FG_DIM       = "#4a6978"
MONO         = "Consolas"


# State -> (core fill, core outline, status text)
_STATE_STYLES: dict[str, tuple[str, str, str]] = {
    "idle":         ("",         CYAN,      "READY"),
    "recording":    (RED,        RED,       "● REC"),
    "transcribing": ("",         YELLOW,    "DECODING…"),
    "busy":         ("",         YELLOW,    "DECODING…"),
    "error":        ("",         "#ff8a00", "MIC ERROR"),
    "loading":      ("",         CYAN_DIM,  "INIT…"),
}


class HistoryWindow:
    # Geometry constants
    WIN_W = 520
    WIN_H = 560
    CANVAS_H = 320
    CENTER = (WIN_W // 2, CANVAS_H // 2 + 10)
    CORE_R = 46          # record circle radius
    RING_R_INNER = 70    # VU ring starts here
    RING_R_OUTER = 110   # and extends to here (at full level)
    VU_SEGMENTS = 48     # number of radial ticks
    SPINNER_ARC = 60     # degrees of spinner

    def __init__(
        self,
        history: History,
        on_copy: Callable[[str], None],
        on_toggle: Callable[[], None] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        hotkey_label: str = "F9",
    ) -> None:
        self._history = history
        self._on_copy = on_copy
        self._on_toggle = on_toggle or (lambda: None)
        self._on_open_settings = on_open_settings or (lambda: None)
        self._hotkey_label = hotkey_label

        # Tk widgets (set in _run)
        self._root: tk.Tk | None = None
        self._canvas: tk.Canvas | None = None
        self._history_box: tk.Listbox | None = None
        self._hotkey_badge: tk.Label | None = None
        self._status_label: tk.Label | None = None

        # Canvas item IDs
        self._core_id: int | None = None
        self._vu_ids: list[int] = []
        self._spinner_id: int | None = None
        self._pulse_id: int | None = None  # recording pulse ring

        # Animation state
        self._current_state = "loading"
        self._level = 0.0          # smoothed VU level 0..1
        self._level_target = 0.0   # raw target from recorder
        self._spin_angle = 0.0     # radians
        self._pulse_phase = 0.0

        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tk-ui", daemon=True)

    # ---------------- lifecycle ----------------

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Dict — voice transcriber")
        root.geometry(f"{self.WIN_W}x{self.WIN_H}")
        root.resizable(False, False)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self._hide_now)

        self._build_header(root)
        self._build_canvas(root)
        self._build_footer(root)
        self._build_history(root)

        self._draw_static()
        self._draw_core()
        self._draw_vu()
        self._draw_spinner()

        self._root = root
        root.deiconify()
        self._ready.set()
        self._tick()  # start animation loop
        root.mainloop()

    # ---------------- build helpers ----------------

    def _build_header(self, root: tk.Tk) -> None:
        header = tk.Frame(root, bg=BG, height=40)
        header.pack(fill="x", padx=14, pady=(12, 0))

        title = tk.Label(header, text="◉ DICT", font=(MONO, 16, "bold"),
                         fg=CYAN, bg=BG)
        title.pack(side="left")

        badge = tk.Label(header, text=f"[ {self._hotkey_label} ]",
                         font=(MONO, 10, "bold"),
                         fg=CYAN_DIM, bg=BG)
        badge.pack(side="left", padx=(10, 0))
        self._hotkey_badge = badge

        settings_btn = tk.Label(header, text="⚙", font=(MONO, 18),
                                fg=FG_DIM, bg=BG, cursor="hand2")
        settings_btn.pack(side="right")
        settings_btn.bind("<Button-1>", lambda _e: self._on_open_settings())
        settings_btn.bind("<Enter>", lambda _e: settings_btn.configure(fg=CYAN))
        settings_btn.bind("<Leave>", lambda _e: settings_btn.configure(fg=FG_DIM))

    def _build_canvas(self, root: tk.Tk) -> None:
        canvas = tk.Canvas(root, width=self.WIN_W, height=self.CANVAS_H,
                           bg=BG, highlightthickness=0)
        canvas.pack(fill="x", padx=0, pady=(8, 0))
        canvas.bind("<Button-1>", self._on_canvas_click)
        self._canvas = canvas

    def _build_footer(self, root: tk.Tk) -> None:
        status = tk.Label(root, text="INIT…", font=(MONO, 10, "bold"),
                          fg=CYAN, bg=BG)
        status.pack(fill="x", pady=(4, 8))
        self._status_label = status

    def _build_history(self, root: tk.Tk) -> None:
        frame = tk.Frame(root, bg=BG_PANEL)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        label = tk.Label(frame, text="▸ HISTORY  (click a row to copy)",
                         font=(MONO, 9, "bold"), fg=CYAN_DIM, bg=BG_PANEL,
                         anchor="w", padx=8, pady=4)
        label.pack(fill="x")

        box = tk.Listbox(
            frame,
            font=(MONO, 10),
            bg=BG_PANEL,
            fg=FG,
            selectbackground=CYAN,
            selectforeground=BG,
            highlightthickness=0,
            borderwidth=0,
            activestyle="none",
            relief="flat",
        )
        box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        box.bind("<<ListboxSelect>>", self._on_select)
        box.bind("<Double-Button-1>", self._on_select)
        self._history_box = box

    # ---------------- static drawing ----------------

    def _draw_static(self) -> None:
        """Subtle grid lines behind everything — pure decoration."""
        c = self._canvas
        if c is None:
            return
        cx, cy = self.CENTER
        # Concentric HUD circles
        for r in (self.RING_R_OUTER + 18, self.RING_R_OUTER + 40,
                  self.RING_R_OUTER + 64):
            c.create_oval(cx - r, cy - r, cx + r, cy + r,
                          outline=GRID_DIM, width=1)
        # Ticks at cardinal points
        for deg in (0, 90, 180, 270):
            rad = math.radians(deg)
            r1 = self.RING_R_OUTER + 18
            r2 = self.RING_R_OUTER + 68
            c.create_line(
                cx + r1 * math.cos(rad), cy + r1 * math.sin(rad),
                cx + r2 * math.cos(rad), cy + r2 * math.sin(rad),
                fill=CYAN_DIM, width=1,
            )

    def _draw_core(self) -> None:
        c = self._canvas
        if c is None:
            return
        cx, cy = self.CENTER
        r = self.CORE_R
        if self._core_id is not None:
            c.delete(self._core_id)
        if self._pulse_id is not None:
            c.delete(self._pulse_id)
        fill, outline, _ = _STATE_STYLES[self._current_state]
        self._core_id = c.create_oval(cx - r, cy - r, cx + r, cy + r,
                                      fill=fill or BG, outline=outline, width=3)
        # Pulse halo (only visible while recording; drawn but size=0 otherwise)
        self._pulse_id = c.create_oval(cx, cy, cx, cy, outline=RED_DIM, width=2)
        # Mic glyph on top of the core
        c.create_text(cx, cy, text="◉" if self._current_state == "recording" else "▶",
                      font=(MONO, 22, "bold"), fill=BG if fill else outline,
                      tags=("core_glyph",))

    def _draw_vu(self) -> None:
        """(Re-)create VU ring segments. Lengths are updated in _tick."""
        c = self._canvas
        if c is None:
            return
        for tid in self._vu_ids:
            c.delete(tid)
        self._vu_ids.clear()
        cx, cy = self.CENTER
        for i in range(self.VU_SEGMENTS):
            a = 2 * math.pi * i / self.VU_SEGMENTS
            r1 = self.RING_R_INNER
            r2 = self.RING_R_INNER + 2  # grows in _tick
            tid = c.create_line(
                cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a),
                fill=CYAN_DIM, width=3, capstyle="round",
            )
            self._vu_ids.append(tid)

    def _draw_spinner(self) -> None:
        c = self._canvas
        if c is None:
            return
        if self._spinner_id is not None:
            c.delete(self._spinner_id)
        cx, cy = self.CENTER
        r = self.RING_R_OUTER + 14
        self._spinner_id = c.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=0, extent=self.SPINNER_ARC,
            style="arc", outline=YELLOW, width=4,
            state="hidden",
        )

    # ---------------- animation tick ----------------

    def _tick(self) -> None:
        if self._root is None:
            return
        c = self._canvas
        if c is None:
            return

        # Smooth level towards target (exponential decay)
        self._level += (self._level_target - self._level) * 0.35
        # Idle decay
        if self._current_state != "recording":
            self._level *= 0.9

        self._update_vu()

        if self._current_state in ("busy", "transcribing", "loading"):
            c.itemconfigure(self._spinner_id, state="normal")
            self._spin_angle = (self._spin_angle + 12) % 360
            cx, cy = self.CENTER
            r = self.RING_R_OUTER + 14
            c.coords(self._spinner_id, cx - r, cy - r, cx + r, cy + r)
            c.itemconfigure(self._spinner_id,
                            start=-self._spin_angle,
                            extent=self.SPINNER_ARC,
                            outline=YELLOW if self._current_state != "loading" else CYAN)
        else:
            c.itemconfigure(self._spinner_id, state="hidden")

        # Recording breath pulse
        if self._current_state == "recording" and self._pulse_id is not None:
            self._pulse_phase = (self._pulse_phase + 0.1) % (2 * math.pi)
            pr = self.CORE_R + 14 + 10 * (0.5 + 0.5 * math.sin(self._pulse_phase))
            cx, cy = self.CENTER
            c.coords(self._pulse_id, cx - pr, cy - pr, cx + pr, cy + pr)
            c.itemconfigure(self._pulse_id, state="normal")
        elif self._pulse_id is not None:
            c.itemconfigure(self._pulse_id, state="hidden")

        self._root.after(33, self._tick)  # ~30 fps

    def _update_vu(self) -> None:
        c = self._canvas
        if c is None:
            return
        cx, cy = self.CENTER
        level = max(0.0, min(1.0, self._level))
        max_extra = self.RING_R_OUTER - self.RING_R_INNER
        base_color = CYAN_DIM if self._current_state != "recording" else RED_DIM
        lit_color  = CYAN     if self._current_state != "recording" else RED
        lit_threshold = int(level * self.VU_SEGMENTS)
        # Segments closer to the top (12 o'clock = -π/2) light up first
        order = sorted(range(self.VU_SEGMENTS),
                       key=lambda i: abs(((i / self.VU_SEGMENTS) * 2 * math.pi
                                          + math.pi / 2) % (2 * math.pi) - math.pi))
        # Easier: just light all the first `lit_threshold` in original order
        for i, tid in enumerate(self._vu_ids):
            a = 2 * math.pi * i / self.VU_SEGMENTS
            # Each segment has a small static length plus a scaled one based on level
            seg_level = level * (0.6 + 0.4 * math.sin(a * 3 + self._spin_angle * 0.05))
            r1 = self.RING_R_INNER
            r2 = self.RING_R_INNER + 4 + max_extra * max(0.0, seg_level)
            c.coords(
                tid,
                cx + r1 * math.cos(a), cy + r1 * math.sin(a),
                cx + r2 * math.cos(a), cy + r2 * math.sin(a),
            )
            c.itemconfigure(tid, fill=lit_color if i < lit_threshold else base_color)
        del order  # silence linter

    # ---------------- public API ----------------

    def schedule(self, fn: Callable[[], None]) -> None:
        if self._root is None:
            return
        self._root.after(0, fn)

    def refresh(self) -> None:
        self.schedule(self._refresh_now)

    def _refresh_now(self) -> None:
        if self._history_box is None:
            return
        self._history_box.delete(0, tk.END)
        for entry in self._history.items():
            ts = entry.timestamp.strftime("%H:%M:%S")
            line = f"  {ts}   {entry.text}"
            self._history_box.insert(tk.END, line)

    def set_state(self, state: str) -> None:
        self.schedule(lambda: self._set_state_now(state))

    def _set_state_now(self, state: str) -> None:
        self._current_state = state
        if self._status_label is not None:
            _, _, status_text = _STATE_STYLES.get(state, _STATE_STYLES["idle"])
            colour = CYAN
            if state == "recording":
                colour = RED
            elif state in ("busy", "transcribing"):
                colour = YELLOW
            elif state == "error":
                colour = "#ff8a00"
            self._status_label.configure(text=status_text, fg=colour)
        self._draw_core()

    def set_level(self, level: float) -> None:
        """Called from the audio thread with RMS 0..1. Atomic float assignment
        is safe in CPython — no lock needed."""
        self._level_target = level

    def set_hotkey_label(self, label: str) -> None:
        self._hotkey_label = label

        def apply() -> None:
            if self._hotkey_badge is not None:
                self._hotkey_badge.configure(text=f"[ {label} ]")

        self.schedule(apply)

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
        del seconds  # no auto-hide; kept for controller API compat
        self.schedule(self._show_now)

    def _show_now(self) -> None:
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _hide_now(self) -> None:
        if self._root is None:
            return
        if self._current_state == "recording":
            return
        self._root.withdraw()

    def _on_select(self, _event) -> None:
        if self._history_box is None:
            return
        idx = self._history_box.curselection()
        if not idx:
            return
        entries = self._history.items()
        i = idx[0]
        if 0 <= i < len(entries):
            self._on_copy(entries[i].text)

    def _on_canvas_click(self, event) -> None:
        cx, cy = self.CENTER
        dx, dy = event.x - cx, event.y - cy
        if dx * dx + dy * dy <= (self.RING_R_OUTER + 10) ** 2:
            log.info("record area clicked (state=%s)", self._current_state)
            try:
                self._on_toggle()
            except Exception:
                log.exception("toggle handler raised")

    def stop(self) -> None:
        self.schedule(self._stop_now)

    def _stop_now(self) -> None:
        if self._root is not None:
            self._root.quit()
            self._root = None
