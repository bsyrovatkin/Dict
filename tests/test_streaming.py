from __future__ import annotations

import numpy as np
import pytest

from dict.streaming import _SegmentBuilder

SR = 16000
WINDOW = 512  # silero window size in samples


def _chunk(n_samples: int, value: int = 100) -> np.ndarray:
    return np.full(n_samples, value, dtype=np.int16)


def test_builder_no_commit_while_only_silence():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4)
    # All-silence: 4 windows of False
    segments = b.feed(chunk, [False, False, False, False])
    assert segments == []
    assert b.flush() is None  # nothing was ever spoken


def test_builder_commits_after_pause_following_speech():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    # 500ms at 16kHz / 512 = ~15.6, round up to 16 windows of silence
    # Feed: 4 speech windows, then 16 silence windows
    speech_chunk = _chunk(WINDOW * 4)
    silence_chunk = _chunk(WINDOW * 16, value=0)
    seg1 = b.feed(speech_chunk, [True, True, True, True])
    assert seg1 == []
    seg2 = b.feed(silence_chunk, [False] * 16)
    assert len(seg2) == 1
    # Segment should contain at least the speech chunk (silence may be appended too)
    assert seg2[0].dtype == np.int16
    assert seg2[0].size >= WINDOW * 4


def test_builder_hard_cap_forces_commit():
    # hard_cap_s = 1.0 -> ~31 windows
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=1.0, sample_rate=SR)
    # Feed continuous speech: 40 windows
    chunk = _chunk(WINDOW * 40)
    segs = b.feed(chunk, [True] * 40)
    assert len(segs) >= 1  # at least one forced commit


def test_builder_flush_emits_pending_speech():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4)
    b.feed(chunk, [True, True, True, True])
    # No silence yet -> not committed
    flushed = b.flush()
    assert flushed is not None
    assert flushed.size >= WINDOW * 4


def test_builder_flush_returns_none_if_no_speech_pending():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4, value=0)
    b.feed(chunk, [False, False, False, False])
    assert b.flush() is None


def test_builder_handles_multiple_speech_silence_cycles():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    speech = _chunk(WINDOW * 4)
    silence = _chunk(WINDOW * 16, value=0)
    # Cycle 1
    b.feed(speech, [True] * 4)
    seg1 = b.feed(silence, [False] * 16)
    assert len(seg1) == 1
    # Cycle 2 — builder should reset state
    b.feed(speech, [True] * 4)
    seg2 = b.feed(silence, [False] * 16)
    assert len(seg2) == 1
