"""Lightweight Whisper wrapper used exclusively for sliding-window preview
transcription during recording.

Uses the `tiny` model: ~75 MB on disk, ~5x faster than `small` on CPU. Quality
is lower but acceptable for transient preview text that gets replaced by the
small-model commit a moment later. Loading is lazy + once, behind a lock so
the warmup thread and the first preview-loop tick don't race.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from dict import config
from dict.transcriber import probe_cuda
from dict.utils_logging import get_logger

log = get_logger(__name__)


class PreviewTranscriber:
    """Whisper-tiny wrapper. Same `transcribe(int16 ndarray) -> str` API as
    `Transcriber` so it can be swapped into VadStreamer's preview loop.
    """

    MODEL_SIZE = "tiny"

    def __init__(self) -> None:
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
            from faster_whisper import WhisperModel  # type: ignore[import]
            device, compute_type = probe_cuda()
            log.info("loading PREVIEW whisper model=%s device=%s compute=%s",
                     self.MODEL_SIZE, device, compute_type)
            self._model = WhisperModel(
                self.MODEL_SIZE, device=device, compute_type=compute_type
            )
            log.info("preview whisper model loaded")

    def transcribe(self, audio: np.ndarray) -> str:
        """Fast preview transcribe. int16 mono @ 16 kHz in; text out.

        Skips VAD (audio is mid-utterance by design) and uses beam_size=1 for
        the lowest possible latency — preview prioritizes "something on screen
        now" over best quality.
        """
        self.ensure_loaded()
        assert self._model is not None
        audio_f32 = audio.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(  # type: ignore[attr-defined]
            audio_f32,
            language=config.LANGUAGE,
            beam_size=1,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        parts = [seg.text.strip() for seg in segments]
        return " ".join(p for p in parts if p).strip()
