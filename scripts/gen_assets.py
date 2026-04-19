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

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SIZE = 256
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

SR = 44100

# Jarvis palette (RGB tuples)
CYAN        = (0,   229, 255)
CYAN_BRIGHT = (120, 245, 255)
CYAN_DIM    = (0,   145, 168)
RED         = (255, 59,  92)
YELLOW      = (255, 204, 0)
GREY        = (110, 130, 140)


def _draw_mic_icon(accent: tuple[int, int, int],
                   recording: bool = False) -> Image.Image:
    """High-res mic icon. Glow ring in `accent`, mic body outline,
    indicator dot shows state. Designed for sharp downsampling to 16px+."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    cx, cy = SIZE // 2, SIZE // 2

    # Outer glow ring (blurred afterwards)
    gd = ImageDraw.Draw(glow)
    for r, alpha in ((SIZE // 2 - 8, 160), (SIZE // 2 - 16, 90), (SIZE // 2 - 24, 50)):
        gd.ellipse((cx - r, cy - r, cx + r, cy + r),
                   outline=(*accent, alpha), width=4)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=6))

    d = ImageDraw.Draw(img)

    # Outer circle (solid thin cyan)
    r_outer = SIZE // 2 - 10
    d.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer),
              outline=(*accent, 255), width=4)

    # Tick marks at cardinal points
    tick_r1 = r_outer - 6
    tick_r2 = r_outer - 20
    for deg in (0, 90, 180, 270):
        a = math.radians(deg)
        x1 = cx + tick_r1 * math.cos(a)
        y1 = cy + tick_r1 * math.sin(a)
        x2 = cx + tick_r2 * math.cos(a)
        y2 = cy + tick_r2 * math.sin(a)
        d.line((x1, y1, x2, y2), fill=(*accent, 255), width=3)

    # Microphone body — capsule
    mic_top = int(SIZE * 0.28)
    mic_bot = int(SIZE * 0.58)
    mic_left = int(SIZE * 0.42)
    mic_right = int(SIZE * 0.58)
    mic_width = mic_right - mic_left
    d.rounded_rectangle(
        (mic_left, mic_top, mic_right, mic_bot),
        radius=mic_width // 2,
        fill=(*accent, 255) if recording else (0, 0, 0, 0),
        outline=(*accent, 255),
        width=5,
    )

    # U-shaped mic stand arc
    stand_r = int(SIZE * 0.18)
    stand_box = (cx - stand_r, cy - stand_r // 2, cx + stand_r, cy + stand_r * 2 - 8)
    d.arc(stand_box, start=20, end=160, fill=(*accent, 255), width=5)
    # Vertical stem
    d.line((cx, mic_bot + 8, cx, mic_bot + int(SIZE * 0.12)),
           fill=(*accent, 255), width=5)
    # Base
    base_w = int(SIZE * 0.12)
    d.line((cx - base_w, mic_bot + int(SIZE * 0.12),
            cx + base_w, mic_bot + int(SIZE * 0.12)),
           fill=(*accent, 255), width=5)

    # Composite glow behind, icon on top
    out = Image.alpha_composite(glow, img)
    return out


def write_icon(name: str, accent: tuple[int, int, int], recording: bool = False) -> None:
    img = _draw_mic_icon(accent, recording=recording)
    img.save(ASSETS / name, format="ICO", sizes=ICO_SIZES)
    # Also save a PNG for easy preview / GitHub README
    png_name = name.replace(".ico", ".png")
    img.save(ASSETS / png_name, format="PNG")


def _draw_gear(size: int = 64, accent: tuple[int, int, int] = CYAN) -> Image.Image:
    """Minimalist gear icon for the settings button."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    cx = cy = size / 2

    outer_r = size * 0.42
    inner_r = size * 0.30
    hole_r = size * 0.14
    teeth = 8

    # Glow layer
    gd = ImageDraw.Draw(glow)
    gd.ellipse((cx - outer_r - 2, cy - outer_r - 2, cx + outer_r + 2, cy + outer_r + 2),
               outline=(*accent, 140), width=3)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=2))

    d = ImageDraw.Draw(img)

    # Teeth as small squares around the perimeter
    for i in range(teeth):
        a = 2 * math.pi * i / teeth
        r = outer_r
        w = size * 0.08
        x = cx + r * math.cos(a)
        y = cy + r * math.sin(a)
        d.rectangle((x - w / 2, y - w / 2, x + w / 2, y + w / 2),
                    fill=(*accent, 255))

    # Ring body
    d.ellipse((cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r),
              outline=(*accent, 255), width=int(size * 0.06))
    # Center hole
    d.ellipse((cx - hole_r, cy - hole_r, cx + hole_r, cy + hole_r),
              fill=(0, 0, 0, 0), outline=(*accent, 255), width=int(size * 0.04))

    return Image.alpha_composite(glow, img)


def write_gear_png(name: str = "icon_gear.png", size: int = 64,
                   accent: tuple[int, int, int] = CYAN) -> None:
    img = _draw_gear(size, accent)
    img.save(ASSETS / name, format="PNG")


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

    # Neon mic icons — state tint matches app palette
    write_icon("icon_idle.ico",      accent=CYAN,   recording=False)
    write_icon("icon_recording.ico", accent=RED,    recording=True)
    write_icon("icon_busy.ico",      accent=YELLOW, recording=False)
    write_icon("icon_error.ico",     accent=GREY,   recording=False)

    # Settings gear (used by the ⚙ button in the window header)
    write_gear_png("icon_gear.png", size=32, accent=CYAN)
    # Larger variant for HiDPI / docs
    write_gear_png("icon_gear@2x.png", size=64, accent=CYAN)

    # Bundled favicon — same as idle mic
    write_icon("dict.ico", accent=CYAN, recording=False)

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
