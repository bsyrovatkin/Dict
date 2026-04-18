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


def pick_input_device() -> int | None:
    """Choose a usable input device index.

    Windows PortAudio sometimes reports sd.default.device[0] == -1 when no
    input is set as "default communications device". In that case we walk
    the device list looking for the first usable microphone, preferring
    devices whose name contains 'mic'/'микрофон'.
    """
    # 1. If the OS default works, keep it.
    try:
        default_in = sd.default.device[0] if sd.default.device else -1
    except Exception:
        default_in = -1
    if default_in is not None and default_in >= 0:
        try:
            info = sd.query_devices(default_in)
            if info.get("max_input_channels", 0) > 0:
                return default_in
        except Exception:
            pass

    # 2. Scan all devices, prefer "mic"-ish names, then any input.
    mic_candidate: int | None = None
    first_input: int | None = None
    try:
        devices = sd.query_devices()
    except Exception:
        log.exception("could not enumerate audio devices")
        return None
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        if first_input is None:
            first_input = idx
        name = (dev.get("name") or "").lower()
        if "mic" in name or "микроф" in name or "микр" in name:
            mic_candidate = idx
            break
    choice = mic_candidate if mic_candidate is not None else first_input
    if choice is None:
        log.warning("no input devices found")
    return choice


class RecorderError(RuntimeError):
    pass


def _linear_resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Cheap linear-interpolation resample. Good enough for speech + Whisper."""
    if src_sr == dst_sr:
        return audio
    new_len = int(round(audio.size * dst_sr / src_sr))
    if new_len <= 0:
        return np.zeros(0, dtype=audio.dtype)
    xs = np.linspace(0.0, audio.size - 1, new_len)
    return np.interp(xs, np.arange(audio.size), audio).astype(audio.dtype)


class Recorder:
    # Target SR we hand to Whisper
    TARGET_SR = config.SAMPLE_RATE  # 16000

    def __init__(self, sample_rate: int = config.SAMPLE_RATE) -> None:
        self._target_sr = sample_rate
        self._native_sr = sample_rate   # may be overridden on open
        self._stream: Optional[sd.InputStream] = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._level_cb: Optional[Callable[[float], None]] = None

    def set_level_callback(self, cb: Optional[Callable[[float], None]]) -> None:
        self._level_cb = cb

    def start(self) -> None:
        if self._stream is not None:
            raise RecorderError("already recording")
        self._chunks = []

        device = pick_input_device()
        dev_name = "<auto>"
        native_sr = self._target_sr
        if device is not None:
            try:
                info = sd.query_devices(device)
                dev_name = info.get("name", f"<idx {device}>")
                native_sr = int(info.get("default_samplerate") or self._target_sr)
            except Exception:
                dev_name = f"<idx {device}>"

        # Try in order: (device, target SR) → (device, native SR) → (default, target SR)
        attempts: list[tuple[Optional[int], int]] = []
        if device is not None:
            attempts.append((device, self._target_sr))
            if native_sr != self._target_sr:
                attempts.append((device, native_sr))
        attempts.append((None, self._target_sr))

        last_exc: Exception | None = None
        for idx, sr in attempts:
            try:
                stream = sd.InputStream(
                    samplerate=sr,
                    channels=config.CHANNELS,
                    dtype=config.DTYPE,
                    device=idx,
                    callback=self._on_audio,
                )
                stream.start()
                self._stream = stream
                self._native_sr = sr
                log.info("recorder: opened device=%s (idx=%s) @ %d Hz (target=%d Hz)",
                         dev_name, idx, sr, self._target_sr)
                return
            except Exception as exc:
                log.warning("recorder attempt failed (device=%s sr=%d): %s",
                            idx, sr, exc)
                last_exc = exc

        self._stream = None
        raise RecorderError(
            f"could not open input stream after {len(attempts)} attempts: {last_exc}"
        ) from last_exc

    def stop(self) -> Optional[np.ndarray]:
        """Stop the stream and return the recording (at target SR = 16 kHz),
        or None if it should be dropped (too short / silent)."""
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
            log.warning("recorder.stop: no chunks captured")
            return None
        audio = np.concatenate(chunks).reshape(-1)
        peak = int(np.abs(audio).max()) if audio.size else 0
        rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
        log.info("recorder.stop: %d samples @%d Hz (%.2fs) peak=%d rms=%.1f",
                 audio.size, self._native_sr, audio.size / self._native_sr, peak, rms)

        if self._native_sr != self._target_sr:
            audio = _linear_resample(audio, self._native_sr, self._target_sr)
            log.info("recorder.stop: resampled -> %d samples @%d Hz",
                     audio.size, self._target_sr)

        if should_drop_recording(audio, self._target_sr):
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
