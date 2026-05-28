"""Post-decoding filter for known Whisper hallucinations.

Whisper was trained on YouTube subtitles and inherits a small set of
"stock phrases" the model emits on silence, music, mic noise, or any
audio it can't actually decode. The most famous is

    Subtitles by the Amara.org community

but there are dozens of others ("Thank you.", "Bless you.", "Поставьте
лайк и подпишитесь на канал", "Продолжение следует...", "[music]", "♪",
etc.). These artifacts bypass `language=` pinning because they are
extremely high-prior token sequences in the model.

This module provides two pure functions (no model required):

  - is_hallucination(text) : True if the whole string is *only* a known
    artifact. Used to drop entire segments that contain nothing real.
  - strip_hallucination_lines(text) : remove artifact phrases from a
    multi-segment string while preserving real content around them.

Match is normalised (case-fold, punctuation/whitespace squashed) so a
trailing period or zero-width space doesn't defeat the filter.
"""
from __future__ import annotations

import re
import unicodedata

# Curated list of phrases Whisper hallucinates on silence/noise/music.
# Keep entries lowercase; matching is case-insensitive after normalisation.
# Sources: well-known list in openai/whisper#928, openai/whisper#1759,
# and observations in our own dict.log.
_HALLUCINATION_PHRASES: tuple[str, ...] = (
    # English (from YouTube subtitle credits)
    "subtitles by the amara.org community",
    "subtitles by amara.org community",
    "amara.org community",
    "subtitles by the",
    "subtitles by",
    "transcription by",
    "translation by",
    "captions by",
    "captioning by",
    "edited by",
    "subscribe to my channel",
    "please subscribe",
    "like and subscribe",
    "thank you for watching",
    "thanks for watching",
    "see you next time",
    "see you in the next video",
    "see you later",
    "we'll be right back",
    "we will be right back",
    "stay tuned",
    # NOTE: single-word greetings like "Hi.", "Hello.", "Bye.", "Yeah.",
    # "Okay." are intentionally NOT in this list — users may legitimately
    # dictate them. Only multi-word stock phrases and unambiguous filler
    # tokens go here.
    "thank you.",
    "thank you",
    "all right.",
    "alright.",
    "bless you.",
    "bless you",
    "hopefully.",
    "uh.",
    "um.",
    "uh...",
    "um...",
    "uh huh.",
    "mm-hmm.",
    "mm hmm.",
    "mhm.",
    "applause",
    "laughter",
    "music",
    "music playing",
    "silence",
    "background music",
    "instrumental music",
    "soft music",
    "upbeat music",
    "dramatic music",
    "outro music",
    "intro music",
    "sigh",
    "sighs",
    "coughs",
    "coughing",
    # Italian / cross-language YouTube credit lines we saw in logs
    "sottotitoli e revisione al canale",
    "sottotitoli e revisione",
    "sottotitoli",
    "poi mencio",
    # Russian credit lines and stock fillers
    "субтитры подогнал",
    "субтитры подготовил",
    "субтитры сделал",
    "субтитры от",
    "подпишитесь на канал",
    "подписывайтесь на канал",
    "поставьте лайк и подпишитесь",
    "ставьте лайк и подписывайтесь",
    "ставьте лайки",
    "ставьте лайк",
    "не забудьте подписаться",
    "продолжение следует",
    "продолжение следует...",
    "продолжение в следующей серии",
    "до новых встреч",
    "до встречи",
    "увидимся",
    "спасибо за просмотр",
    "спасибо за внимание",
    "всем спасибо",
    "конец",
    "редактор субтитров",
    "корректор",
    "переводчик",
)


# YouTube subtitler credit lines almost always end with a SUBTITLER NAME or
# handle ("DimaTorzok", "ru.SubsCenter", "Arctic Studio", ...). Enumerating
# every name is hopeless — Whisper inherits hundreds from YouTube training
# data. Instead we match the credit-line PREFIX in several languages and
# accept anything (name, handle, URL, whitespace) as the tail.
#
# Rules of thumb to stay safe:
#   - Anchor with ^...$ so we only kill segments that are ENTIRELY a credit
#     line, not real prose that happens to contain "subtitles".
#   - Require a verb/preposition immediately after the noun, so prose like
#     "Subtitles need to be reviewed by Friday" or "Субтитры нужно проверить"
#     does not match.
#   - Case- and unicode-insensitive via re.IGNORECASE | re.UNICODE.
_CREDIT_LINE_RE: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE | re.UNICODE)
    for p in (
        # Russian verb form: "Субтитры создавал DimaTorzok", "Субтитры
        # подготовил Иван", "Субтитры от ru.SubsCenter". Verb list is broad
        # on purpose — Whisper sees dozens of variants in training data
        # ("создал/создавал/подготовил/перевёл/написал…").
        r"^\s*субтитры\s+(?:"
        r"созда(?:л|ла|ли|вал|вала|вали)|"
        r"подготовил(?:а|и)?|подгонял(?:а|и)?|подогнал(?:а|и)?|"
        r"сделал(?:а|и)?|написал(?:а|и)?|"
        r"перев(?:ё|е)л(?:а|и)?|перевод(?:чик)?|"
        r"редактор|корректор|от"
        r")\b.*$",
        # Russian separator form: "Субтитры — Arctic Studio", "Субтитры:
        # X". `\b` doesn't work after `—`/`:` (non-word→non-word), so we
        # match the separator + whitespace + at least one tail char.
        r"^\s*субтитры\s*[—–\-:]\s+\S.*$",
        # Russian: "Перевод и субтитры — X", "Перевод субтитров: X"
        r"^\s*перевод\s+(?:и\s+)?субтитр[а-я]*\b.*$",
        # Russian: standalone credit roles followed by a name
        # ("Корректор: Анна", "Редактор субтитров — X")
        r"^\s*(?:корректор|редактор\s+субтитров)\s*[:—–\-]\s*\S.*$",
        # English: "Subtitles by X", "Captions by X", "Translation by X",
        # "Transcription by X". Requires "by" immediately after — kills
        # "Subtitles by John Doe" but not "Subtitles need review by Friday".
        r"^\s*(?:subtitles|captions|transcription|translation)\s+by\b.*$",
        # German: "Untertitel von ARD", "Untertitelung durch X"
        r"^\s*untertitel(?:ung)?\s+(?:von|im\s+auftrag|der|durch)\b.*$",
        # French: "Sous-titres par X", "Sous-titres réalisés par X"
        r"^\s*sous[-\s]titres\s+(?:par|de|réalisés|effectués)\b.*$",
        # Italian: "Sottotitoli e revisione a cura di X", "Sottotitoli di X"
        r"^\s*sottotitoli\s+(?:e\s+revisione|di|a\s+cura)\b.*$",
    )
)


def _matches_credit_line(text: str) -> bool:
    """True if `text` looks like a YouTube subtitler credit line.

    Credit lines have the shape `<credit-prefix> <subtitler-name>` in many
    languages. We can't enumerate every name (hundreds in Whisper's training
    data), so we match the prefix and accept any tail.
    """
    if not text or not text.strip():
        return False
    for pat in _CREDIT_LINE_RE:
        if pat.match(text):
            return True
    return False


# Bracketed sound-effect tags Whisper emits: [Music], [Applause], (laughter),
# ♪ ... ♪ etc. We strip the whole token when it consists ONLY of bracketing
# characters, music symbols, and whitespace — i.e. there is no real letter
# or digit content inside.
_BRACKET_CONTENT_RE = re.compile(r"[A-Za-z0-9А-Яа-яЁё]", re.UNICODE)
_BRACKET_FRAME_RE = re.compile(r"^[\s\[\(<♪♫\*\.]+$", re.UNICODE)


def _is_bracketed_artifact(text: str) -> bool:
    """True if `text` is a bare sound-tag like '[Music]', '(applause)', '♪',
    '♪ ♪' — i.e. brackets / music symbols around at most one short word.
    """
    s = text.strip()
    if not s:
        return False
    # Pure bracket/music chars and whitespace, no letters at all (e.g. "♪ ♪")
    if _BRACKET_FRAME_RE.match(s):
        return True
    # Has an outer bracket pair or starts/ends with music symbol AND the
    # inner content is a single word (no spaces inside the brackets) →
    # treat as a sound tag. "[Music]", "(Applause)", "[music playing]".
    starts = s[0] in "[(<♪♫*"
    ends = s[-1] in "])>♪♫*"
    if (starts or ends):
        inner = re.sub(r"[\s\[\]\(\)<>♪♫\*\.]+", " ", s).strip()
        if not inner:
            return True
        # Whitelist of inner words that are well-known sound-tag content
        inner_l = inner.casefold()
        SOUND_TAGS = {
            "music", "music playing", "applause", "laughter", "silence",
            "background music", "instrumental", "instrumental music",
            "soft music", "upbeat music", "dramatic music", "outro music",
            "intro music", "sigh", "sighs", "cough", "coughs", "coughing",
        }
        if inner_l in SOUND_TAGS:
            return True
    return False


# Normalisation: strip punctuation, fold whitespace, case-fold. Used only
# for COMPARISON — we never mutate the user's text with it.
_NORMALISE_STRIP = re.compile(r"[\s\.\,\!\?\:\;\"'\-–—…\(\)\[\]\*♪♫]+", re.UNICODE)


def _normalise(text: str) -> str:
    """Casefold + Unicode-normalise + strip surrounding punctuation/whitespace.

    Two strings that differ only in punctuation, surrounding whitespace,
    or letter case compare equal after this. Keeps internal word
    separators (single space) so multi-word phrases still match.
    """
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text).casefold()
    # Collapse all punctuation/whitespace runs to single spaces, then trim
    t = _NORMALISE_STRIP.sub(" ", t).strip()
    return t


_NORMALISED_HALLUCINATIONS: frozenset[str] = frozenset(
    _normalise(p) for p in _HALLUCINATION_PHRASES if _normalise(p)
)


def is_hallucination(text: str) -> bool:
    """Return True if `text` is *entirely* a known Whisper hallucination.

    The check is conservative: it only matches when the WHOLE string,
    after normalisation, equals a known artifact, or when the string is
    nothing but a bracketed sound tag like "[Music]" or "♪ ... ♪".

    Real content mixed with an artifact ("Привет, thank you") does NOT
    match — use strip_hallucination_lines() for that case.
    """
    if not text or not text.strip():
        return False
    if _is_bracketed_artifact(text):
        return True
    if _matches_credit_line(text):
        return True
    return _normalise(text) in _NORMALISED_HALLUCINATIONS


# Sentence-ish split. We split on runs that end with .!? plus following space,
# OR on newlines. Keeps the original delimiters so reconstruction preserves
# spacing roughly.
_SENT_SPLIT = re.compile(r"(?<=[\.\!\?\…])\s+|\n+", re.UNICODE)


def strip_hallucination_lines(text: str) -> str:
    """Remove sentences that are entirely hallucinations; keep the rest.

    Useful when Whisper concatenates a real sentence with a stock phrase
    ("Привет всем. Thanks for watching."). The real sentence survives,
    the artifact is dropped.

    If the whole input is one hallucination → returns "".
    """
    if not text or not text.strip():
        return text
    if is_hallucination(text):
        return ""
    parts = _SENT_SPLIT.split(text)
    kept = [p for p in parts if p and not is_hallucination(p)]
    if not kept:
        return ""
    return " ".join(s.strip() for s in kept if s.strip())
