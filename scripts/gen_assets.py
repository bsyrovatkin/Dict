"""Regenerate all icon and sound assets from code.

Deterministic: running this twice produces byte-identical outputs.
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


def _icon(color_dot: tuple[int, int, int] | None) -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Microphone-ish body: rounded rect
    d.rounded_rectangle((22, 8, 42, 40), radius=10, fill=(40, 40, 40, 255))
    # Stand
    d.rectangle((30, 40, 34, 52), fill=(40, 40, 40, 255))
    d.rectangle((20, 52, 44, 56), fill=(40, 40, 40, 255))
    if color_dot is not None:
        d.ellipse((44, 8, 60, 24), fill=(*color_dot, 255))
    return img


def write_icon(name: str, dot: tuple[int, int, int] | None) -> None:
    img = _icon(dot)
    img.save(ASSETS / name, format="ICO", sizes=SIZES)


def write_sine_wav(path: Path, freq_hz: float, duration_s: float = 0.1,
                   volume: float = 0.25, sample_rate: int = 44100) -> None:
    n = int(duration_s * sample_rate)
    fade = 5
    frames = bytearray()
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = (n - i) / fade
        sample = volume * env * math.sin(2 * math.pi * freq_hz * i / sample_rate)
        frames += struct.pack("<h", int(sample * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(bytes(frames))


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    write_icon("icon_idle.ico",      dot=None)
    write_icon("icon_recording.ico", dot=(220, 40, 40))
    write_icon("icon_busy.ico",      dot=(200, 200, 50))
    write_icon("icon_error.ico",     dot=(150, 150, 150))
    write_sine_wav(ASSETS / "start.wav", freq_hz=880)
    write_sine_wav(ASSETS / "stop.wav",  freq_hz=440)
    print(f"wrote assets to {ASSETS}")


if __name__ == "__main__":
    main()
