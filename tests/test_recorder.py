from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from dict import config
from dict.recorder import Recorder, _linear_resample, apply_gain, should_drop_recording


def test_drops_too_short():
    audio = np.zeros(int(16000 * 0.3), dtype=np.int16)
    assert should_drop_recording(audio, sample_rate=16000) is True


def test_drops_silent_but_long_enough():
    audio = np.zeros(int(16000 * 1.0), dtype=np.int16)
    assert should_drop_recording(audio, sample_rate=16000) is True


def test_keeps_long_enough_and_loud_enough():
    t = np.arange(16000) / 16000
    audio = (0.9 * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    assert should_drop_recording(audio, sample_rate=16000) is False


def test_drops_empty_array():
    assert should_drop_recording(np.zeros(0, dtype=np.int16), sample_rate=16000) is True


def test_apply_gain_unity_is_noop():
    audio = np.array([100, -200, 300], dtype=np.int16)
    out = apply_gain(audio, 1.0)
    assert out is audio  # no copy when gain==1


def test_apply_gain_doubles_quiet_signal():
    audio = np.array([1000, -1000, 500], dtype=np.int16)
    out = apply_gain(audio, 2.0)
    assert out.dtype == np.int16
    assert list(out) == [2000, -2000, 1000]


def test_apply_gain_clips_to_int16_range():
    audio = np.array([20000, -20000, 100], dtype=np.int16)
    out = apply_gain(audio, 5.0)
    assert out.max() <= 32767
    assert out.min() >= -32768
    # 20000 * 5 = 100000 -> clipped to 32767
    assert out[0] == 32767
    assert out[1] == -32768


def test_apply_gain_handles_empty():
    audio = np.zeros(0, dtype=np.int16)
    out = apply_gain(audio, 3.0)
    assert out.size == 0


def test_linear_resample_no_op_when_rates_match():
    audio = np.array([1, 2, 3], dtype=np.int16)
    out = _linear_resample(audio, 16000, 16000)
    assert out is audio


def test_linear_resample_downsamples():
    # 100 samples @ 32000 Hz -> 50 samples @ 16000 Hz
    audio = np.arange(100, dtype=np.int16)
    out = _linear_resample(audio, 32000, 16000)
    assert out.size == 50
    assert out.dtype == np.int16


def test_set_push_callback_invoked_on_chunk():
    r = Recorder()
    cb = MagicMock()
    r.set_push_callback(cb)
    # Synthesize a sounddevice callback at the same native==target SR
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_called_once()
    arg = cb.call_args[0][0]
    assert arg.shape == (512,)


def test_set_push_callback_none_disables_invocation():
    r = Recorder()
    cb = MagicMock()
    r.set_push_callback(cb)
    r.set_push_callback(None)
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_not_called()


def test_push_callback_exception_does_not_break_audio_thread(caplog):
    r = Recorder()
    cb = MagicMock(side_effect=RuntimeError("kaboom"))
    r.set_push_callback(cb)
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    # Must not raise
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_called_once()
