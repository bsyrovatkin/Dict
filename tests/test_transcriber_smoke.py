from __future__ import annotations

import numpy as np
import pytest

from dict.transcriber import Transcriber


@pytest.mark.slow
def test_transcribe_silent_array_returns_empty():
    t = Transcriber()
    audio = np.zeros(16000 * 2, dtype=np.int16)
    result = t.transcribe(audio)
    assert result == ""


@pytest.mark.slow
def test_transcribe_tone_returns_some_string_not_crash():
    t = Transcriber()
    samples = (0.5 * 32767 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.int16)
    result = t.transcribe(samples)
    assert isinstance(result, str)
