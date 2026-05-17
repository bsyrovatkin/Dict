"""faster-whisper wrapper with CUDA auto-probe and lazy model load."""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)

def probe_cuda() -> tuple[str, str]:
    """Return (device, compute_type).

    Uses ctranslate2 directly to detect CUDA — no torch dependency required.
    If CUDA is available we pick the best supported compute type:
      - int8_float16: quantized weights, float16 math — best balance for ≥4GB
        cards (small VRAM footprint, fast inference)
      - float16: fallback if int8_float16 unsupported
      - cpu+int8: no usable CUDA device
    """
    fallback = ("cpu", "int8")
    try:
        import ctranslate2  # type: ignore[import]
    except Exception:
        log.warning("ctranslate2 import failed; falling back to CPU")
        return fallback
    try:
        n = ctranslate2.get_cuda_device_count()
        if n <= 0:
            return fallback
        supported = set(ctranslate2.get_supported_compute_types("cuda"))
        for ct in ("int8_float16", "float16", "int8"):
            if ct in supported:
                return ("cuda", ct)
        return fallback
    except Exception:
        log.exception("CUDA probe failed; falling back to CPU")
        return fallback


class TranscriberError(RuntimeError):
    pass


class Transcriber:
    def __init__(self, model_size: str = config.MODEL_SIZE) -> None:
        self._model_size = model_size
        self._model: object | None = None
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel  # type: ignore[import]
            except Exception as exc:
                raise TranscriberError(f"faster-whisper import failed: {exc}") from exc
            device, compute_type = probe_cuda()
            log.info("loading whisper model=%s device=%s compute=%s",
                     self._model_size, device, compute_type)
            try:
                self._model = WhisperModel(
                    self._model_size, device=device, compute_type=compute_type
                )
            except Exception as exc:
                raise TranscriberError(f"whisper model load failed: {exc}") from exc

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe int16 mono audio at 16 kHz. Returns empty string if no speech."""
        self.ensure_loaded()
        assert self._model is not None
        audio_f32 = (audio.astype(np.float32) / 32768.0)
        segments, info = self._model.transcribe(  # type: ignore[attr-defined]
            audio_f32,
            language=config.LANGUAGE,
            beam_size=config.BEAM_SIZE,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments]
        text = " ".join(p for p in parts if p).strip()
        log.info("transcribed lang=%s duration=%.2fs -> %d chars",
                 info.language, info.duration, len(text))
        return text
