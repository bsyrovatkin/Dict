"""Hard-coded configuration for the dict app.

Values that might need tuning during development live here so the rest
of the codebase never hard-codes magic numbers.
"""
from __future__ import annotations

import tempfile as _tmp
from pathlib import Path

# Paths (resolved relative to the package directory)
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
ASSETS_DIR = PROJECT_DIR / "assets"
LOG_PATH = PROJECT_DIR / "dict.log"
LOCK_PATH = Path(_tmp.gettempdir()) / "dict.lock"

# Audio
SAMPLE_RATE = 16000        # Hz; Whisper is trained on 16 kHz
CHANNELS = 1
DTYPE = "int16"

# Recording semantics
MIN_RECORDING_SEC = 0.5
SILENCE_RMS_INT16 = 30     # approx -60 dBFS; permissive — Whisper's VAD handles the rest

# Whisper
MODEL_SIZE = "small"       # multilingual
LANGUAGE: str | None = None  # auto-detect
# 8 beams (was 5) — wider search trades a little latency for more accurate
# decoding, especially on mixed-language utterances and named entities.
BEAM_SIZE = 8
# Language detection mode (toggled in Settings dialog):
#   "single" — Whisper auto-detects internally over all 99 languages, one
#              transcribe call. Faster but can slip into UK/PL/BY/DE on
#              short or noisy clips.
#   "dual"   — explicit detect_language() first, restrict result to RU/EN,
#              then transcribe with the pinned language. One extra forward
#              pass, but never produces wrong-language output.
LANGUAGE_DETECT_MODE = "dual"
# Initial prompt — primes the decoder for the kinds of words you typically
# dictate. Mix of Russian and English programming/product/dev vocabulary
# helps the model bias toward correct spellings for jargon like "OAuth",
# "Whisper", "GitHub", "TypeScript", etc. ~1 sentence is enough.
INITIAL_PROMPT = (
    "Диктовка для разработчика. Mixed Russian and English. "
    "Common terms: GitHub, Whisper, OpenAI, Python, JavaScript, TypeScript, "
    "API, OAuth, JWT, Docker, Kubernetes, PostgreSQL, Redis, Anthropic, "
    "Claude, CUDA, NVIDIA, Chrome, VS Code, prompt, model, transcript. "
    "Game ML pipeline terms: HUD, X-Clip, Rust, Arc Riders, density, "
    "crouching, looting, AFK, episode, label."
)

# LLM polish stage — Whisper output is faithful but raw. A small LLM
# post-pass cleans up filler words, fixes punctuation/grammar, and corrects
# phonetic mistakes in technical terms ("Уиспер" → "Whisper"). This is what
# makes ChatGPT voice feel more polished than raw Whisper.
# Fail-soft: if no API key, polish is skipped and the raw output is used.
POLISH_ENABLED = True
POLISH_MODEL = "claude-3-5-haiku-20241022"
# Resolution order: this constant → ANTHROPIC_API_KEY env var. Leave None
# to use the env var (recommended — Claude Code's environment already has it).
ANTHROPIC_API_KEY: str | None = None

# Hotkey. Syntax is the `keyboard` library format ("f9", "ctrl+shift+v",
# "ctrl+alt+d"). Overridable at runtime via settings.json.
# F9 is a single key and works reliably; `windows+b` was swallowed by
# the Windows shell even with a low-level hook installed.
HOTKEY = "f9"

# History
HISTORY_MAX = 5

# UI
AUTO_SHOW_SECONDS = 2.0

# Streaming / paste
AUTO_PASTE = True            # send Ctrl+V into the focused field after transcription
# Quality-friendly VAD: aggressive timings here previously starved Whisper of
# phrase context and produced garbage like "1, 2, 3, 4" or missing letters
# ("Аплитуда" instead of "Амплитуда"). Whisper needs ~5–10s windows for its
# best output; we still cap so the UI commits within a few seconds.
STREAM_PAUSE_MS = 500        # silence that commits a segment (longer = bigger chunks)
STREAM_HARD_CAP_S = 8.0      # max speech-only seconds in a segment before forced commit
STREAM_HARD_CAP_ELAPSED_S = 7.0  # wall-clock cap (chunks arrive ~every 5-7s)

# Streaming-paste typewriter cadence — chunks are typed character-by-character
# into the focused field. 0.018s/char × ~50 chars ≈ ~1s per chunk.
STREAM_TYPE_DELAY_S = 0.018

# Real-time preview transcription (sliding window on uncommitted audio).
# A dedicated PreviewTranscriber (tiny model, see preview_transcriber.py) runs
# this loop, so latency is already low — we can afford a wider window for
# materially better preview quality.
PREVIEW_INTERVAL_S = 1.0     # how often to re-run Whisper on pending audio
PREVIEW_WINDOW_S = 5.0       # transcribe the last N seconds of pending audio

# Icon filenames (inside ASSETS_DIR)
ICON_FILES = {
    "idle":      "icon_idle.ico",
    "recording": "icon_recording.ico",
    "busy":      "icon_busy.ico",
    "error":     "icon_error.ico",
}

SOUND_FILES = {
    "start": "start.wav",
    "stop":  "stop.wav",
    "error": "error.wav",
}
