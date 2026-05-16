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

import queue
import threading
from typing import Callable, Optional

import numpy as np

from dict.utils_logging import get_logger

log = get_logger(__name__)

_VAD_WINDOW = 512  # silero's fixed window size at 16 kHz (~32 ms)


class _SegmentBuilder:
    """Stateful: feed int16 chunks + per-window speech flags, emit segments.

    Commit triggers:
      - silence run >= pause_ms after any speech in the current segment
      - speech run  >= hard_cap_s (forced split when speech-only time exceeds cap)
      - elapsed run >= hard_cap_elapsed_s (forced split on wall-clock time
        including inter-phrase pauses — keeps the UI feeling real-time even
        when the user speaks continuously with tiny pauses that never trip the
        silence-run commit)
    """

    def __init__(
        self,
        pause_ms: int,
        hard_cap_s: float,
        sample_rate: int = 16000,
        hard_cap_elapsed_s: float = 5.0,
    ):
        self._sample_rate = sample_rate
        # Round UP so we definitely meet the threshold
        self._max_silence_windows = max(
            1, (pause_ms * sample_rate + (1000 * _VAD_WINDOW) - 1)
               // (1000 * _VAD_WINDOW)
        )
        self._max_speech_windows = max(
            1, int(hard_cap_s * sample_rate / _VAD_WINDOW)
        )
        self._max_elapsed_windows = max(
            1, int(hard_cap_elapsed_s * sample_rate / _VAD_WINDOW)
        )
        self._current: list[np.ndarray] = []   # int16 chunks accumulated
        self._silence_run = 0                  # consecutive silent windows
        self._speech_total = 0                 # total speech windows in current segment
        self._total_windows = 0                # all windows (speech+silence) in current segment

    def feed(self, chunk: np.ndarray, is_speech_windows: list[bool]) -> list[np.ndarray]:
        """Append a chunk + its per-window speech flags. Return any commits.

        `chunk` is int16 mono at sample_rate. `is_speech_windows` is one bool
        per 512-sample window inside the chunk (so len == chunk.size // 512).
        """
        committed: list[np.ndarray] = []
        self._current.append(chunk)

        for is_speech in is_speech_windows:
            self._total_windows += 1
            if is_speech:
                self._silence_run = 0
                self._speech_total += 1
                if self._speech_total >= self._max_speech_windows:
                    seg = self._take_current()
                    if seg is not None:
                        committed.append(seg)
                    continue
            else:
                if self._speech_total > 0:
                    self._silence_run += 1
                    if self._silence_run >= self._max_silence_windows:
                        seg = self._take_current()
                        if seg is not None:
                            committed.append(seg)
                        continue
            # Elapsed-time cap: commit if we've been accumulating for too long
            # and there's at least some speech worth transcribing.
            if (self._speech_total > 0
                    and self._total_windows >= self._max_elapsed_windows):
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
        self._total_windows = 0
        return seg


class _VadAccumulator:
    """Wraps faster_whisper's bundled silero ONNX.

    Accepts int16 audio in chunks of arbitrary size. Buffers the remainder
    if the chunk is not a multiple of 512 samples. Returns one bool per
    completed 512-sample window.
    """

    def __init__(self, threshold: float = 0.5):
        # Lazy local import so module load doesn't pull onnxruntime if unused
        from faster_whisper.utils import get_assets_path
        from faster_whisper.vad import SileroVADModel
        import os

        path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        self._model = SileroVADModel(path)
        self._threshold = threshold
        self._buf = np.zeros(0, dtype=np.float32)

    def add(self, chunk_int16: np.ndarray) -> list[bool]:
        f = chunk_int16.astype(np.float32) / 32768.0
        self._buf = np.concatenate([self._buf, f])
        n = (self._buf.size // _VAD_WINDOW) * _VAD_WINDOW
        if n == 0:
            return []
        usable = self._buf[:n]
        self._buf = self._buf[n:]
        probs = self._model(usable, num_samples=_VAD_WINDOW)
        return [bool(p >= self._threshold) for p in probs.flatten()]


def _make_vad_accumulator() -> _VadAccumulator:
    """Factory indirection so tests can monkeypatch this single function."""
    return _VadAccumulator()


class VadStreamer:
    """Streaming-VAD pipeline. Two worker threads + queues.

    Lifecycle:
      start()         -> spawn vad_loop and tx_loop threads
      push(chunk)     -> non-blocking enqueue (drops chunks if queue full)
      stop()          -> flush, join workers, return joined committed text
    """

    AUDIO_QUEUE_CAP = 200   # ~ chunks; PortAudio typically delivers ~50ms chunks

    def __init__(
        self,
        transcriber,
        on_partial: Callable[[str], None],
        pause_ms: int = 500,
        hard_cap_s: float = 12.0,
        sample_rate: int = 16000,
        hard_cap_elapsed_s: float = 5.0,
    ):
        self._transcriber = transcriber
        self._on_partial = on_partial
        self._pause_ms = pause_ms
        self._hard_cap_s = hard_cap_s
        self._hard_cap_elapsed_s = hard_cap_elapsed_s
        self._sample_rate = sample_rate
        self._audio_q: queue.Queue = queue.Queue(maxsize=self.AUDIO_QUEUE_CAP)
        self._segments_q: queue.Queue = queue.Queue()
        self._committed: list[str] = []
        self._committed_lock = threading.Lock()
        self._last_stop_text: str = ""
        self._running = threading.Event()
        self._vad_thread: Optional[threading.Thread] = None
        self._tx_thread: Optional[threading.Thread] = None
        self._vad: Optional[_VadAccumulator] = None
        self._builder: Optional[_SegmentBuilder] = None
        self._passthrough = False

        try:
            self._vad = _make_vad_accumulator()
        except Exception:
            log.exception("silero VAD unavailable; streamer in passthrough mode")
            self._passthrough = True

    @property
    def is_passthrough(self) -> bool:
        return self._passthrough

    def start(self) -> None:
        if self._running.is_set():
            return
        # I4 guard: refuse if previous threads are still alive
        for name, t in (("vad", self._vad_thread), ("tx", self._tx_thread)):
            if t is not None and t.is_alive():
                raise RuntimeError(
                    f"VadStreamer.start: previous {name} thread is still alive; "
                    "stop() must complete before restart"
                )
        with self._committed_lock:
            self._committed = []
        self._last_stop_text = ""
        self._drain(self._audio_q)
        self._drain(self._segments_q)
        if self._passthrough:
            return
        # M9: reset VAD internal buffer so leftover samples from prior session
        # don't bleed into the next session's first window classification
        if self._vad is not None:
            self._vad._buf = np.zeros(0, dtype=np.float32)
        self._builder = _SegmentBuilder(
            pause_ms=self._pause_ms,
            hard_cap_s=self._hard_cap_s,
            sample_rate=self._sample_rate,
            hard_cap_elapsed_s=self._hard_cap_elapsed_s,
        )
        self._running.set()
        self._vad_thread = threading.Thread(
            target=self._vad_loop, name="vad-loop", daemon=True
        )
        self._tx_thread = threading.Thread(
            target=self._tx_loop, name="tx-loop", daemon=True
        )
        self._vad_thread.start()
        self._tx_thread.start()

    def push(self, chunk: np.ndarray) -> None:
        if self._passthrough or not self._running.is_set():
            return
        try:
            self._audio_q.put_nowait(chunk)
        except queue.Full:
            log.warning("vad audio queue full, dropping chunk")

    def stop(self) -> str:
        if self._passthrough or not self._running.is_set():
            # I3: cache the joined text on first call so a second call returns same value
            return self._last_stop_text
        self._running.clear()
        if self._vad_thread is not None:
            self._vad_thread.join(timeout=10.0)
            if self._vad_thread.is_alive():
                log.error("VadStreamer.stop: vad_thread did not join in 10s; leaking")
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=60.0)
            if self._tx_thread.is_alive():
                log.error(
                    "VadStreamer.stop: tx_thread did not join in 60s; leaking — "
                    "next start() will fail until thread exits"
                )
        with self._committed_lock:
            text = " ".join(self._committed).strip()
        self._last_stop_text = text
        return text

    # ---- worker loops ----

    def _vad_loop(self) -> None:
        while True:
            try:
                chunk = self._audio_q.get(timeout=0.05)
            except queue.Empty:
                if not self._running.is_set():
                    break
                continue
            try:
                flags = self._vad.add(chunk)
                segments = self._builder.feed(chunk, flags)
                for seg in segments:
                    self._segments_q.put(seg)
            except Exception:
                log.exception("vad_loop processing failed; dropping chunk")
        # Drain whatever's left in the queue (we cleared _running)
        while True:
            try:
                chunk = self._audio_q.get_nowait()
            except queue.Empty:
                break
            try:
                flags = self._vad.add(chunk)
                segments = self._builder.feed(chunk, flags)
                for seg in segments:
                    self._segments_q.put(seg)
            except Exception:
                log.exception("vad_loop drain failed; dropping chunk")
        # Final flush
        try:
            tail = self._builder.flush()
            if tail is not None and tail.size > 0:
                self._segments_q.put(tail)
        except Exception:
            log.exception("vad_loop flush failed")
        # Sentinel for tx_loop
        self._segments_q.put(None)

    def _tx_loop(self) -> None:
        while True:
            seg = self._segments_q.get()
            if seg is None:
                return
            try:
                text = self._transcriber.transcribe(seg)
            except Exception:
                log.exception("transcribe failed on segment; skipping")
                continue
            text = (text or "").strip()
            if not text:
                continue
            with self._committed_lock:
                self._committed.append(text)
            try:
                self._on_partial(text)
            except Exception:
                log.exception("on_partial callback raised")

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return
