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
    def set_always_on_top(self, on: bool) -> None: ...


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
        # Tracks whether we've already streamed-pasted any chunks during the
        # current session. When True, the final stop-worker skips the bulk
        # paste so we don't double-paste what was already typed live.
        self._session_streamed = False

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

    def handle_partial(self, text: str) -> None:
        """Route a freshly-committed VAD chunk: append to the HUD transcript
        AND (if auto-paste is on) type it character-by-character into the
        focused field so the user sees text streaming in live as they speak.

        Called from the streamer's tx_thread. Safe to call across threads —
        window.append_partial uses a queued signal; type_text uses keyboard
        SendInput on its own.
        """
        try:
            self._window.append_partial(text)
        except Exception:
            log.exception("window.append_partial raised")
        if not self._auto_paste:
            return
        # Only stream-type during RECORDING or TRANSCRIBING (the tail flushed
        # during stop also counts). Don't type in IDLE — would surprise the
        # user and likely land in the wrong app.
        with self._state_lock:
            current = self._state
        if current is State.IDLE:
            return
        # Replace EVERY space (separator AND inside chunk text) with
        # NON-BREAKING SPACE (U+00A0). pynput on Windows sends regular
        # ' ' via the real VK_SPACE virtual key, which browsers intercept
        # as 'Space = page-scroll-down'. NBSP is not in pynput's keymap,
        # so it falls through to SendInput KEYEVENTF_UNICODE - no key event
        # fires, browser sees a pure Unicode char insertion.
        text_nbsp = text.replace(' ', ' ')
        sep = ' ' if self._session_streamed else ''
        payload = sep + text_nbsp
        # Lazy import — keeps controller decoupled from paste module's deps.
        from dict import paste as _paste_mod
        from dict import config as _cfg
        try:
            ok = _paste_mod.type_text(
                payload,
                current_hotkey=self._get_current_hotkey(),
                delay_s=_cfg.STREAM_TYPE_DELAY_S,
            )
            self._session_streamed = True
            log.info("stream-type chunk (%d chars, all spaces->NBSP) ok=%s", len(payload), ok)
        except Exception:
            log.exception("stream-type failed for chunk")

    def _start_recording(self) -> None:
        log.info(
            "_start_recording invoked: transcriber.is_loaded=%s",
            getattr(self._transcriber, "is_loaded", True),
        )
        if not getattr(self._transcriber, "is_loaded", True):
            log.info("hotkey while model still loading — ignoring")
            self._tray.set_state("loading")
            self._window.set_state("loading")
            self._tray.notify("Dict", "Model still loading — try again in a moment")
            return
        # Reset stream-paste tracker for the new session
        self._session_streamed = False
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
        # Pin the HUD on top for the duration of REC/DECODING so the user
        # can always see the live transcript above other windows.
        try:
            self._window.set_always_on_top(True)
        except Exception:
            log.exception("set_always_on_top(True) failed (continuing)")
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
            # LLM polish stage — cleans up filler words, fixes punctuation,
            # corrects phonetic errors in technical terms. Fail-soft: if no
            # API key or network error, returns the raw text unchanged.
            try:
                from dict.polisher import polish as _polish
                polished = _polish(text)
                if polished and polished != text:
                    log.info(
                        "polished text (raw=%d → polished=%d chars)",
                        len(text), len(polished),
                    )
                    text = polished
            except Exception:
                log.exception("polish stage failed (continuing with raw text)")
            log.info("delivering %d chars (streamed=%s)", len(text), self._session_streamed)
            self._history.push(text)
            self._logger_append(text)
            if self._session_streamed:
                # Chunks were already typed live into the focused field via
                # handle_partial. Skip the bulk paste so we don't duplicate
                # everything.
                log.info("skipping bulk paste — text already streamed live")
            elif self._auto_paste:
                try:
                    ok = self._paste(text, self._get_current_hotkey())
                    log.info("auto-paste sent ok=%s", ok)
                except Exception:
                    log.exception("paste failed; text is in clipboard for manual paste")
            else:
                self._clipboard_set(text)
            # ALWAYS write the final full text to the clipboard at the end
            # of every session, regardless of streaming/paste path. Acts as a
            # safety net: if streaming-paste missed (focus lost, target app
            # didn't accept keystrokes), user can Ctrl+V manually to recover.
            try:
                if self._clipboard_set(text):
                    log.info("final text (%d chars) parked in clipboard as fallback", len(text))
            except Exception:
                log.exception("final clipboard.set_text failed (non-fatal)")
            self._window.refresh()
            self._window.show_for(self._auto_show_seconds)
            # Intentionally NOT clearing partials here — the user wants the
            # final transcript to remain visible until the next session begins.
            self._return_to_idle()

        self._spawn(worker)

    def _return_to_idle(self) -> None:
        self._tray.set_state("idle")
        self._window.set_state("idle")
        # Drop the always-on-top pin so the user can cover the HUD with
        # other windows normally when nothing is being captured.
        try:
            self._window.set_always_on_top(False)
        except Exception:
            log.exception("set_always_on_top(False) failed (continuing)")
        with self._state_lock:
            self._state = State.IDLE
