"""Regenerate all icon and sound assets from code.

Deterministic: running this twice produces byte-identical outputs.

Sound design goals (Jarvis-style):
  * Rich harmonic content — stacked sine partials with slight detune
  * Smooth ADSR envelope, no clicks
  * Ascending arpeggio for `start` ("activation")
  * Descending arpeggio for `stop`    ("deactivation")
  * A third `error` tone for failures (down-third)
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 64
SIZES = [(16, 16), (32, 32), (48, 48), (64, 64)]

SR = 44100


def _icon(color_dot: tuple[int, int, int] | None) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((22, 8, 42, 40), radius=10, fill=(40, 40, 40, 255))
    d.rectangle((30, 40, 34, 52), fill=(40, 40, 40, 255))
    d.rectangle((20, 52, 44, 56), fill=(40, 40, 40, 255))
    if color_dot is not None:
        d.ellipse((44, 8, 60, 24), fill=(*color_dot, 255))
    return img


def write_icon(name: str, dot: tuple[int, int, int] | None) -> None:
    img = _icon(dot)
    img.save(ASSETS / name, format="ICO", sizes=SIZES)


def _adsr(i: int, n: int, attack: int, release: int) -> float:
    """Linear ADSR envelope. Returns a multiplier in [0, 1]."""
    if i < attack:
        return i / attack
    if i > n - release:
        return max(0.0, (n - i) / release)
    return 1.0


def _note(freq_hz: float, duration_s: float, volume: float = 0.22,
          detune: float = 0.3) -> list[float]:
    """One note: sine fundamental + 2 detuned partials (octave, fifth)
    with ADSR. Returns a list of floats in [-1, 1]."""
    n = int(duration_s * SR)
    attack = int(0.01 * SR)       # 10 ms
    release = max(8, int(0.3 * duration_s * SR))
    out: list[float] = []
    for i in range(n):
        t = i / SR
        # fundamental + octave at 0.4 + fifth at 0.25 with slight detune
        s = (1.00 * math.sin(2 * math.pi * freq_hz * t)
             + 0.35 * math.sin(2 * math.pi * (freq_hz * 2.0 + detune) * t)
             + 0.18 * math.sin(2 * math.pi * (freq_hz * 1.5 - detune) * t))
        env = _adsr(i, n, attack, release)
        out.append(volume * env * s / 1.53)  # 1.53 = sum of partial weights
    return out


def _sequence(frequencies: list[float], note_duration_s: float,
              step_s: float, volume: float = 0.22) -> list[float]:
    """Play notes in sequence. Each note starts `step_s` after the previous,
    but notes overlap (a small chorus effect) because `note_duration_s` is
    typically larger than `step_s`."""
    step_samples = int(step_s * SR)
    total = int((len(frequencies) - 1) * step_s * SR + note_duration_s * SR) + 1
    mix = [0.0] * total
    for idx, freq in enumerate(frequencies):
        note = _note(freq, note_duration_s, volume=volume)
        offset = idx * step_samples
        for j, s in enumerate(note):
            if offset + j < total:
                mix[offset + j] += s
    # normalise to -1..1 if clipping
    peak = max((abs(s) for s in mix), default=0.0)
    if peak > 0.95:
        mix = [s * (0.95 / peak) for s in mix]
    return mix


def write_wav(path: Path, samples: list[float]) -> None:
    frames = bytearray()
    for s in samples:
        frames += struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


# Equal-tempered frequencies (A4 = 440 Hz)
def _note_hz(semitones_from_A4: int) -> float:
    return 440.0 * (2 ** (semitones_from_A4 / 12.0))


# Musical notes we use (semitones from A4)
A4 = 0
C5 = 3
E5 = 7
G5 = 10
A5 = 12
C6 = 15
E6 = 19

# Start: ascending C-E-G-C arpeggio (C major triad with top note)
START_SEQ = [C5, E5, G5, C6]
# Stop: descending C-G-E-C (same triad, reversed, one octave higher starter)
STOP_SEQ = [C6, G5, E5, C5]
# Error: down minor third (C - A♭)
ERROR_SEQ = [G5, E5 - 1]  # E♭5 = E5 - 1 semitone


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    write_icon("icon_idle.ico",      dot=None)
    write_icon("icon_recording.ico", dot=(220, 40, 40))
    write_icon("icon_busy.ico",      dot=(200, 200, 50))
    write_icon("icon_error.ico",     dot=(150, 150, 150))

    start = _sequence([_note_hz(st) for st in START_SEQ],
                      note_duration_s=0.22, step_s=0.06)
    stop = _sequence([_note_hz(st) for st in STOP_SEQ],
                     note_duration_s=0.22, step_s=0.06)
    error = _sequence([_note_hz(st) for st in ERROR_SEQ],
                      note_duration_s=0.28, step_s=0.12, volume=0.18)

    write_wav(ASSETS / "start.wav", start)
    write_wav(ASSETS / "stop.wav",  stop)
    write_wav(ASSETS / "error.wav", error)
    print(f"wrote assets to {ASSETS}")


if __name__ == "__main__":
    main()
