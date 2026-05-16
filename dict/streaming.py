"""Streaming VAD pipeline.

Three pieces:
  - _VadAccumulator   : wraps faster_whisper's silero ONNX, accepts int16
                        chunks of any size, emits one bool per 512-sample
                        window (~32 ms at 16 kHz).
  - _SegmentBuilder   : pure state machine. Receives chunks + per-window
                        bools, emits ready-to-transcribe segments when
                        silence run >= pause_ms or speech run >= hard_cap.
  - VadStreamer       : threaded runtime. Owns an audio queue, a VAD
                        thread, and a transcribe thread. Public API is
                        start / push / stop.
"""
from __future__ import annotations

import numpy as np

from dict.utils_logging import get_logger

log = get_logger(__name__)

_VAD_WINDOW = 512  # silero's fixed window size at 16 kHz (~32 ms)


class _SegmentBuilder:
    """Stateful: feed int16 chunks + per-window speech flags, emit segments.

    Commit triggers:
      - silence run >= pause_ms after any speech in the current segment
      - speech run  >= hard_cap_s (forced split mid-utterance)
    """

    def __init__(self, pause_ms: int, hard_cap_s: float, sample_rate: int = 16000):
        self._sample_rate = sample_rate
        # Round UP so we definitely meet the threshold
        self._max_silence_windows = max(
            1, (pause_ms * sample_rate + (1000 * _VAD_WINDOW) - 1)
               // (1000 * _VAD_WINDOW)
        )
        self._max_speech_windows = max(
            1, int(hard_cap_s * sample_rate / _VAD_WINDOW)
        )
        self._current: list[np.ndarray] = []   # int16 chunks accumulated
        self._silence_run = 0                  # consecutive silent windows
        self._speech_total = 0                 # total speech windows in current segment

    def feed(self, chunk: np.ndarray, is_speech_windows: list[bool]) -> list[np.ndarray]:
        """Append a chunk + its per-window speech flags. Return any commits.

        `chunk` is int16 mono at sample_rate. `is_speech_windows` is one bool
        per 512-sample window inside the chunk (so len == chunk.size // 512).
        """
        committed: list[np.ndarray] = []
        self._current.append(chunk)

        for is_speech in is_speech_windows:
            if is_speech:
                self._silence_run = 0
                self._speech_total += 1
                if self._speech_total >= self._max_speech_windows:
                    seg = self._take_current()
                    if seg is not None:
                        committed.append(seg)
            else:
                if self._speech_total > 0:
                    self._silence_run += 1
                    if self._silence_run >= self._max_silence_windows:
                        seg = self._take_current()
                        if seg is not None:
                            committed.append(seg)
        return committed

    def flush(self) -> np.ndarray | None:
        """Final commit on stop. Returns the buffered segment if any speech
        was detected since the last commit; otherwise None."""
        if self._speech_total == 0:
            self._current.clear()
            return None
        return self._take_current()

    def _take_current(self) -> np.ndarray | None:
        if not self._current:
            return None
        seg = np.concatenate(self._current)
        self._current.clear()
        self._silence_run = 0
        self._speech_total = 0
        return seg
