from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from dict.controller import Controller, State


@pytest.fixture
def mocks():
    return {
        "recorder":    MagicMock(),
        "transcriber": MagicMock(),
        "tray":        MagicMock(),
        "window":      MagicMock(),
        "history":     MagicMock(),
        "sounds":      MagicMock(),
        "clipboard":   MagicMock(),
        "logger":      MagicMock(),
    }


def make_controller(mocks, run_worker_inline: bool = True) -> Controller:
    def spawn(target):
        if run_worker_inline:
            target()
    streamer = MagicMock()
    streamer.stop.return_value = ""  # forces fallback to legacy whole-buffer transcribe
    paste = MagicMock(return_value=True)
    mocks["transcriber"].is_loaded = True
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
        streamer=streamer,
        paste=paste,
        get_current_hotkey=lambda: "f9",
        auto_paste=False,  # legacy tests assert clipboard path
        spawn=spawn,
    )


def make_streaming_controller(mocks, run_worker_inline: bool = True, auto_paste: bool = True):
    """Variant of make_controller that includes streamer + paste + hotkey."""
    def spawn(target):
        if run_worker_inline:
            target()
    mocks.setdefault("streamer", MagicMock())
    mocks.setdefault("paste", MagicMock(return_value=True))
    mocks.setdefault("get_hotkey", MagicMock(return_value="f9"))
    # Default: transcriber.is_loaded True so hotkey is not gated
    if not hasattr(mocks["transcriber"], "is_loaded"):
        mocks["transcriber"].is_loaded = True
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
        streamer=mocks["streamer"],
        paste=mocks["paste"],
        get_current_hotkey=mocks["get_hotkey"],
        auto_paste=auto_paste,
        spawn=spawn,
    )


def test_starts_idle(mocks):
    c = make_controller(mocks)
    assert c.state is State.IDLE


def test_first_trigger_starts_recording(mocks):
    c = make_controller(mocks)
    c.on_hotkey()
    assert c.state is State.RECORDING
    mocks["recorder"].start.assert_called_once()
    mocks["sounds"].play_start.assert_called_once()
    mocks["tray"].set_state.assert_any_call("recording")


def test_second_trigger_transcribes_and_returns_to_idle(mocks):
    audio = np.ones(32000, dtype=np.int16)
    mocks["recorder"].stop.return_value = audio
    mocks["transcriber"].transcribe.return_value = "проверка"

    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()

    mocks["recorder"].stop.assert_called_once()
    mocks["sounds"].play_stop.assert_called_once()
    mocks["transcriber"].transcribe.assert_called_once_with(audio)
    mocks["history"].push.assert_called_once_with("проверка")
    # Clipboard now set TWICE: legacy delivery + safety-net fallback,
    # both with the same text.
    assert all(call.args == ("проверка",) for call in mocks["clipboard"].call_args_list)
    assert mocks["clipboard"].call_count >= 1
    mocks["logger"].assert_called_once_with("проверка")
    mocks["window"].refresh.assert_called_once()
    mocks["window"].show_for.assert_called()
    mocks["tray"].set_state.assert_any_call("idle")
    assert c.state is State.IDLE


def test_empty_recording_is_dropped_silently(mocks):
    mocks["recorder"].stop.return_value = None
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()

    mocks["transcriber"].transcribe.assert_not_called()
    mocks["history"].push.assert_not_called()
    mocks["clipboard"].assert_not_called()
    mocks["logger"].assert_not_called()
    mocks["sounds"].play_stop.assert_called_once()
    assert c.state is State.IDLE


def test_empty_transcription_is_dropped(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["transcriber"].transcribe.return_value = "   "
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()

    mocks["history"].push.assert_not_called()
    mocks["clipboard"].assert_not_called()
    mocks["logger"].assert_not_called()
    assert c.state is State.IDLE


def test_hotkey_ignored_while_transcribing(mocks):
    c = make_controller(mocks, run_worker_inline=False)
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    c.on_hotkey()
    c.on_hotkey()
    assert c.state is State.TRANSCRIBING
    c.on_hotkey()
    assert c.state is State.TRANSCRIBING


def test_transcriber_exception_returns_to_idle(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["transcriber"].transcribe.side_effect = RuntimeError("boom")
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    assert c.state is State.IDLE
    mocks["tray"].set_state.assert_any_call("idle")
    mocks["history"].push.assert_not_called()


def test_recorder_start_failure_returns_to_idle(mocks):
    mocks["recorder"].start.side_effect = RuntimeError("no mic")
    c = make_controller(mocks)
    c.on_hotkey()
    assert c.state is State.IDLE
    mocks["tray"].set_state.assert_any_call("error")


def test_hotkey_blocked_while_model_loading(mocks):
    mocks["transcriber"].is_loaded = False
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    mocks["recorder"].start.assert_not_called()
    mocks["tray"].notify.assert_called_once()
    assert c.state is State.IDLE


def test_streaming_path_calls_paste_when_enabled(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello world"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=True)
    c.on_hotkey()  # start
    c.on_hotkey()  # stop
    mocks["paste"].assert_called_once_with("hello world", "f9")
    # clipboard is ALWAYS set at the end as a safety-net fallback so the user
    # can Ctrl+V manually even if the auto-paste landed in the wrong window.
    mocks["clipboard"].assert_called_with("hello world")


def test_streaming_path_uses_clipboard_when_auto_paste_off(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=False)
    c.on_hotkey()
    c.on_hotkey()
    mocks["paste"].assert_not_called()
    # auto_paste off → clipboard gets the text via the legacy path AND the
    # safety-net at the end (same text, two calls — both with "hello")
    assert all(
        call.args == ("hello",) for call in mocks["clipboard"].call_args_list
    )
    assert mocks["clipboard"].call_count >= 1


def test_fallback_to_whole_buffer_if_streamer_empty(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = ""
    mocks["transcriber"].transcribe.return_value = "fallback text"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=True)
    c.on_hotkey()
    c.on_hotkey()
    mocks["transcriber"].transcribe.assert_called_once()
    mocks["paste"].assert_called_once_with("fallback text", "f9")


def test_partials_cleared_when_returning_to_idle(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "x"
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    mocks["window"].clear_partials.assert_called()


def test_streamer_start_called_on_recording_start(mocks):
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    mocks["streamer"].start.assert_called_once()
    mocks["recorder"].set_push_callback.assert_called_once_with(mocks["streamer"].push)


def test_streamer_push_callback_cleared_on_stop(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello"
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    # last call to set_push_callback should be with None
    calls = mocks["recorder"].set_push_callback.call_args_list
    assert calls[-1].args == (None,)
