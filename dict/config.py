"""Hard-coded configuration for the dict app.

Values that might need tuning during development live here so the rest
of the codebase never hard-codes magic numbers.
"""
from __future__ import annotations

from pathlib import Path

# Paths (resolved relative to the package directory)
PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
ASSETS_DIR = PROJECT_DIR / "assets"
LOG_PATH = PROJECT_DIR / "dict.log"
LOCK_PATH = Path.home() / "AppData" / "Local" / "Temp" / "dict.lock"

# Audio
SAMPLE_RATE = 16000        # Hz; Whisper is trained on 16 kHz
CHANNELS = 1
DTYPE = "int16"

# Recording semantics
MIN_RECORDING_SEC = 0.5
SILENCE_RMS_INT16 = 200    # approx -44 dBFS; recordings quieter than this are dropped

# Whisper
MODEL_SIZE = "small"       # multilingual
LANGUAGE: str | None = None  # auto-detect
BEAM_SIZE = 5

# Hotkey. Syntax is the `keyboard` library format ("f9", "ctrl+shift+v",
# "ctrl+alt+d"). Overridable at runtime via settings.json.
# F9 is a single key and works reliably; `windows+b` was swallowed by
# the Windows shell even with a low-level hook installed.
HOTKEY = "f9"

# History
HISTORY_MAX = 5

# UI
AUTO_SHOW_SECONDS = 2.0

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
}
