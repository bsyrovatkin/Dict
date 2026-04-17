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


class _TranscriberProto(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class _TrayProto(Protocol):
    def set_state(self, state: str) -> None: ...
    def notify(self, title: str, message: str) -> None: ...


class _WindowProto(Protocol):
    def refresh(self) -> None: ...
    def show_for(self, seconds: float) -> None: ...


class _HistoryProto(Protocol):
    def push(self, text: str) -> object: ...


class _SoundsProto(Protocol):
    def play_start(self) -> None: ...
    def play_stop(self) -> None: ...


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

        if current is State.IDLE:
            self._start_recording()
        elif current is State.RECORDING:
            self._stop_and_transcribe()
        else:
            log.debug("hotkey ignored - currently transcribing")

    def _start_recording(self) -> None:
        try:
            self._recorder.start()
        except Exception:
            log.exception("recorder start failed")
            self._tray.set_state("error")
            self._tray.notify("Dict", "Microphone not available")
            return
        with self._state_lock:
            self._state = State.RECORDING
        self._sounds.play_start()
        self._tray.set_state("recording")

    def _stop_and_transcribe(self) -> None:
        audio = self._recorder.stop()
        self._sounds.play_stop()

        if audio is None:
            self._tray.set_state("idle")
            with self._state_lock:
                self._state = State.IDLE
            return

        with self._state_lock:
            self._state = State.TRANSCRIBING
        self._tray.set_state("busy")

        def worker() -> None:
            try:
                text = self._transcriber.transcribe(audio)
            except Exception:
                log.exception("transcription failed")
                self._tray.notify("Dict", "Transcription failed")
                self._return_to_idle()
                return
            text = (text or "").strip()
            if not text:
                self._return_to_idle()
                return
            self._history.push(text)
            self._logger_append(text)
            self._clipboard_set(text)
            self._window.refresh()
            self._window.show_for(self._auto_show_seconds)
            self._return_to_idle()

        self._spawn(worker)

    def _return_to_idle(self) -> None:
        self._tray.set_state("idle")
        with self._state_lock:
            self._state = State.IDLE
