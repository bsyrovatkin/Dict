"""faster-whisper wrapper with CUDA auto-probe and lazy model load."""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from dict import config
from dict.hallucinations import is_hallucination, strip_hallucination_lines
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
        # Runtime-toggleable language detection mode. Controller can override
        # via set_lang_detect_mode() based on the Settings dialog.
        #   "single" — pass language=None, Whisper internal auto-detect (99 langs)
        #   "dual"   — explicit detect_language() restricted to RU/EN, then transcribe
        self._lang_detect_mode: str = getattr(config, "LANGUAGE_DETECT_MODE", "dual")
        self._model: object | None = None
        self._load_lock = threading.Lock()

    def set_lang_detect_mode(self, mode: str) -> None:
        if mode not in ("single", "dual"):
            log.warning("ignoring unknown lang_detect_mode=%r", mode)
            return
        log.info("lang_detect_mode: %s → %s", self._lang_detect_mode, mode)
        self._lang_detect_mode = mode

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

    def _detect_ru_or_en(self, audio_f32: np.ndarray) -> str | None:
        """Auto-detect language but restrict to RU/EN only.

        Returns 'ru' or 'en' — whichever has higher probability — or None
        if config.LANGUAGE pins a specific language (skip detection in that
        case). Forces the decoder away from neighbour-language hallucinations
        (Ukrainian, Belarusian, Polish, German) that auto-detect occasionally
        slips into on short or noisy chunks.
        """
        if config.LANGUAGE is not None:
            return None  # user pinned a language, respect it
        try:
            _, _, all_probs = self._model.detect_language(audio_f32)  # type: ignore[attr-defined]
        except Exception:
            log.exception("detect_language failed; falling back to 'en'")
            return "en"
        ru = float(all_probs.get("ru", 0.0)) if hasattr(all_probs, "get") else 0.0
        en = float(all_probs.get("en", 0.0)) if hasattr(all_probs, "get") else 0.0
        choice = "ru" if ru >= en else "en"
        log.info("ru-or-en detect: ru=%.3f en=%.3f → %s", ru, en, choice)
        return choice

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe int16 mono audio at 16 kHz. Returns empty string if no speech."""
        self.ensure_loaded()
        assert self._model is not None
        audio_f32 = (audio.astype(np.float32) / 32768.0)
        # Language selection branches on lang_detect_mode (Settings dialog):
        #   "dual"   — explicit detect_language() restricted to RU/EN, then
        #              transcribe with the pinned language
        #   "single" — pass None and let Whisper's internal auto-detect decide
        #              in the same forward pass (faster, but may slip into UK/PL/BY)
        if config.LANGUAGE is not None:
            lang = config.LANGUAGE  # user pinned, respect it
        elif self._lang_detect_mode == "single":
            lang = None  # Whisper auto-detect internally
            log.info("transcribe: lang_detect_mode=single (whisper internal auto-detect)")
        else:
            lang = self._detect_ru_or_en(audio_f32)
        # Language-specific initial prompt: a mixed-language prompt actively
        # primes cross-language hallucinations ("Thank you for watching"
        # leaks through even with language='ru'). Pick the prompt that
        # matches the pinned language; default to RU if unpinned (single
        # auto-detect mode) since this user dictates primarily in Russian.
        if lang == "en":
            initial_prompt = getattr(config, "INITIAL_PROMPT_EN", config.INITIAL_PROMPT)
        else:
            initial_prompt = getattr(config, "INITIAL_PROMPT_RU", config.INITIAL_PROMPT)
        segments, info = self._model.transcribe(  # type: ignore[attr-defined]
            audio_f32,
            language=lang,
            beam_size=config.BEAM_SIZE,
            # condition_on_previous_text=False — dictation is short discrete
            # utterances, not long-form narration. Conditioning on prior
            # output here mostly propagates hallucinations across segments
            # (one "Thank you." seeds the next chunk to repeat it).
            condition_on_previous_text=False,
            # Temperature fallback ladder capped at 0.4. Above 0.4 the
            # decoder starts inventing high-prior YouTube-subtitle artifacts
            # ("Subtitles by the Amara.org community", "Thank you.") on
            # low-confidence audio instead of failing gracefully.
            temperature=[0.0, 0.2, 0.4],
            # Reject hallucinated repetition and low-confidence garbage by
            # falling through to the next temperature.
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            # Stricter (was 0.6). On marginal audio Whisper prefers to
            # output empty rather than a stock filler phrase.
            no_speech_threshold=0.7,
            # VAD pre-filter — drops silence regions before they reach the
            # decoder. Tightened parameters: smaller min-silence so we don't
            # merge separate utterances, and a longer max-speech window so
            # one long sentence isn't split mid-word.
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=120,
            ),
            # Steer the decoder with a short prompt that primes the kinds of
            # words the user typically dictates. Helps with mixed RU+EN
            # programming/product terms and acronyms.
            initial_prompt=initial_prompt,
            # word_timestamps off — we don't display them and they cost time.
            word_timestamps=False,
        )
        # Per-segment hallucination filter: drop segments that are *only*
        # a known Whisper stock phrase. Real segments containing a mix of
        # real speech + artifact are passed to strip_hallucination_lines()
        # which removes the artifact sentences and keeps the rest.
        parts: list[str] = []
        for seg in segments:
            s = (seg.text or "").strip()
            if not s:
                continue
            if is_hallucination(s):
                log.info("dropped hallucinated segment: %r", s)
                continue
            cleaned = strip_hallucination_lines(s)
            if cleaned:
                parts.append(cleaned)
            elif s:
                log.info("dropped hallucinated segment (post-strip): %r", s)
        text = " ".join(parts).strip()
        log.info("transcribed lang=%s duration=%.2fs -> %d chars",
                 info.language, info.duration, len(text))
        return text
