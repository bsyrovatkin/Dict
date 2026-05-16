"""State machine tying together recorder, transcriber, tray, window, history."""
from __future__ import annotations

import enum
import threading
from typing import Callable, Protocol

import numpy as np

from dict.utils_logging import get_logger

log = get_logger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class _RecorderProto(Protocol):
    def start(self) -> None: ...
    def stop(self) -> np.ndarray | None: ...
    def set_push_callback(self, cb: Callable[[np.ndarray], None] | None) -> None: ...


class _TranscriberProto(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class _TrayProto(Protocol):
    def set_state(self, state: str) -> None: ...
    def notify(self, title: str, message: str) -> None: ...


class _WindowProto(Protocol):
    def refresh(self) -> None: ...
    def show_for(self, seconds: float) -> None: ...
    def set_state(self, state: str) -> None: ...
    def append_partial(self, text: str) -> None: ...
    def set_preview(self, text: str) -> None: ...
    def clear_partials(self) -> None: ...


class _HistoryProto(Protocol):
    def push(self, text: str) -> object: ...


class _SoundsProto(Protocol):
    def play_start(self) -> None: ...
    def play_stop(self) -> None: ...


class _StreamerProto(Protocol):
    def start(self) -> None: ...
    def push(self, chunk: np.ndarray) -> None: ...
    def stop(self) -> str: ...


def _default_spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="transcribe-worker", daemon=True).start()


class Controller:
    def __init__(
        self,
        recorder: _RecorderProto,
        transcriber: _TranscriberProto,
        tray: _TrayProto,
        window: _WindowProto,
        history: _HistoryProto,
        sounds: _SoundsProto,
        clipboard_set: Callable[[str], bool],
        logger_append: Callable[[str], None],
        streamer: _StreamerProto,
        paste: Callable[[str, str | None], bool],
        get_current_hotkey: Callable[[], str],
        auto_paste: bool,
        spawn: Callable[[Callable[[], None]], None] = _default_spawn,
        auto_show_seconds: float = 2.0,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._tray = tray
        self._window = window
        self._history = history
        self._sounds = sounds
        self._clipboard_set = clipboard_set
        self._logger_append = logger_append
        self._streamer = streamer
        self._paste = paste
        self._get_current_hotkey = get_current_hotkey
        self._auto_paste = auto_paste
        self._spawn = spawn
        self._auto_show_seconds = auto_show_seconds
        self._state = State.IDLE
        self._state_lock = threading.Lock()

    @property
    def state(self) -> State:
        with self._state_lock:
            return self._state

    def on_hotkey(self) -> None:
        with self._state_lock:
            current = self._state
        log.info("on_hotkey: current state=%s", current.value)

        if current is State.IDLE:
            self._start_recording()
        elif current is State.RECORDING:
            self._stop_and_transcribe()
        else:
            log.info("hotkey ignored - currently transcribing")

    def _start_recording(self) -> None:
        if not getattr(self._transcriber, "is_loaded", True):
            log.info("hotkey while model still loading — ignoring")
            self._tray.set_state("loading")
            self._window.set_state("loading")
            self._tray.notify("Dict", "Model still loading — try again in a moment")
            return
        # Clear the prior session's transcript so it doesn't bleed into this one.
        # (We intentionally do NOT clear at the end of the previous session —
        # the user wants the last result to persist until the next recording.)
        try:
            self._window.clear_partials()
        except Exception:
            log.exception("clear_partials at session start failed")
        try:
            self._recorder.set_push_callback(self._streamer.push)
            self._recorder.start()
        except Exception:
            log.exception("recorder start failed")
            self._tray.set_state("error")
            self._window.set_state("error")
            self._tray.notify("Dict", "Microphone not available")
            try:
                self._recorder.set_push_callback(None)
            except Exception:
                log.exception("clearing push_callback after start failure failed")
            return
        try:
            self._streamer.start()
        except Exception:
            log.exception("streamer start failed — recording without streaming")
        with self._state_lock:
            self._state = State.RECORDING
        self._sounds.play_start()
        self._tray.set_state("recording")
        self._window.set_state("recording")
        try:
            self._window.show_for(self._auto_show_seconds)
        except Exception:
            log.exception("window show failed")

    def _stop_and_transcribe(self) -> None:
        audio = self._recorder.stop()
        # Clear the push callback BEFORE streamer.stop so no more chunks
        # arrive while we're flushing.
        try:
            self._recorder.set_push_callback(None)
        except Exception:
            log.exception("clearing push_callback failed (continuing)")
        self._sounds.play_stop()

        with self._state_lock:
            self._state = State.TRANSCRIBING
        self._tray.set_state("busy")
        self._window.set_state("busy")

        def worker() -> None:
            try:
                stream_text = self._streamer.stop() or ""
            except Exception:
                log.exception("streamer.stop failed")
                stream_text = ""
            text = stream_text
            if not text.strip() and audio is not None:
                # Fallback: streaming produced nothing — try whole-buffer transcribe
                try:
                    text = self._transcriber.transcribe(audio) or ""
                except Exception:
                    log.exception("fallback transcribe failed")
                    text = ""
            text = text.strip()
            if not text:
                log.info("no text produced; returning to idle")
                # Leave whatever was already shown (likely empty) — the next
                # session's _start_recording() will clear it.
                self._return_to_idle()
                return
            log.info("delivering %d chars", len(text))
            self._history.push(text)
            self._logger_append(text)
            if self._auto_paste:
                try:
                    ok = self._paste(text, self._get_current_hotkey())
                    log.info("auto-paste sent ok=%s", ok)
                except Exception:
                    log.exception("paste failed; text is in clipboard for manual paste")
            else:
                self._clipboard_set(text)
            self._window.refresh()
            self._window.show_for(self._auto_show_seconds)
            # Intentionally NOT clearing partials here — the user wants the
            # final transcript to remain visible until the next session begins.
            self._return_to_idle()

        self._spawn(worker)

    def _return_to_idle(self) -> None:
        self._tray.set_state("idle")
        self._window.set_state("idle")
        with self._state_lock:
            self._state = State.IDLE
