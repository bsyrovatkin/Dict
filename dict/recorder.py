"""Microphone capture using sounddevice.

The sounddevice callback fires on a dedicated thread owned by PortAudio,
so we guard the chunk list with a lock.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


# Normalising factor: int16 max, with a little head-room so even 100% loudness
# never quite saturates the VU meter. 25000 ≈ -2.4 dBFS.
_VU_REFERENCE = 25000.0


def should_drop_recording(audio: np.ndarray, sample_rate: int) -> bool:
    if audio.size == 0:
        return True
    if audio.size < int(sample_rate * config.MIN_RECORDING_SEC):
        return True
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
    if rms < config.SILENCE_RMS_INT16:
        return True
    return False


class RecorderError(RuntimeError):
    pass


class Recorder:
    def __init__(self, sample_rate: int = config.SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._stream: Optional[sd.InputStream] = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._level_cb: Optional[Callable[[float], None]] = None

    def set_level_callback(self, cb: Optional[Callable[[float], None]]) -> None:
        """Register a callback that receives a normalised RMS level
        (0.0 – 1.0) for every audio chunk. Called from the PortAudio
        callback thread — do not do heavy work inside the handler."""
        self._level_cb = cb

    def start(self) -> None:
        if self._stream is not None:
            raise RecorderError("already recording")
        self._chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=config.CHANNELS,
                dtype=config.DTYPE,
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RecorderError(f"could not open input stream: {exc}") from exc

    def stop(self) -> Optional[np.ndarray]:
        """Stop the stream and return the recording, or None if it
        should be dropped (too short / silent)."""
        if self._stream is None:
            return None
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            chunks = list(self._chunks)
            self._chunks = []
        if not chunks:
            return None
        audio = np.concatenate(chunks).reshape(-1)
        if should_drop_recording(audio, self._sample_rate):
            return None
        return audio

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            log.warning("input stream status: %s", status)
        chunk = indata.copy().reshape(-1)
        with self._lock:
            self._chunks.append(chunk)
        cb = self._level_cb
        if cb is not None and chunk.size > 0:
            try:
                rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                level = min(1.0, rms / _VU_REFERENCE)
                cb(level)
            except Exception:
                log.exception("level callback raised")
