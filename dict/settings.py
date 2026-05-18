"""User settings stored as JSON in %APPDATA%/dict/settings.json.

Fields that don't exist in the file fall back to `config.py` defaults.
"""
from __future__ import annotations

import json
import sys as _sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)

if _sys.platform == "win32":
    SETTINGS_PATH = Path.home() / "AppData" / "Roaming" / "dict" / "settings.json"
elif _sys.platform == "darwin":
    SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "dict" / "settings.json"
else:
    SETTINGS_PATH = Path.home() / ".config" / "dict" / "settings.json"


@dataclass
class Settings:
    hotkey: str = field(default_factory=lambda: config.HOTKEY)
    model_size: str = field(default_factory=lambda: config.MODEL_SIZE)
    language: str | None = field(default_factory=lambda: config.LANGUAGE)
    volume: float = 0.7    # 0.0 – 1.0; playback volume (not yet applied to WAVs)
    mic_gain: float = 1.0  # 0.5 – 5.0; software gain applied before transcription
    auto_paste: bool = field(default_factory=lambda: config.AUTO_PASTE)
    # Language detection mode:
    #   "single" — pass language=None to Whisper; one forward pass, internal auto-detect
    #              over all 99 languages (occasionally slips into UK/PL/BY on short clips)
    #   "dual"   — call detect_language() first, restrict to RU/EN, then transcribe
    #              with the detected language pinned (no foreign-language hallucinations)
    lang_detect_mode: str = field(
        default_factory=lambda: getattr(config, "LANGUAGE_DETECT_MODE", "dual"),
    )

    def to_dict(self) -> dict:
        return asdict(self)


def load() -> Settings:
    s = Settings()
    if not SETTINGS_PATH.exists():
        log.info("no settings file; using defaults from config.py")
        return s
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        log.exception("failed to read settings, using defaults")
        return s
    valid_keys = {f.name for f in fields(s)}
    for k, v in data.items():
        if k in valid_keys:
            setattr(s, k, v)
    log.info("loaded settings: %s", s.to_dict())
    return s


def save(settings: Settings) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("settings saved to %s", SETTINGS_PATH)
