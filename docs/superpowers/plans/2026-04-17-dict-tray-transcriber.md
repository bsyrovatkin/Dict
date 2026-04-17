# Dict Tray Transcriber Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Windows tray utility that records audio on `Win+B`, transcribes Russian/English speech with local `faster-whisper small`, and drops the text into the clipboard while keeping a small visible history.

**Architecture:** Single Python process. `pystray` tray + `tkinter` history window run on the main thread. A `Controller` state machine (`idle → recording → transcribing → idle`) orchestrates `Recorder` (sounddevice), `Transcriber` (faster-whisper in a worker thread), `Clipboard`, `Logger`, `History`, and `Sounds`. `HotkeyWatcher` (pynput) posts toggle commands via a thread-safe queue.

**Tech Stack:** Python 3.10+, `faster-whisper`, `sounddevice`, `numpy`, `pynput`, `pystray`, `pillow`, `pyperclip`. Stdlib: `tkinter`, `winsound`, `queue`, `threading`, `msvcrt`.

**Spec:** [`docs/superpowers/specs/2026-04-17-dict-tray-transcriber-design.md`](../specs/2026-04-17-dict-tray-transcriber-design.md)

---

## Task 1: Project scaffolding

**Files:**
- Create: `D:/Projects/Dict/pyproject.toml`
- Create: `D:/Projects/Dict/.gitignore`
- Create: `D:/Projects/Dict/README.md`
- Create: `D:/Projects/Dict/launch.bat`
- Create: `D:/Projects/Dict/dict/__init__.py`
- Create: `D:/Projects/Dict/tests/__init__.py`
- Create: `D:/Projects/Dict/assets/.gitkeep`

- [ ] **Step 1: Initialize git repository**

```bash
cd "D:/Projects/Dict" && git init && git config user.email "bsyrovatkin@gmail.com" && git config user.name "bsyrovatkin"
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.venv/
venv/
dist/
build/
*.egg-info/
dict.log
*.tmp
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[project]
name = "dict"
version = "0.1.0"
description = "Tray-resident voice-to-clipboard transcriber for Windows"
requires-python = ">=3.10"
dependencies = [
  "faster-whisper>=1.0.3",
  "sounddevice>=0.4.6",
  "numpy>=1.26,<2.3",
  "pynput>=1.7.7",
  "pystray>=0.19.5",
  "pillow>=10.3.0",
  "pyperclip>=1.9.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-mock>=3.12"]

[project.scripts]
dict = "dict.__main__:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["dict*"]

[tool.pytest.ini_options]
markers = ["slow: integration tests that load models or touch audio hardware"]
addopts = "-m 'not slow'"
```

- [ ] **Step 4: Write `launch.bat`**

```bat
@echo off
cd /d "%~dp0"
python -m dict
```

- [ ] **Step 5: Write `README.md`**

```markdown
# Dict

Tray-resident voice-to-clipboard transcriber for Windows. Press `Win+B` to start recording, press again to stop — the transcription lands in your clipboard and a small history window.

## Install

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

First launch downloads `faster-whisper small` (~470 MB) into the Hugging Face cache.

## Run

Double-click `launch.bat` or `python -m dict`.

## Manual smoke test

1. Launch. Tray icon appears.
2. `Win+B`, say "проверка связи", `Win+B`.
3. Start/stop sounds play. History window appears for ~2 s. Clipboard contains the text. `dict.log` has a new line.
4. Click tray icon — window toggles. Click a history row — clipboard re-updated.
5. Launch a second instance — it exits with "Dict already running".
```

- [ ] **Step 6: Create empty package markers**

Create `dict/__init__.py`, `tests/__init__.py`, `assets/.gitkeep` — all empty files.

- [ ] **Step 7: Verify Python and install**

```bash
cd "D:/Projects/Dict" && python --version && python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
```
Expected: clean install, no errors.

- [ ] **Step 8: Commit**

```bash
cd "D:/Projects/Dict" && git add pyproject.toml .gitignore README.md launch.bat dict/ tests/ assets/ docs/ && git commit -m "chore: scaffold dict tray transcriber project"
```

---

## Task 2: `config.py` constants

**Files:**
- Create: `D:/Projects/Dict/dict/config.py`

- [ ] **Step 1: Write `dict/config.py`**

```python
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
SILENCE_RMS_INT16 = 200    # ≈ -44 dBFS; recordings quieter than this are dropped

# Whisper
MODEL_SIZE = "small"       # multilingual
LANGUAGE: str | None = None  # auto-detect
BEAM_SIZE = 5

# Hotkey (pynput GlobalHotKeys format)
HOTKEY = "<cmd>+b"         # <cmd> = Windows key on Windows

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
```

- [ ] **Step 2: Verify import**

```bash
cd "D:/Projects/Dict" && .venv/Scripts/python -c "from dict import config; print(config.SAMPLE_RATE, config.HOTKEY)"
```
Expected: `16000 <cmd>+b`

- [ ] **Step 3: Commit**

```bash
git add dict/config.py && git commit -m "feat: add config constants"
```

---

## Task 3: `history.py` — TDD

**Files:**
- Create: `D:/Projects/Dict/tests/test_history.py`
- Create: `D:/Projects/Dict/dict/history.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_history.py`:

```python
from __future__ import annotations

from datetime import datetime

from dict.history import History, Entry


def test_push_stores_entry_with_timestamp():
    h = History(maxlen=5)
    before = datetime.now()
    h.push("hello")
    after = datetime.now()
    items = h.items()
    assert len(items) == 1
    assert items[0].text == "hello"
    assert before <= items[0].timestamp <= after


def test_items_returns_newest_first():
    h = History(maxlen=5)
    h.push("first")
    h.push("second")
    h.push("third")
    texts = [e.text for e in h.items()]
    assert texts == ["third", "second", "first"]


def test_maxlen_evicts_oldest():
    h = History(maxlen=3)
    for t in ["a", "b", "c", "d", "e"]:
        h.push(t)
    texts = [e.text for e in h.items()]
    assert texts == ["e", "d", "c"]


def test_entry_is_immutable_namedtuple():
    # Entry instances are value objects; never mutated in place.
    e = Entry(timestamp=datetime.now(), text="x")
    import pytest
    with pytest.raises(AttributeError):
        e.text = "y"  # type: ignore[misc]
```

- [ ] **Step 2: Run and verify failure**

```bash
cd "D:/Projects/Dict" && .venv/Scripts/python -m pytest tests/test_history.py -v
```
Expected: FAIL, `ModuleNotFoundError: No module named 'dict.history'`.

- [ ] **Step 3: Implement `dict/history.py`**

```python
"""Bounded most-recent-first history of transcriptions."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Entry:
    timestamp: datetime
    text: str


class History:
    def __init__(self, maxlen: int) -> None:
        self._items: deque[Entry] = deque(maxlen=maxlen)

    def push(self, text: str) -> Entry:
        entry = Entry(timestamp=datetime.now(), text=text)
        self._items.append(entry)
        return entry

    def items(self) -> list[Entry]:
        """Return entries newest-first."""
        return list(reversed(self._items))
```

- [ ] **Step 4: Run and verify passes**

```bash
.venv/Scripts/python -m pytest tests/test_history.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add dict/history.py tests/test_history.py && git commit -m "feat: add bounded History with Entry value objects"
```

---

## Task 4: `logger.py` — TDD

**Files:**
- Create: `D:/Projects/Dict/tests/test_logger.py`
- Create: `D:/Projects/Dict/dict/logger.py`

- [ ] **Step 1: Write failing test**

```python
from __future__ import annotations

import re
from pathlib import Path

from dict.logger import append


LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \| .+\n$")


def test_append_creates_file_and_writes_formatted_line(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("hello world", path=log)
    content = log.read_text(encoding="utf-8")
    assert LINE_RE.match(content), f"bad line: {content!r}"
    assert "hello world" in content


def test_append_is_append_only(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("one", path=log)
    append("two", path=log)
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("| one")
    assert lines[1].endswith("| two")


def test_append_creates_parent_dir(tmp_path: Path):
    log = tmp_path / "nested" / "dict.log"
    append("x", path=log)
    assert log.exists()


def test_newlines_in_text_are_escaped(tmp_path: Path):
    log = tmp_path / "dict.log"
    append("line1\nline2", path=log)
    content = log.read_text(encoding="utf-8")
    assert content.count("\n") == 1  # only the trailing newline
    assert "line1\\nline2" in content
```

- [ ] **Step 2: Run and verify failure**

```bash
.venv/Scripts/python -m pytest tests/test_logger.py -v
```
Expected: FAIL, no module.

- [ ] **Step 3: Implement `dict/logger.py`**

```python
"""Append-only plain-text transcription log."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from dict import config


def append(text: str, path: Path | None = None) -> None:
    """Append one `YYYY-MM-DD HH:MM:SS | <text>` line.

    Newlines inside `text` are escaped so each record stays on one line.
    """
    target = path if path is not None else config.LOG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    safe = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    with target.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp} | {safe}\n")
```

- [ ] **Step 4: Run and verify passes**

```bash
.venv/Scripts/python -m pytest tests/test_logger.py -v
```
Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add dict/logger.py tests/test_logger.py && git commit -m "feat: add append-only transcription logger"
```

---

## Task 5: `clipboard.py` thin wrapper

**Files:**
- Create: `D:/Projects/Dict/dict/clipboard.py`
- Create: `D:/Projects/Dict/tests/test_clipboard.py`

- [ ] **Step 1: Write test**

```python
from __future__ import annotations

from dict import clipboard


def test_set_text_calls_pyperclip(mocker):
    copy = mocker.patch("dict.clipboard.pyperclip.copy")
    ok = clipboard.set_text("hi")
    assert ok is True
    copy.assert_called_once_with("hi")


def test_set_text_returns_false_on_failure(mocker):
    mocker.patch("dict.clipboard.pyperclip.copy", side_effect=RuntimeError("nope"))
    ok = clipboard.set_text("hi")
    assert ok is False
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/Scripts/python -m pytest tests/test_clipboard.py -v
```
Expected: FAIL, no module.

- [ ] **Step 3: Implement `dict/clipboard.py`**

```python
"""Clipboard wrapper that never raises — failures are reported via bool."""
from __future__ import annotations

import pyperclip

from dict.utils_logging import get_logger

log = get_logger(__name__)


def set_text(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except Exception:  # pyperclip errors are unpredictable across platforms
        log.exception("clipboard write failed")
        return False
```

- [ ] **Step 4: Add `dict/utils_logging.py` helper**

`dict/utils_logging.py`:

```python
"""Thin wrapper around stdlib logging so every module looks the same."""
from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

- [ ] **Step 5: Run and verify passes**

```bash
.venv/Scripts/python -m pytest tests/test_clipboard.py -v
```
Expected: 2 pass.

- [ ] **Step 6: Commit**

```bash
git add dict/clipboard.py dict/utils_logging.py tests/test_clipboard.py && git commit -m "feat: add clipboard wrapper and logging helper"
```

---

## Task 6: Generate icons and sound files

**Files:**
- Create: `D:/Projects/Dict/scripts/gen_assets.py`
- Create: `D:/Projects/Dict/assets/icon_idle.ico`
- Create: `D:/Projects/Dict/assets/icon_recording.ico`
- Create: `D:/Projects/Dict/assets/icon_busy.ico`
- Create: `D:/Projects/Dict/assets/icon_error.ico`
- Create: `D:/Projects/Dict/assets/start.wav`
- Create: `D:/Projects/Dict/assets/stop.wav`

- [ ] **Step 1: Write asset generator**

`scripts/gen_assets.py`:

```python
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
    # 5-sample linear fade-in/out to avoid clicks
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
    write_icon("icon_recording.ico", dot=(220, 40, 40))    # red
    write_icon("icon_busy.ico",      dot=(200, 200, 50))   # yellow
    write_icon("icon_error.ico",     dot=(150, 150, 150))  # grey
    write_sine_wav(ASSETS / "start.wav", freq_hz=880)
    write_sine_wav(ASSETS / "stop.wav",  freq_hz=440)
    print(f"wrote assets to {ASSETS}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the generator**

```bash
cd "D:/Projects/Dict" && .venv/Scripts/python scripts/gen_assets.py
```
Expected: prints `wrote assets to ...`, 4 `.ico` + 2 `.wav` in `assets/`.

- [ ] **Step 3: Verify files**

```bash
ls assets/
```
Expected: `icon_busy.ico icon_error.ico icon_idle.ico icon_recording.ico start.wav stop.wav .gitkeep`.

- [ ] **Step 4: Commit**

```bash
git add scripts/gen_assets.py assets/ && git commit -m "feat: generate tray icons and start/stop sounds"
```

---

## Task 7: `sounds.py` — Windows WAV playback

**Files:**
- Create: `D:/Projects/Dict/dict/sounds.py`

- [ ] **Step 1: Implement `dict/sounds.py`**

```python
"""Asynchronous WAV playback via winsound (Windows-only)."""
from __future__ import annotations

import winsound

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


def _play(name: str) -> None:
    path = config.ASSETS_DIR / config.SOUND_FILES[name]
    if not path.exists():
        log.warning("sound %s not found at %s", name, path)
        return
    try:
        # SND_ASYNC: return immediately; SND_FILENAME: treat as path; SND_NODEFAULT: silent if missing.
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        log.exception("failed to play %s", name)


def play_start() -> None:
    _play("start")


def play_stop() -> None:
    _play("stop")
```

- [ ] **Step 2: Manual smoke test**

```bash
.venv/Scripts/python -c "from dict import sounds; sounds.play_start(); import time; time.sleep(0.3); sounds.play_stop(); time.sleep(0.3)"
```
Expected: two short beeps, no errors. (If no audio output, that's a hardware issue, not a code issue.)

- [ ] **Step 3: Commit**

```bash
git add dict/sounds.py && git commit -m "feat: add WAV playback for start/stop cues"
```

---

## Task 8: `recorder.py` — sounddevice capture

**Files:**
- Create: `D:/Projects/Dict/dict/recorder.py`
- Create: `D:/Projects/Dict/tests/test_recorder.py`

- [ ] **Step 1: Write tests that isolate the buffer-assembly logic**

`tests/test_recorder.py`:

```python
from __future__ import annotations

import numpy as np

from dict.recorder import should_drop_recording


def test_drops_too_short():
    audio = np.zeros(int(16000 * 0.3), dtype=np.int16)  # 0.3s
    assert should_drop_recording(audio, sample_rate=16000) is True


def test_drops_silent_but_long_enough():
    audio = np.zeros(int(16000 * 1.0), dtype=np.int16)
    assert should_drop_recording(audio, sample_rate=16000) is True


def test_keeps_long_enough_and_loud_enough():
    # 1 second of full-scale tone → RMS ≈ 23170
    t = np.arange(16000) / 16000
    audio = (0.9 * 32767 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)
    assert should_drop_recording(audio, sample_rate=16000) is False


def test_drops_empty_array():
    assert should_drop_recording(np.zeros(0, dtype=np.int16), sample_rate=16000) is True
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/Scripts/python -m pytest tests/test_recorder.py -v
```
Expected: FAIL, no module.

- [ ] **Step 3: Implement `dict/recorder.py`**

```python
"""Microphone capture using sounddevice.

The sounddevice callback fires on a dedicated thread owned by PortAudio,
so we guard the chunk list with a lock.
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np
import sounddevice as sd

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


def should_drop_recording(audio: np.ndarray, sample_rate: int) -> bool:
    if audio.size == 0:
        return True
    if audio.size < int(sample_rate * config.MIN_RECORDING_SEC):
        return True
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) if audio.size else 0.0
    if rms < config.SILENCE_RMS_INT16:
        return True
    return False


class RecorderError(RuntimeError):
    pass


class Recorder:
    def __init__(self, sample_rate: int = config.SAMPLE_RATE) -> None:
        self._sample_rate = sample_rate
        self._stream: Optional[sd.InputStream] = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._stream is not None:
            raise RecorderError("already recording")
        self._chunks = []
        try:
            self._stream = sd.InputStream(
                samplerate=self._sample_rate,
                channels=config.CHANNELS,
                dtype=config.DTYPE,
                callback=self._on_audio,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise RecorderError(f"could not open input stream: {exc}") from exc

    def stop(self) -> Optional[np.ndarray]:
        """Stop the stream and return the recording, or `None` if it
        should be dropped (too short / silent)."""
        if self._stream is None:
            return None
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None
        with self._lock:
            chunks = list(self._chunks)
            self._chunks = []
        if not chunks:
            return None
        audio = np.concatenate(chunks).reshape(-1)
        if should_drop_recording(audio, self._sample_rate):
            return None
        return audio

    def _on_audio(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            log.warning("input stream status: %s", status)
        # indata dtype matches config.DTYPE (int16); copy to detach from PortAudio buffer.
        with self._lock:
            self._chunks.append(indata.copy().reshape(-1))
```

- [ ] **Step 4: Run and verify tests pass**

```bash
.venv/Scripts/python -m pytest tests/test_recorder.py -v
```
Expected: 4 pass.

- [ ] **Step 5: Manual smoke — record 2 seconds**

```bash
.venv/Scripts/python -c "from dict.recorder import Recorder; import time; r=Recorder(); r.start(); print('speak...'); time.sleep(2); a=r.stop(); print('samples:', None if a is None else a.shape)"
```
Expected: `speak...` then `samples: (32000,)` (give or take). If `None`, speak louder.

- [ ] **Step 6: Commit**

```bash
git add dict/recorder.py tests/test_recorder.py && git commit -m "feat: add microphone recorder with silence/min-length guard"
```

---

## Task 9: `transcriber.py` — faster-whisper wrapper

**Files:**
- Create: `D:/Projects/Dict/dict/transcriber.py`
- Create: `D:/Projects/Dict/tests/test_transcriber_smoke.py`

- [ ] **Step 1: Implement `dict/transcriber.py`**

```python
"""faster-whisper wrapper with CUDA auto-probe and lazy model load."""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)

_MIN_CUDA_VRAM_BYTES = 4 * (1024 ** 3)


def probe_cuda() -> tuple[str, str]:
    """Return (device, compute_type). CUDA needs ≥4 GB VRAM; otherwise CPU int8."""
    fallback = ("cpu", "int8")
    try:
        import torch  # type: ignore[import]
    except Exception:
        return fallback
    try:
        if not torch.cuda.is_available() or torch.cuda.device_count() <= 0:
            return fallback
        props = torch.cuda.get_device_properties(0)
        if int(getattr(props, "total_memory", 0)) < _MIN_CUDA_VRAM_BYTES:
            return fallback
        return ("cuda", "float16")
    except Exception:
        return fallback


class TranscriberError(RuntimeError):
    pass


class Transcriber:
    def __init__(self, model_size: str = config.MODEL_SIZE) -> None:
        self._model_size = model_size
        self._model: object | None = None
        self._load_lock = threading.Lock()

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

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe int16 mono audio at 16 kHz. Returns empty string if no speech."""
        self.ensure_loaded()
        assert self._model is not None
        # faster-whisper wants float32 in [-1, 1]
        audio_f32 = (audio.astype(np.float32) / 32768.0)
        segments, info = self._model.transcribe(  # type: ignore[attr-defined]
            audio_f32,
            language=config.LANGUAGE,
            beam_size=config.BEAM_SIZE,
            vad_filter=True,
        )
        parts = [seg.text.strip() for seg in segments]
        text = " ".join(p for p in parts if p).strip()
        log.info("transcribed lang=%s duration=%.2fs -> %d chars",
                 info.language, info.duration, len(text))
        return text
```

- [ ] **Step 2: Write smoke test (marked slow)**

`tests/test_transcriber_smoke.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from dict.transcriber import Transcriber


@pytest.mark.slow
def test_transcribe_silent_array_returns_empty():
    t = Transcriber()
    audio = np.zeros(16000 * 2, dtype=np.int16)
    result = t.transcribe(audio)
    assert result == ""


@pytest.mark.slow
def test_transcribe_tone_returns_some_string_not_crash():
    t = Transcriber()
    samples = (0.5 * 32767 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)).astype(np.int16)
    # no speech → probably empty, but must not raise
    result = t.transcribe(samples)
    assert isinstance(result, str)
```

- [ ] **Step 3: Run regular (non-slow) tests**

```bash
.venv/Scripts/python -m pytest -v
```
Expected: all existing tests pass; slow tests skipped.

- [ ] **Step 4: Optional — run smoke test manually**

```bash
.venv/Scripts/python -m pytest tests/test_transcriber_smoke.py -v -m slow
```
First run downloads the model (~470 MB). Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add dict/transcriber.py tests/test_transcriber_smoke.py && git commit -m "feat: add faster-whisper transcriber with CUDA auto-probe"
```

---

## Task 10: `hotkey.py` — global hotkey

**Files:**
- Create: `D:/Projects/Dict/dict/hotkey.py`

- [ ] **Step 1: Implement `dict/hotkey.py`**

```python
"""Global hotkey listener via pynput."""
from __future__ import annotations

from typing import Callable, Optional

from pynput import keyboard

from dict.utils_logging import get_logger

log = get_logger(__name__)


class HotkeyWatcher:
    def __init__(self, combo: str, on_trigger: Callable[[], None]) -> None:
        self._combo = combo
        self._on_trigger = on_trigger
        self._listener: Optional[keyboard.GlobalHotKeys] = None

    def start(self) -> None:
        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys({self._combo: self._on_fire})
        self._listener.start()
        log.info("hotkey %s registered", self._combo)

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None

    def _on_fire(self) -> None:
        try:
            self._on_trigger()
        except Exception:
            log.exception("hotkey handler raised")
```

- [ ] **Step 2: Manual smoke test**

```bash
.venv/Scripts/python -c "from dict.hotkey import HotkeyWatcher; import time; w=HotkeyWatcher('<cmd>+b', lambda: print('FIRED')); w.start(); print('press Win+B within 10s'); time.sleep(10); w.stop()"
```
Press `Win+B` during the 10 s window. Expected: `FIRED` printed each time.

- [ ] **Step 3: Commit**

```bash
git add dict/hotkey.py && git commit -m "feat: add global hotkey listener"
```

---

## Task 11: `tray.py` — system tray icon

**Files:**
- Create: `D:/Projects/Dict/dict/tray.py`

- [ ] **Step 1: Implement `dict/tray.py`**

```python
"""System tray icon wrapper around pystray."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import pystray
from PIL import Image

from dict import config
from dict.utils_logging import get_logger

log = get_logger(__name__)


class Tray:
    def __init__(
        self,
        on_left_click: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_left_click = on_left_click
        self._on_quit = on_quit
        self._images: dict[str, Image.Image] = {
            state: Image.open(config.ASSETS_DIR / filename)
            for state, filename in config.ICON_FILES.items()
        }
        self._icon = pystray.Icon(
            name="dict",
            icon=self._images["idle"],
            title="Dict — voice transcriber",
            menu=pystray.Menu(
                pystray.MenuItem("Show/hide", self._handle_click, default=True, visible=False),
                pystray.MenuItem("Quit", self._handle_quit),
            ),
        )

    def set_state(self, state: str) -> None:
        img = self._images.get(state)
        if img is None:
            log.warning("unknown tray state %s", state)
            return
        self._icon.icon = img

    def run(self) -> None:
        # Blocking: must be called on the main thread (Windows requirement).
        self._icon.run()

    def stop(self) -> None:
        self._icon.stop()

    def _handle_click(self, icon, item) -> None:
        try:
            self._on_left_click()
        except Exception:
            log.exception("tray click handler raised")

    def _handle_quit(self, icon, item) -> None:
        try:
            self._on_quit()
        finally:
            icon.stop()

    def notify(self, title: str, message: str) -> None:
        try:
            self._icon.notify(message, title)
        except Exception:
            log.exception("tray notify failed")
```

- [ ] **Step 2: Manual smoke test**

```bash
.venv/Scripts/python -c "from dict.tray import Tray; t=Tray(lambda: print('click'), lambda: print('quit')); import threading,time; threading.Thread(target=lambda:(time.sleep(3), t.set_state('recording'), time.sleep(2), t.stop()), daemon=True).start(); t.run()"
```
Expected: tray icon appears, switches to recording after 3 s, disappears after 5 s.

- [ ] **Step 3: Commit**

```bash
git add dict/tray.py && git commit -m "feat: add pystray-based tray icon"
```

---

## Task 12: `window.py` — history window

**Files:**
- Create: `D:/Projects/Dict/dict/window.py`

- [ ] **Step 1: Implement `dict/window.py`**

```python
"""tkinter history window.

The tkinter event loop runs in its own thread so the pystray main loop
on the main thread is not blocked. All Tk calls must go through
`schedule()` (Tk objects are not thread-safe)."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from dict import config
from dict.history import Entry, History
from dict.utils_logging import get_logger

log = get_logger(__name__)


class HistoryWindow:
    def __init__(self, history: History, on_copy: Callable[[str], None]) -> None:
        self._history = history
        self._on_copy = on_copy
        self._root: tk.Tk | None = None
        self._listbox: tk.Listbox | None = None
        self._hide_after_id: str | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tk-ui", daemon=True)

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(timeout=5)

    def _run(self) -> None:
        root = tk.Tk()
        root.title("Dict — history")
        root.geometry("420x180")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self._hide_now)

        listbox = tk.Listbox(root, activestyle="dotbox", font=("Segoe UI", 10))
        listbox.pack(fill="both", expand=True, padx=6, pady=6)
        listbox.bind("<<ListboxSelect>>", self._on_select)
        listbox.bind("<Double-Button-1>", self._on_select)

        self._root = root
        self._listbox = listbox
        root.withdraw()  # start hidden
        self._ready.set()
        root.mainloop()

    def schedule(self, fn: Callable[[], None]) -> None:
        if self._root is None:
            return
        self._root.after(0, fn)

    def refresh(self) -> None:
        self.schedule(self._refresh_now)

    def _refresh_now(self) -> None:
        if self._listbox is None:
            return
        self._listbox.delete(0, tk.END)
        for entry in self._history.items():
            line = f"[{entry.timestamp.strftime('%H:%M:%S')}]  {entry.text}"
            self._listbox.insert(tk.END, line)

    def toggle(self) -> None:
        self.schedule(self._toggle_now)

    def _toggle_now(self) -> None:
        if self._root is None:
            return
        if self._root.state() == "withdrawn":
            self._show_now()
        else:
            self._hide_now()

    def show_for(self, seconds: float) -> None:
        self.schedule(lambda: self._show_for_now(seconds))

    def _show_for_now(self, seconds: float) -> None:
        if self._root is None:
            return
        self._show_now()
        if self._hide_after_id is not None:
            self._root.after_cancel(self._hide_after_id)
        self._hide_after_id = self._root.after(int(seconds * 1000), self._hide_now)

    def _show_now(self) -> None:
        if self._root is None:
            return
        self._root.deiconify()
        self._root.lift()
        self._root.focus_force()

    def _hide_now(self) -> None:
        if self._root is None:
            return
        self._root.withdraw()

    def _on_select(self, _event) -> None:
        if self._listbox is None:
            return
        idx = self._listbox.curselection()
        if not idx:
            return
        entries = self._history.items()
        i = idx[0]
        if 0 <= i < len(entries):
            self._on_copy(entries[i].text)

    def stop(self) -> None:
        self.schedule(self._stop_now)

    def _stop_now(self) -> None:
        if self._root is not None:
            self._root.quit()
            self._root.destroy()
            self._root = None
```

- [ ] **Step 2: Manual smoke test**

```bash
.venv/Scripts/python -c "from dict.history import History; from dict.window import HistoryWindow; import time; h=History(5); h.push('привет мир'); h.push('second'); w=HistoryWindow(h, print); w.start(); w.refresh(); w.show_for(3); time.sleep(4); w.stop()"
```
Expected: window pops up for ~3 s showing two entries, then hides.

- [ ] **Step 3: Commit**

```bash
git add dict/window.py && git commit -m "feat: add tkinter history window"
```

---

## Task 13: `controller.py` — state machine (TDD with mocks)

**Files:**
- Create: `D:/Projects/Dict/tests/test_controller.py`
- Create: `D:/Projects/Dict/dict/controller.py`

- [ ] **Step 1: Write failing tests**

`tests/test_controller.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from dict.controller import Controller, State


@pytest.fixture
def mocks():
    return {
        "recorder":    MagicMock(),
        "transcriber": MagicMock(),
        "tray":        MagicMock(),
        "window":      MagicMock(),
        "history":     MagicMock(),
        "sounds":      MagicMock(),
        "clipboard":   MagicMock(),
        "logger":      MagicMock(),
    }


def make_controller(mocks, run_worker_inline: bool = True) -> Controller:
    # Run the transcriber worker synchronously inside the test thread
    # so we can assert its outcome without sleeping.
    def spawn(target):
        if run_worker_inline:
            target()
        # otherwise drop on the floor — used for concurrency tests
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
        spawn=spawn,
    )


def test_starts_idle(mocks):
    c = make_controller(mocks)
    assert c.state is State.IDLE


def test_first_trigger_starts_recording(mocks):
    c = make_controller(mocks)
    c.on_hotkey()
    assert c.state is State.RECORDING
    mocks["recorder"].start.assert_called_once()
    mocks["sounds"].play_start.assert_called_once()
    mocks["tray"].set_state.assert_any_call("recording")


def test_second_trigger_transcribes_and_returns_to_idle(mocks):
    audio = np.ones(32000, dtype=np.int16)
    mocks["recorder"].stop.return_value = audio
    mocks["transcriber"].transcribe.return_value = "проверка"

    c = make_controller(mocks)
    c.on_hotkey()  # start
    c.on_hotkey()  # stop + transcribe (inline worker)

    mocks["recorder"].stop.assert_called_once()
    mocks["sounds"].play_stop.assert_called_once()
    mocks["transcriber"].transcribe.assert_called_once_with(audio)
    mocks["history"].push.assert_called_once_with("проверка")
    mocks["clipboard"].assert_called_once_with("проверка")
    mocks["logger"].assert_called_once_with("проверка")
    mocks["window"].refresh.assert_called_once()
    mocks["window"].show_for.assert_called_once()
    mocks["tray"].set_state.assert_any_call("idle")
    assert c.state is State.IDLE


def test_empty_recording_is_dropped_silently(mocks):
    mocks["recorder"].stop.return_value = None
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()

    mocks["transcriber"].transcribe.assert_not_called()
    mocks["history"].push.assert_not_called()
    mocks["clipboard"].assert_not_called()
    mocks["logger"].assert_not_called()
    mocks["sounds"].play_stop.assert_called_once()
    assert c.state is State.IDLE


def test_empty_transcription_is_dropped(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["transcriber"].transcribe.return_value = "   "
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()

    mocks["history"].push.assert_not_called()
    mocks["clipboard"].assert_not_called()
    mocks["logger"].assert_not_called()
    assert c.state is State.IDLE


def test_hotkey_ignored_while_transcribing(mocks):
    # With spawn that does NOT run the worker, the state stays TRANSCRIBING.
    c = make_controller(mocks, run_worker_inline=False)
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    c.on_hotkey()  # → RECORDING
    c.on_hotkey()  # → TRANSCRIBING (worker not run)
    assert c.state is State.TRANSCRIBING
    c.on_hotkey()  # should be ignored
    assert c.state is State.TRANSCRIBING


def test_transcriber_exception_returns_to_idle(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["transcriber"].transcribe.side_effect = RuntimeError("boom")
    c = make_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    assert c.state is State.IDLE
    mocks["tray"].set_state.assert_any_call("idle")
    mocks["history"].push.assert_not_called()


def test_recorder_start_failure_returns_to_idle(mocks):
    mocks["recorder"].start.side_effect = RuntimeError("no mic")
    c = make_controller(mocks)
    c.on_hotkey()
    assert c.state is State.IDLE
    mocks["tray"].set_state.assert_any_call("error")
```

- [ ] **Step 2: Run, expect failure**

```bash
.venv/Scripts/python -m pytest tests/test_controller.py -v
```
Expected: FAIL, no module.

- [ ] **Step 3: Implement `dict/controller.py`**

```python
"""State machine tying together recorder, transcriber, tray, window, history."""
from __future__ import annotations

import enum
import threading
from typing import Callable, Protocol

import numpy as np

from dict.utils_logging import get_logger

log = get_logger(__name__)


class State(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"


class _RecorderProto(Protocol):
    def start(self) -> None: ...
    def stop(self) -> np.ndarray | None: ...


class _TranscriberProto(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class _TrayProto(Protocol):
    def set_state(self, state: str) -> None: ...
    def notify(self, title: str, message: str) -> None: ...


class _WindowProto(Protocol):
    def refresh(self) -> None: ...
    def show_for(self, seconds: float) -> None: ...


class _HistoryProto(Protocol):
    def push(self, text: str) -> object: ...


class _SoundsProto(Protocol):
    def play_start(self) -> None: ...
    def play_stop(self) -> None: ...


def _default_spawn(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name="transcribe-worker", daemon=True).start()


class Controller:
    def __init__(
        self,
        recorder: _RecorderProto,
        transcriber: _TranscriberProto,
        tray: _TrayProto,
        window: _WindowProto,
        history: _HistoryProto,
        sounds: _SoundsProto,
        clipboard_set: Callable[[str], bool],
        logger_append: Callable[[str], None],
        spawn: Callable[[Callable[[], None]], None] = _default_spawn,
        auto_show_seconds: float = 2.0,
    ) -> None:
        self._recorder = recorder
        self._transcriber = transcriber
        self._tray = tray
        self._window = window
        self._history = history
        self._sounds = sounds
        self._clipboard_set = clipboard_set
        self._logger_append = logger_append
        self._spawn = spawn
        self._auto_show_seconds = auto_show_seconds
        self._state = State.IDLE
        self._state_lock = threading.Lock()

    @property
    def state(self) -> State:
        with self._state_lock:
            return self._state

    def on_hotkey(self) -> None:
        with self._state_lock:
            current = self._state

        if current is State.IDLE:
            self._start_recording()
        elif current is State.RECORDING:
            self._stop_and_transcribe()
        else:  # TRANSCRIBING
            log.debug("hotkey ignored — currently transcribing")

    def _start_recording(self) -> None:
        try:
            self._recorder.start()
        except Exception:
            log.exception("recorder start failed")
            self._tray.set_state("error")
            self._tray.notify("Dict", "Microphone not available")
            # stay in IDLE
            return
        with self._state_lock:
            self._state = State.RECORDING
        self._sounds.play_start()
        self._tray.set_state("recording")

    def _stop_and_transcribe(self) -> None:
        audio = self._recorder.stop()
        self._sounds.play_stop()

        if audio is None:
            # empty / silent → straight back to idle, no work
            self._tray.set_state("idle")
            with self._state_lock:
                self._state = State.IDLE
            return

        with self._state_lock:
            self._state = State.TRANSCRIBING
        self._tray.set_state("busy")

        def worker() -> None:
            try:
                text = self._transcriber.transcribe(audio)
            except Exception:
                log.exception("transcription failed")
                self._tray.notify("Dict", "Transcription failed")
                self._return_to_idle()
                return
            text = (text or "").strip()
            if not text:
                self._return_to_idle()
                return
            self._history.push(text)
            self._logger_append(text)
            self._clipboard_set(text)
            self._window.refresh()
            self._window.show_for(self._auto_show_seconds)
            self._return_to_idle()

        self._spawn(worker)

    def _return_to_idle(self) -> None:
        self._tray.set_state("idle")
        with self._state_lock:
            self._state = State.IDLE
```

- [ ] **Step 4: Run tests**

```bash
.venv/Scripts/python -m pytest tests/test_controller.py -v
```
Expected: all 8 pass.

- [ ] **Step 5: Full test suite**

```bash
.venv/Scripts/python -m pytest -v
```
Expected: all non-slow tests pass.

- [ ] **Step 6: Commit**

```bash
git add dict/controller.py tests/test_controller.py && git commit -m "feat: add Controller state machine with TDD coverage"
```

---

## Task 14: `__main__.py` — single-instance wiring

**Files:**
- Create: `D:/Projects/Dict/dict/__main__.py`

- [ ] **Step 1: Implement `dict/__main__.py`**

```python
"""Entry point: single-instance lock, wiring, main loop."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import msvcrt

from dict import clipboard, config, logger as logger_mod, sounds
from dict.controller import Controller
from dict.history import History
from dict.hotkey import HotkeyWatcher
from dict.recorder import Recorder
from dict.transcriber import Transcriber
from dict.tray import Tray
from dict.window import HistoryWindow
from dict.utils_logging import get_logger


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


class _SingleInstanceLock:
    """Non-blocking file lock; on failure the process should exit."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._file = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file = open(self._path, "a+")
            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            if self._file is not None:
                self._file.close()
                self._file = None
            return False

    def release(self) -> None:
        if self._file is None:
            return
        try:
            msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        self._file.close()
        self._file = None


def main() -> int:
    _configure_logging()
    log = get_logger("dict.main")

    lock = _SingleInstanceLock(config.LOCK_PATH)
    if not lock.acquire():
        print("Dict already running")
        return 0

    try:
        # Build the object graph bottom-up.
        history = History(maxlen=config.HISTORY_MAX)
        recorder = Recorder()
        transcriber = Transcriber()
        window = HistoryWindow(history=history, on_copy=clipboard.set_text)

        # Tray needs callbacks that reference hotkey + controller, so build
        # those first (controller needs tray → we resolve tray lazily via a
        # mutable holder to avoid a cycle in construction order).
        tray_holder: dict[str, "Tray"] = {}

        class _TrayFacade:
            def set_state(self, state: str) -> None:
                tray_holder["tray"].set_state(state)
            def notify(self, title: str, message: str) -> None:
                tray_holder["tray"].notify(title, message)

        controller = Controller(
            recorder=recorder,
            transcriber=transcriber,
            tray=_TrayFacade(),
            window=window,
            history=history,
            sounds=sounds,
            clipboard_set=clipboard.set_text,
            logger_append=logger_mod.append,
            auto_show_seconds=config.AUTO_SHOW_SECONDS,
        )

        hotkey = HotkeyWatcher(config.HOTKEY, on_trigger=controller.on_hotkey)

        def on_left_click() -> None:
            window.toggle()

        def on_quit() -> None:
            hotkey.stop()
            window.stop()
            lock.release()

        tray = Tray(on_left_click=on_left_click, on_quit=on_quit)
        tray_holder["tray"] = tray

        # Boot: load model lazily on first use — but download it up front
        # if missing so the user sees the delay only once, before the tray
        # goes live.
        log.info("warming up whisper model (%s)...", config.MODEL_SIZE)
        try:
            transcriber.ensure_loaded()
        except Exception:
            log.exception("initial model load failed — hotkey remains active; each attempt will retry")

        window.start()
        hotkey.start()
        log.info("dict ready; press %s to record", config.HOTKEY)
        tray.run()  # blocks until on_quit
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Import-only syntax check**

```bash
.venv/Scripts/python -c "import dict.__main__ as m; print('ok')"
```
Expected: `ok`.

- [ ] **Step 3: Manual E2E — first launch**

```bash
.venv/Scripts/python -m dict
```
Expected: after model warmup, tray icon appears. Press `Win+B`, say "проверка связи", press `Win+B` again. Start/stop sounds play. History window appears for ~2 s. `dict.log` contains a line. Clipboard contains the text.

- [ ] **Step 4: Manual E2E — second instance exits**

Leave first running. In another terminal:

```bash
.venv/Scripts/python -m dict
```
Expected: prints `Dict already running` and exits.

- [ ] **Step 5: Quit via tray → click Quit**

Expected: tray icon disappears, process exits. First instance's lock released.

- [ ] **Step 6: Commit**

```bash
git add dict/__main__.py && git commit -m "feat: wire entry point with single-instance lock"
```

---

## Task 15: README manual smoke + polish

**Files:**
- Modify: `D:/Projects/Dict/README.md`

- [ ] **Step 1: Read current README**

```bash
cat README.md
```

- [ ] **Step 2: Expand README with troubleshooting**

Append to `README.md`:

```markdown
## Troubleshooting

- **Nothing happens on Win+B:** another app may be holding the hotkey. Try a different combo in `dict/config.py` (`HOTKEY = "<ctrl>+<alt>+v"` etc.) and relaunch.
- **"Microphone not available":** check Windows Sound settings → Input. Close apps that may be holding exclusive access (Teams, Discord, OBS).
- **Transcription is slow:** without a CUDA GPU (≥4 GB VRAM) Whisper runs on CPU int8. A 10-second clip takes roughly 3-6 s on a modern laptop CPU.
- **Words missed at the start/end of recordings:** leave ~0.3 s of silence before speaking and before pressing the hotkey again.
- **Model re-downloads every run:** set `HF_HOME` to a persistent directory.

## Files

- `dict.log` — append-only transcription log in the project root.
- `%TEMP%/dict.lock` — single-instance lockfile.
- Model cache — `%USERPROFILE%\.cache\huggingface\hub\` (shared with Content Mashine).
```

- [ ] **Step 3: Run full manual smoke checklist**

From the README:
1. Launch.
2. Win+B → "проверка связи" → Win+B.
3. Start/stop sounds played.
4. History window auto-appeared for ~2 s.
5. List shows new entry with timestamp.
6. Clipboard contains the transcribed text (`Ctrl+V` into Notepad).
7. `dict.log` has a matching line.
8. Click tray icon — window toggles visibility.
9. Click an older history row — clipboard updated to that row.
10. Launch a second instance — exits immediately.
11. Right-click tray → Quit — process exits cleanly.

- [ ] **Step 4: Commit**

```bash
git add README.md && git commit -m "docs: expand README with troubleshooting and file map"
```

---

## Self-review notes

- **Spec coverage:** every row of the Product decisions table maps to at least one task:
  - model `small` / auto lang → Task 9
  - `pystray` / `tkinter` / `pynput` → Tasks 10-12
  - hotkey `Win+B` toggle → Task 2 config + Task 10 + Task 13 state machine
  - history N=5, click-to-copy → Tasks 3, 12, 13
  - window toggle on tray click + 2 s auto-show → Tasks 12, 13, 14
  - sounds → Tasks 6, 7
  - clipboard → Task 5
  - log `dict.log` append-only → Task 4
  - no WAV retention → Recorder just returns and discards (Task 8)
  - no Windows autostart → no task (YAGNI)
  - empty/silent drop → Tasks 8 (detection), 13 (Controller behavior)
  - no max length → no lifecycle timer
  - single-instance → Task 14
  - risks (pynput Win leak, model download, tray+tk threading) → validated during Tasks 10, 9, 12 manual smokes

- **Placeholder scan:** no `TBD` / `TODO` / vague-error lines. All code blocks are complete.

- **Type consistency:**
  - `Recorder.stop()` returns `np.ndarray | None` — matches test expectations and `Controller._stop_and_transcribe`.
  - `Transcriber.transcribe(audio: np.ndarray) -> str` — consistent across Task 9, Task 13 tests, and Controller.
  - `History.push(text) -> Entry` consistent with test and window usage.
  - `clipboard.set_text(text) -> bool` — `Controller` uses it as `clipboard_set: Callable[[str], bool]`; `__main__` passes `clipboard.set_text` directly. Match.
  - `logger.append(text)` — `Controller` expects `Callable[[str], None]`; `logger_mod.append(text, path=None)` matches when called positionally.
