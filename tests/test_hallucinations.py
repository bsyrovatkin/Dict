"""Unit tests for dict.hallucinations — pure, no model load."""
from __future__ import annotations

import pytest

from dict.hallucinations import (
    is_hallucination,
    strip_hallucination_lines,
)


# ---- is_hallucination -------------------------------------------------------

@pytest.mark.parametrize(
    "phrase",
    [
        # The famous one
        "Subtitles by the Amara.org community",
        "subtitles by the amara.org community",
        "Subtitles by the Amara.org community.",
        "  Subtitles by the Amara.org community  ",
        # English stock fillers we saw in dict.log
        "Thank you.",
        "Thank you",
        "Bless you.",
        "All right.",
        "We'll be right back.",
        "Hopefully.",
        "Uh...",
        # Russian YouTube credits / fillers
        "Поставьте лайк и подпишитесь",
        "Подпишитесь на канал.",
        "Продолжение следует...",
        "Спасибо за просмотр",
        # Sound-effect tags
        "[Music]",
        "[music playing]",
        "(applause)",
        "♪",
        "♪ ♪",
    ],
)
def test_pure_hallucinations_detected(phrase):
    assert is_hallucination(phrase), f"should be hallucination: {phrase!r}"


@pytest.mark.parametrize(
    "phrase",
    [
        "Привет, как дела?",
        "Run the script and check the logs.",
        # Real content that *contains* a stock word but isn't pure stock
        "Thank you for the patch, it works.",
        "Subtitles need to be reviewed by Friday.",
        # Empty / whitespace must not be flagged (let upstream decide)
        "",
        "   ",
    ],
)
def test_real_content_not_flagged(phrase):
    assert not is_hallucination(phrase), f"should NOT be hallucination: {phrase!r}"


def test_case_and_punctuation_insensitive():
    assert is_hallucination("THANK YOU!!!")
    assert is_hallucination("thank you...")
    assert is_hallucination("  Thank you,  ")


# ---- strip_hallucination_lines ----------------------------------------------

def test_strip_drops_pure_hallucination():
    assert strip_hallucination_lines("Subtitles by the Amara.org community") == ""
    assert strip_hallucination_lines("Thank you.") == ""


def test_strip_preserves_real_content_around_hallucination():
    # Real sentence + stock filler → only real sentence survives
    out = strip_hallucination_lines("Привет, как дела? Thank you.")
    assert "Привет" in out
    assert "Thank you" not in out


def test_strip_preserves_input_when_clean():
    inp = "Открой файл config.py и поменяй BEAM_SIZE."
    assert strip_hallucination_lines(inp) == inp


def test_strip_empty_returns_empty():
    assert strip_hallucination_lines("") == ""
    assert strip_hallucination_lines("   ") == "   "  # passthrough whitespace


def test_strip_handles_multiple_artifacts():
    inp = "Thanks for watching. Реальное предложение. Subtitles by the Amara.org community."
    out = strip_hallucination_lines(inp)
    assert "Реальное предложение" in out
    assert "Amara" not in out
    assert "Thanks for watching" not in out


def test_strip_handles_sound_tag_segment():
    # Whisper sometimes emits e.g. "Hello. [Music]" — we keep "Hello." and drop the tag
    out = strip_hallucination_lines("Hello. [Music]")
    assert "Hello" in out
    assert "Music" not in out
