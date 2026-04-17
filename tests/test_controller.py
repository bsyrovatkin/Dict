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
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
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
    mocks["clipboard"].assert_called_once_with("проверка")
    mocks["logger"].assert_called_once_with("проверка")
    mocks["window"].refresh.assert_called_once()
    mocks["window"].show_for.assert_called_once()
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
