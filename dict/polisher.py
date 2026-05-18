"""LLM polish stage for Whisper transcriptions.

Whisper produces faithful but raw transcripts: "э-э-э короче давай сделаем
вот так". ChatGPT voice doesn't feel "smarter" — they just pipe Whisper
output through GPT-4o which silently rewrites the message before it reaches
you. Dict does the same here with Claude Haiku.

Design choices:
- Fail-soft: if there's no API key, the network is down, or the API errors,
  we return the raw Whisper text unchanged. The polish never makes things
  worse, only ever better.
- Single call per finalized transcript (not per streaming chunk) — streaming
  chunks land mid-thought and aren't safe to rewrite.
- Synchronous from the controller's point of view (worker thread), but the
  call itself is short (200-500 ms with Haiku).
- API key resolution order:
    1. dict.config.ANTHROPIC_API_KEY (settings.json or constant)
    2. ANTHROPIC_API_KEY environment variable
    3. None → polish disabled, return raw
"""
from __future__ import annotations

import os
from typing import Optional

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


POLISH_SYSTEM_PROMPT = """\
You are a dictation cleanup assistant. The user dictated a message via a
local speech-to-text tool (Whisper). Rewrite it into clean, natural prose:

- Remove disfluencies ("э", "ммм", "ну", "значит", "так вот", "uh", "um",
  "you know", "like").
- Add proper sentence punctuation and capitalization.
- Fix obvious phonetic mistakes in technical / English terms. Common
  examples for this user:
    «Гитхаб» → «GitHub», «Уиспер»→«Whisper», «опенай»→«OpenAI»,
    «Клод»→«Claude», «Куда»→«CUDA», «РТэХ»→«RTX», «Хагин фейс»→«HuggingFace»,
    «гпт-5»→«GPT-5», «Постгрес»→«PostgreSQL», «Кубер»→«Kubernetes»,
    «Эх клип»→«X-Clip», «худ»→«HUD», «эпизод варг»→«episode Varg»,
    «AРЦ»→«Arc Riders», «Дэнсити»→«density», «Краучинг»→«crouching»,
    «АФК»→«AFK», «лутание»→«looting», «Раст»→«Rust».
- Combine fragmented thoughts into clean sentences without changing meaning
  or losing detail.
- Keep mixed Russian + English EXACTLY as the user mixed them (don't
  translate one to the other).
- Preserve the user's voice and tone — this is dictation, not formal prose.
  Casual is fine.
- Do NOT add new content, opinions, or filler the user didn't say.
- Do NOT summarise; preserve every distinct point.
- Return ONLY the polished text. No preamble like "Here is...", no
  surrounding quotes, no markdown formatting.
"""


def _resolve_api_key() -> Optional[str]:
    """Read API key from config or environment. Returns None if unavailable."""
    cfg_key = getattr(config, "ANTHROPIC_API_KEY", None)
    if cfg_key:
        return cfg_key.strip()
    env_key = os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return env_key.strip()
    return None


def polish(raw: str) -> str:
    """Polish raw Whisper output via Claude Haiku.

    Fail-soft: returns the input unchanged on any error / missing key.
    """
    if not raw or not raw.strip():
        return raw
    if not getattr(config, "POLISH_ENABLED", True):
        return raw
    api_key = _resolve_api_key()
    if not api_key:
        log.info("polish skipped: no ANTHROPIC_API_KEY available")
        return raw
    try:
        import anthropic  # type: ignore[import]
    except ImportError:
        log.exception("polish skipped: anthropic SDK not installed")
        return raw
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=getattr(config, "POLISH_MODEL", "claude-3-5-haiku-20241022"),
            max_tokens=2048,
            system=POLISH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw}],
            # Low temperature so the polish stays close to the user's wording.
            temperature=0.1,
        )
        polished = "".join(
            block.text for block in msg.content if hasattr(block, "text")
        ).strip()
        if not polished:
            log.warning("polish returned empty output, falling back to raw")
            return raw
        log.info(
            "polish: raw=%d chars → polished=%d chars (model=%s)",
            len(raw), len(polished), msg.model,
        )
        return polished
    except Exception:
        log.exception("polish API call failed — falling back to raw")
        return raw
