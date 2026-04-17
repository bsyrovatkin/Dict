from __future__ import annotations

import numpy as np

from dict.recorder import should_drop_recording


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
