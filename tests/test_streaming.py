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


import threading
import time
from unittest.mock import MagicMock

from dict.streaming import VadStreamer


class _FakeTranscriber:
    """Returns 'TX(<len>)' per segment so tests can verify partial wiring."""
    def __init__(self) -> None:
        self.calls: list[int] = []

    def transcribe(self, audio: np.ndarray) -> str:
        self.calls.append(audio.size)
        return f"TX({audio.size})"


def _make_streamer(
    monkeypatch,
    *,
    transcriber=None,
    on_partial=None,
    pause_ms: int = 500,
    hard_cap_s: float = 12.0,
    passthrough: bool = False,
):
    """Build a VadStreamer with the VAD layer mocked.

    The fake VAD treats any chunk with samples != 0 as speech.
    """
    if transcriber is None:
        transcriber = _FakeTranscriber()
    if on_partial is None:
        on_partial = MagicMock()

    class _FakeVad:
        def add(self, chunk_int16):
            n_windows = chunk_int16.size // WINDOW
            return [bool(np.any(chunk_int16[i*WINDOW:(i+1)*WINDOW]))
                    for i in range(n_windows)]

    def _fake_factory():
        if passthrough:
            raise RuntimeError("forced VAD load failure")
        return _FakeVad()

    monkeypatch.setattr("dict.streaming._make_vad_accumulator", _fake_factory)

    s = VadStreamer(
        transcriber=transcriber,
        on_partial=on_partial,
        pause_ms=pause_ms,
        hard_cap_s=hard_cap_s,
        sample_rate=SR,
    )
    return s, transcriber, on_partial


def test_streamer_emits_partial_on_silence_then_speech(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, pause_ms=500, hard_cap_s=12.0)
    s.start()
    try:
        s.push(_chunk(WINDOW * 4, value=100))      # speech
        s.push(_chunk(WINDOW * 16, value=0))       # silence -> commit
        s.push(_chunk(WINDOW * 4, value=200))      # speech
        s.push(_chunk(WINDOW * 16, value=0))       # silence -> commit
        # Wait for tx_loop to drain
        for _ in range(50):
            if on_partial.call_count >= 2:
                break
            time.sleep(0.05)
    finally:
        text = s.stop()
    assert on_partial.call_count >= 2
    assert text.startswith("TX(") or "TX(" in text


def test_streamer_stop_flushes_pending(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, pause_ms=500, hard_cap_s=12.0)
    s.start()
    s.push(_chunk(WINDOW * 4, value=100))   # speech only, no trailing silence
    text = s.stop()
    assert text  # something was transcribed
    assert tx.calls  # transcriber was called at least once


def test_streamer_returns_empty_in_passthrough_mode(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, passthrough=True)
    assert s.is_passthrough is True
    s.start()
    s.push(_chunk(WINDOW * 4, value=100))
    text = s.stop()
    assert text == ""
    assert tx.calls == []  # no transcribe attempted in passthrough


def test_streamer_continues_after_transcribe_exception(monkeypatch):
    class _FlakyTx:
        def __init__(self):
            self.n = 0
        def transcribe(self, audio):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("first call blows up")
            return f"ok-{self.n}"

    tx = _FlakyTx()
    s, _, on_partial = _make_streamer(monkeypatch, transcriber=tx)
    s.start()
    try:
        # Segment 1 — will raise
        s.push(_chunk(WINDOW * 4, value=100))
        s.push(_chunk(WINDOW * 16, value=0))
        # Segment 2 — should succeed
        s.push(_chunk(WINDOW * 4, value=100))
        s.push(_chunk(WINDOW * 16, value=0))
        for _ in range(50):
            if on_partial.call_count >= 1:
                break
            time.sleep(0.05)
    finally:
        text = s.stop()
    on_partial.assert_called_once_with("ok-2")
    assert text == "ok-2"


def test_streamer_push_after_stop_is_noop(monkeypatch):
    s, _, _ = _make_streamer(monkeypatch)
    s.start()
    s.stop()
    # Should not raise
    s.push(_chunk(WINDOW * 4, value=100))


def test_streamer_drops_chunk_on_full_queue(monkeypatch, caplog):
    s, _, _ = _make_streamer(monkeypatch)
    # Shrink the queue so we can fill it cheaply
    s._audio_q = __import__("queue").Queue(maxsize=2)
    s.start()
    # Don't let vad thread consume — push fast
    for _ in range(10):
        s.push(_chunk(WINDOW * 4, value=100))
    s.stop()
    # At least one drop warning should have been logged
    assert any("queue full" in r.message.lower() for r in caplog.records)


def test_streamer_multi_cycle_no_cross_contamination(monkeypatch):
    """Cycle start->push->stop twice on the same streamer instance — no leaked state."""
    s, tx, on_partial = _make_streamer(monkeypatch)
    # Cycle 1
    s.start()
    s.push(_chunk(WINDOW * 4, value=100))   # speech
    text1 = s.stop()
    assert text1, "first cycle should produce text"
    # Cycle 2
    s.start()
    s.push(_chunk(WINDOW * 4, value=200))   # speech
    text2 = s.stop()
    assert text2, "second cycle should produce text"
    # Second-cycle text should NOT contain first-cycle text (no carry-over)
    # Each cycle's _FakeTranscriber call produced its own TX(size) string;
    # but if _committed didn't reset, text2 would be "TX(x) TX(y)" not just one.
    assert text1 not in text2 or text1 == text2  # benign equality if both same length

    # Stronger: the transcriber should have been called twice, once per cycle
    assert len(tx.calls) == 2
