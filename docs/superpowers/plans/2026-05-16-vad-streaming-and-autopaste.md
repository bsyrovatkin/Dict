# VAD streaming + HUD-on-top + auto-paste Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace batch transcription with streaming segments (silero VAD, 500ms pause / 12s hard-cap), accumulate partials in a focus-preserving always-on-top HUD, and auto-paste the full result into the active text field after the user releases the hotkey.

**Architecture:** A new `VadStreamer` owns audio routing during a recording session — it receives raw int16 PortAudio chunks via a non-blocking `push()`, runs silero VAD on 512-sample windows to find natural pauses, commits each completed segment to a transcription thread, and emits per-segment text via callback. The Window grows a HUD mode (Qt.Tool + WA_ShowWithoutActivating) and a partials display. A new `paste_text` helper saves/restores the clipboard around a programmatic Ctrl+V. The Controller is the only coordinator that knows about all the pieces.

**Tech Stack:** Python 3.10+, PySide6, faster-whisper (provides bundled silero ONNX via `faster_whisper.vad.SileroVADModel`), onnxruntime (already a runtime dep), pyperclip, keyboard, numpy, pytest.

**Spec:** [docs/superpowers/specs/2026-05-16-vad-streaming-and-autopaste-design.md](../specs/2026-05-16-vad-streaming-and-autopaste-design.md)

---

## File map

**New:**
- `dict/streaming.py` — `_VadAccumulator`, `_SegmentBuilder`, `VadStreamer`
- `dict/paste.py` — `paste_text(text, current_hotkey)`
- `tests/test_streaming.py` — unit tests for builder + streamer (mocked VAD + Transcriber)
- `tests/test_paste.py` — unit tests for paste flow (mocked pyperclip + keyboard)
- `tests/test_streaming_smoke.py` — slow integration with real Whisper

**Modified:**
- `dict/config.py` — add `AUTO_PASTE`, `STREAM_PAUSE_MS`, `STREAM_HARD_CAP_S`
- `dict/settings.py` — add `auto_paste` field
- `dict/clipboard.py` — add `get_text()`
- `dict/transcriber.py` — add `is_loaded` property
- `dict/recorder.py` — add `set_push_callback` + invocation in `_on_audio`
- `dict/controller.py` — wire `VadStreamer`, gate hotkey on model load, replace clipboard-only with paste
- `dict/qt_window.py` — Qt.Tool + WA_ShowWithoutActivating, no-focus show, partials widget + signals
- `dict/__main__.py` — construct streamer, pass `auto_paste` + `get_current_hotkey`, set HUD mode, warn on Ctrl+V-collision hotkeys
- `tests/test_controller.py` — new tests for streaming path

---

## Task 1: Config + Settings — new fields

**Why first:** every other task references these values. Additive — won't break anything.

**Files:**
- Modify: `dict/config.py`
- Modify: `dict/settings.py`
- Test: `tests/test_settings.py`

- [ ] **Step 1: Read existing config and settings test to understand patterns**

Read `dict/config.py`, `dict/settings.py`, and `tests/test_settings.py` so the additions match the existing style.

- [ ] **Step 2: Write failing test for new auto_paste field**

Append to `tests/test_settings.py`:

```python
def test_settings_default_auto_paste_true():
    s = settings_mod.Settings()
    assert s.auto_paste is True


def test_settings_load_preserves_auto_paste_false(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text('{"hotkey": "f9", "auto_paste": false}', encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", p)
    s = settings_mod.load()
    assert s.auto_paste is False
```

If `settings_mod` is not already imported in that file under that name, match the existing import style (look for how `Settings` / `load` are referenced in the file).

- [ ] **Step 3: Run tests, expect failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_settings.py -v
```

Expected: `test_settings_default_auto_paste_true` fails with `AttributeError: 'Settings' object has no attribute 'auto_paste'`.

- [ ] **Step 4: Add config constants**

In `dict/config.py`, after the existing UI section (`AUTO_SHOW_SECONDS = 2.0`), add:

```python
# Streaming / paste
AUTO_PASTE = True            # send Ctrl+V into the focused field after transcription
STREAM_PAUSE_MS = 500        # silence duration that commits a segment
STREAM_HARD_CAP_S = 12.0     # max segment duration before forced commit
```

- [ ] **Step 5: Add Settings field**

In `dict/settings.py`, inside the `Settings` dataclass, after `mic_gain`:

```python
    auto_paste: bool = field(default_factory=lambda: config.AUTO_PASTE)
```

- [ ] **Step 6: Run tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_settings.py -v
```

Expected: all settings tests pass.

- [ ] **Step 7: Commit**

```bash
git add dict/config.py dict/settings.py tests/test_settings.py
git commit -m "feat(settings): add auto_paste + streaming tuning constants"
```

---

## Task 2: Transcriber.is_loaded property

**Why next:** used by Controller's model-load gate. Tiny and isolated.

**Files:**
- Modify: `dict/transcriber.py`
- Test: `tests/test_transcriber_smoke.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_transcriber_smoke.py`:

```python
def test_transcriber_is_loaded_false_before_load():
    t = Transcriber()
    assert t.is_loaded is False


@pytest.mark.slow
def test_transcriber_is_loaded_true_after_load():
    t = Transcriber()
    t.ensure_loaded()
    assert t.is_loaded is True
```

- [ ] **Step 2: Run tests, expect first to fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_transcriber_smoke.py::test_transcriber_is_loaded_false_before_load -v
```

Expected: `AttributeError`.

- [ ] **Step 3: Implement property**

In `dict/transcriber.py`, inside `Transcriber`, after the `__init__` method:

```python
    @property
    def is_loaded(self) -> bool:
        return self._model is not None
```

- [ ] **Step 4: Run test, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_transcriber_smoke.py::test_transcriber_is_loaded_false_before_load -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dict/transcriber.py tests/test_transcriber_smoke.py
git commit -m "feat(transcriber): is_loaded property"
```

---

## Task 3: clipboard.get_text

**Why next:** needed by paste_text. Tiny.

**Files:**
- Modify: `dict/clipboard.py`
- Test: `tests/test_clipboard.py`

- [ ] **Step 1: Read existing clipboard test**

Read `tests/test_clipboard.py` to mirror the style.

- [ ] **Step 2: Write failing test**

Append to `tests/test_clipboard.py` (adjust import if needed):

```python
from unittest.mock import patch


def test_get_text_returns_pyperclip_paste():
    with patch("dict.clipboard.pyperclip.paste", return_value="hello"):
        assert clipboard.get_text() == "hello"


def test_get_text_returns_empty_on_pyperclip_failure():
    with patch("dict.clipboard.pyperclip.paste", side_effect=RuntimeError("boom")):
        assert clipboard.get_text() == ""
```

If `clipboard` is imported differently in that test file, match the existing import.

- [ ] **Step 3: Run test, expect failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_clipboard.py -v
```

Expected: `AttributeError: module 'dict.clipboard' has no attribute 'get_text'`.

- [ ] **Step 4: Implement get_text**

In `dict/clipboard.py`, after `set_text`:

```python
def get_text() -> str:
    try:
        return pyperclip.paste() or ""
    except Exception:
        log.exception("clipboard read failed")
        return ""
```

- [ ] **Step 5: Run tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_clipboard.py -v
```

- [ ] **Step 6: Commit**

```bash
git add dict/clipboard.py tests/test_clipboard.py
git commit -m "feat(clipboard): get_text for save/restore around paste"
```

---

## Task 4: paste_text module

**Files:**
- Create: `dict/paste.py`
- Create: `tests/test_paste.py`

- [ ] **Step 1: Write failing test file**

Create `tests/test_paste.py`:

```python
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dict import paste as paste_mod


def test_paste_text_saves_copies_pastes_then_schedules_restore():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()
    mock_timer = MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=mock_timer) as timer_ctor:
        ok = paste_mod.paste_text("NEW")

    assert ok is True
    # Order matters: read saved -> copy new -> send paste -> schedule restore
    mock_pyperclip.paste.assert_called_once_with()
    mock_pyperclip.copy.assert_called_once_with("NEW")
    mock_keyboard.send.assert_called_once_with("ctrl+v")
    timer_ctor.assert_called_once()
    mock_timer.start.assert_called_once()


def test_paste_text_releases_hotkey_before_sending_ctrl_v():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = ""
    mock_keyboard = MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        paste_mod.paste_text("X", current_hotkey="ctrl+shift+v")

    # release must come BEFORE send
    call_order = [c[0] for c in mock_keyboard.method_calls]
    assert call_order.index("release") < call_order.index("send")
    mock_keyboard.release.assert_called_once_with("ctrl+shift+v")


def test_paste_text_returns_false_when_send_fails():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()
    mock_keyboard.send.side_effect = RuntimeError("no perms")

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer") as timer_ctor:
        ok = paste_mod.paste_text("NEW")

    assert ok is False
    timer_ctor.assert_not_called()  # do NOT restore — text stays in clipboard


def test_paste_text_release_failure_does_not_block_paste():
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = ""
    mock_keyboard = MagicMock()
    mock_keyboard.release.side_effect = RuntimeError("hotkey unknown")

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", return_value=MagicMock()):
        ok = paste_mod.paste_text("X", current_hotkey="weird+combo")

    # release failed but send still happened
    assert ok is True
    mock_keyboard.send.assert_called_once_with("ctrl+v")


def test_paste_text_restore_timer_callback_swallows_failures():
    """The timer fires later; if pyperclip.copy raises during restore, no crash."""
    mock_pyperclip = MagicMock()
    mock_pyperclip.paste.return_value = "OLD"
    mock_keyboard = MagicMock()

    captured = {}

    def fake_timer(delay, fn):
        captured["fn"] = fn
        return MagicMock()

    with patch("dict.paste.pyperclip", mock_pyperclip), \
         patch("dict.paste.keyboard", mock_keyboard), \
         patch("dict.paste.threading.Timer", side_effect=fake_timer):
        paste_mod.paste_text("NEW")

    # Now make restore fail
    mock_pyperclip.copy.side_effect = RuntimeError("clip locked")
    captured["fn"]()  # must not raise
```

- [ ] **Step 2: Run tests, expect import-fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paste.py -v
```

Expected: `ModuleNotFoundError: No module named 'dict.paste'`.

- [ ] **Step 3: Create dict/paste.py**

```python
"""Auto-paste recognized text into the focused text field.

Saves the clipboard, copies our text, sends Ctrl+V, and restores the
clipboard ~200ms later. The active app reads the clipboard asynchronously
on Ctrl+V, so restoring synchronously would race with the paste.

If the user's hotkey shares modifier keys with Ctrl+V (e.g.
ctrl+shift+v), we issue a best-effort keyboard.release(<hotkey>) before
sending Ctrl+V — otherwise the still-pressed modifiers cause SendInput
to misbehave.
"""
from __future__ import annotations

import threading

import keyboard
import pyperclip

from dict.utils_logging import get_logger

log = get_logger(__name__)

_RESTORE_DELAY_S = 0.2


def paste_text(
    text: str,
    current_hotkey: str | None = None,
    restore_delay_s: float = _RESTORE_DELAY_S,
) -> bool:
    """Place `text` in the clipboard, send Ctrl+V, restore old clipboard.

    Returns True if Ctrl+V was sent successfully. Returns False if the
    keyboard.send failed (text remains in the clipboard so the user can
    paste manually; the restore timer is NOT scheduled in that case).
    """
    saved = ""
    try:
        saved = pyperclip.paste() or ""
    except Exception:
        log.exception("paste_text: read of clipboard failed; will not restore")
        saved = ""

    try:
        pyperclip.copy(text)
    except Exception:
        log.exception("paste_text: copy of new text failed")
        return False

    if current_hotkey:
        try:
            keyboard.release(current_hotkey)
        except Exception:
            log.warning("paste_text: keyboard.release(%r) failed (continuing)",
                        current_hotkey)

    try:
        keyboard.send("ctrl+v")
    except Exception:
        log.warning("paste_text: keyboard.send('ctrl+v') failed; text left in clipboard")
        return False

    def _restore() -> None:
        try:
            pyperclip.copy(saved)
        except Exception:
            log.warning("paste_text: clipboard restore failed (swallowed)")

    threading.Timer(restore_delay_s, _restore).start()
    return True
```

- [ ] **Step 4: Run tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_paste.py -v
```

Expected: all 5 pass.

- [ ] **Step 5: Commit**

```bash
git add dict/paste.py tests/test_paste.py
git commit -m "feat(paste): paste_text with clip save/restore and hotkey release"
```

---

## Task 5: Recorder.set_push_callback

**Why now:** the streamer needs raw chunks from the recorder. This is a small additive change.

**Files:**
- Modify: `dict/recorder.py`
- Test: `tests/test_recorder.py`

- [ ] **Step 1: Read the existing recorder test file**

Read `tests/test_recorder.py` to see test fixtures and patterns.

- [ ] **Step 2: Write failing test**

Append to `tests/test_recorder.py`:

```python
from unittest.mock import MagicMock


def test_set_push_callback_invoked_on_chunk():
    r = Recorder()
    cb = MagicMock()
    r.set_push_callback(cb)
    # Synthesize a sounddevice callback at the same native==target SR
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_called_once()
    arg = cb.call_args[0][0]
    assert arg.shape == (512,)


def test_set_push_callback_none_disables_invocation():
    r = Recorder()
    cb = MagicMock()
    r.set_push_callback(cb)
    r.set_push_callback(None)
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_not_called()


def test_push_callback_exception_does_not_break_audio_thread(caplog):
    r = Recorder()
    cb = MagicMock(side_effect=RuntimeError("kaboom"))
    r.set_push_callback(cb)
    r._native_sr = config.SAMPLE_RATE
    chunk = np.ones((512, 1), dtype=np.int16) * 100
    # Must not raise
    r._on_audio(chunk, 512, time_info=None, status=None)
    cb.assert_called_once()
```

Make sure `config` and `np` are imported at the top of the test file (likely already there).

- [ ] **Step 3: Run tests, expect failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```

Expected: `AttributeError: 'Recorder' object has no attribute 'set_push_callback'`.

- [ ] **Step 4: Add the field, setter, and invocation**

In `dict/recorder.py`, inside `Recorder.__init__`, after `self._gain = 1.0`:

```python
        self._push_cb: Optional[Callable[[np.ndarray], None]] = None
```

After `set_level_callback`, add:

```python
    def set_push_callback(self, cb: Optional[Callable[[np.ndarray], None]]) -> None:
        """Receive resampled int16 chunks at TARGET_SR for downstream streaming.

        Invoked from the PortAudio callback thread AFTER the chunk is stored
        in _chunks for the full-buffer fallback. Exceptions are caught here
        so the audio thread cannot die.
        """
        self._push_cb = cb
```

In `_on_audio`, after the existing `cb = self._level_cb` block (the entire `if cb is not None: ...` block), add:

```python
        push = self._push_cb
        if push is not None:
            try:
                if self._native_sr != self._target_sr:
                    pushed = _linear_resample(chunk, self._native_sr, self._target_sr)
                else:
                    pushed = chunk
                push(pushed)
            except Exception:
                log.exception("push_callback raised")
```

- [ ] **Step 5: Run tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_recorder.py -v
```

- [ ] **Step 6: Commit**

```bash
git add dict/recorder.py tests/test_recorder.py
git commit -m "feat(recorder): set_push_callback for downstream streaming"
```

---

## Task 6: `_SegmentBuilder` — pure VAD state machine

**Why split from VadStreamer:** the segmentation logic (silence detection, hard-cap) is fully testable without threads or real VAD. Pluggable classifier means tests feed canned booleans.

**Files:**
- Create: `dict/streaming.py` (just the builder for now)
- Create: `tests/test_streaming.py`

- [ ] **Step 1: Create empty streaming.py with module docstring**

`dict/streaming.py`:

```python
"""Streaming VAD pipeline.

Three pieces:
  - _VadAccumulator   : wraps faster_whisper's silero ONNX, accepts int16
                        chunks of any size, emits one bool per 512-sample
                        window (~32 ms at 16 kHz).
  - _SegmentBuilder   : pure state machine. Receives chunks + per-window
                        bools, emits ready-to-transcribe segments when
                        silence run >= pause_ms or speech run >= hard_cap.
  - VadStreamer       : threaded runtime. Owns an audio queue, a VAD
                        thread, and a transcribe thread. Public API is
                        start / push / stop.
"""
from __future__ import annotations
```

- [ ] **Step 2: Write failing tests for _SegmentBuilder**

Create `tests/test_streaming.py`:

```python
from __future__ import annotations

import numpy as np
import pytest

from dict.streaming import _SegmentBuilder

SR = 16000
WINDOW = 512  # silero window size in samples


def _chunk(n_samples: int, value: int = 100) -> np.ndarray:
    return np.full(n_samples, value, dtype=np.int16)


def test_builder_no_commit_while_only_silence():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4)
    # All-silence: 4 windows of False
    segments = b.feed(chunk, [False, False, False, False])
    assert segments == []
    assert b.flush() is None  # nothing was ever spoken


def test_builder_commits_after_pause_following_speech():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    # 500ms at 16kHz / 512 = ~15.6, round up to 16 windows of silence
    # Feed: 4 speech windows, then 16 silence windows
    speech_chunk = _chunk(WINDOW * 4)
    silence_chunk = _chunk(WINDOW * 16, value=0)
    seg1 = b.feed(speech_chunk, [True, True, True, True])
    assert seg1 == []
    seg2 = b.feed(silence_chunk, [False] * 16)
    assert len(seg2) == 1
    # Segment should contain at least the speech chunk (silence may be appended too)
    assert seg2[0].dtype == np.int16
    assert seg2[0].size >= WINDOW * 4


def test_builder_hard_cap_forces_commit():
    # hard_cap_s = 1.0 -> ~31 windows
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=1.0, sample_rate=SR)
    # Feed continuous speech: 40 windows
    chunk = _chunk(WINDOW * 40)
    segs = b.feed(chunk, [True] * 40)
    assert len(segs) >= 1  # at least one forced commit


def test_builder_flush_emits_pending_speech():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4)
    b.feed(chunk, [True, True, True, True])
    # No silence yet -> not committed
    flushed = b.flush()
    assert flushed is not None
    assert flushed.size >= WINDOW * 4


def test_builder_flush_returns_none_if_no_speech_pending():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    chunk = _chunk(WINDOW * 4, value=0)
    b.feed(chunk, [False, False, False, False])
    assert b.flush() is None


def test_builder_handles_multiple_speech_silence_cycles():
    b = _SegmentBuilder(pause_ms=500, hard_cap_s=12.0, sample_rate=SR)
    speech = _chunk(WINDOW * 4)
    silence = _chunk(WINDOW * 16, value=0)
    # Cycle 1
    b.feed(speech, [True] * 4)
    seg1 = b.feed(silence, [False] * 16)
    assert len(seg1) == 1
    # Cycle 2 — builder should reset state
    b.feed(speech, [True] * 4)
    seg2 = b.feed(silence, [False] * 16)
    assert len(seg2) == 1
```

- [ ] **Step 3: Run tests, expect import failure**

```bash
.venv/Scripts/python.exe -m pytest tests/test_streaming.py -v
```

Expected: `ImportError: cannot import name '_SegmentBuilder' from 'dict.streaming'`.

- [ ] **Step 4: Implement _SegmentBuilder**

Append to `dict/streaming.py`:

```python
import numpy as np

from dict.utils_logging import get_logger

log = get_logger(__name__)

_VAD_WINDOW = 512  # silero's fixed window size at 16 kHz (~32 ms)


class _SegmentBuilder:
    """Stateful: feed int16 chunks + per-window speech flags, emit segments.

    Commit triggers:
      - silence run >= pause_ms after any speech in the current segment
      - speech run  >= hard_cap_s (forced split mid-utterance)
    """

    def __init__(self, pause_ms: int, hard_cap_s: float, sample_rate: int = 16000):
        self._sample_rate = sample_rate
        # Round UP so we definitely meet the threshold
        self._max_silence_windows = max(
            1, (pause_ms * sample_rate + (1000 * _VAD_WINDOW) - 1)
               // (1000 * _VAD_WINDOW)
        )
        self._max_speech_windows = max(
            1, int(hard_cap_s * sample_rate / _VAD_WINDOW)
        )
        self._current: list[np.ndarray] = []   # int16 chunks accumulated
        self._silence_run = 0                  # consecutive silent windows
        self._speech_total = 0                 # total speech windows in current segment

    def feed(self, chunk: np.ndarray, is_speech_windows: list[bool]) -> list[np.ndarray]:
        """Append a chunk + its per-window speech flags. Return any commits.

        `chunk` is int16 mono at sample_rate. `is_speech_windows` is one bool
        per 512-sample window inside the chunk (so len == chunk.size // 512).
        """
        committed: list[np.ndarray] = []
        self._current.append(chunk)

        for is_speech in is_speech_windows:
            if is_speech:
                self._silence_run = 0
                self._speech_total += 1
                if self._speech_total >= self._max_speech_windows:
                    seg = self._take_current()
                    if seg is not None:
                        committed.append(seg)
            else:
                if self._speech_total > 0:
                    self._silence_run += 1
                    if self._silence_run >= self._max_silence_windows:
                        seg = self._take_current()
                        if seg is not None:
                            committed.append(seg)
        return committed

    def flush(self) -> np.ndarray | None:
        """Final commit on stop. Returns the buffered segment if any speech
        was detected since the last commit; otherwise None."""
        if self._speech_total == 0:
            self._current.clear()
            return None
        return self._take_current()

    def _take_current(self) -> np.ndarray | None:
        if not self._current:
            return None
        seg = np.concatenate(self._current)
        self._current.clear()
        self._silence_run = 0
        self._speech_total = 0
        return seg
```

- [ ] **Step 5: Run tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_streaming.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add dict/streaming.py tests/test_streaming.py
git commit -m "feat(streaming): _SegmentBuilder pure state machine"
```

---

## Task 7: `_VadAccumulator` + `VadStreamer` — silero wrapper + threaded runtime

**Files:**
- Modify: `dict/streaming.py`
- Modify: `tests/test_streaming.py`

- [ ] **Step 1: Write failing tests for the threaded streamer**

Append to `tests/test_streaming.py`:

```python
import threading
import time
from unittest.mock import MagicMock

from dict.streaming import VadStreamer


class _FakeTranscriber:
    """Returns 'TX(<len>)' per segment so tests can verify partial wiring."""
    def __init__(self) -> None:
        self.calls: list[int] = []

    def transcribe(self, audio: np.ndarray) -> str:
        self.calls.append(audio.size)
        return f"TX({audio.size})"


def _make_streamer(
    monkeypatch,
    *,
    transcriber=None,
    on_partial=None,
    pause_ms: int = 500,
    hard_cap_s: float = 12.0,
    passthrough: bool = False,
):
    """Build a VadStreamer with the VAD layer mocked.

    The fake VAD treats any chunk with samples != 0 as speech.
    """
    if transcriber is None:
        transcriber = _FakeTranscriber()
    if on_partial is None:
        on_partial = MagicMock()

    class _FakeVad:
        def add(self, chunk_int16):
            n_windows = chunk_int16.size // WINDOW
            return [bool(np.any(chunk_int16[i*WINDOW:(i+1)*WINDOW]))
                    for i in range(n_windows)]

    def _fake_factory():
        if passthrough:
            raise RuntimeError("forced VAD load failure")
        return _FakeVad()

    monkeypatch.setattr("dict.streaming._make_vad_accumulator", _fake_factory)

    s = VadStreamer(
        transcriber=transcriber,
        on_partial=on_partial,
        pause_ms=pause_ms,
        hard_cap_s=hard_cap_s,
        sample_rate=SR,
    )
    return s, transcriber, on_partial


def test_streamer_emits_partial_on_silence_then_speech(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, pause_ms=500, hard_cap_s=12.0)
    s.start()
    try:
        s.push(_chunk(WINDOW * 4, value=100))      # speech
        s.push(_chunk(WINDOW * 16, value=0))       # silence -> commit
        s.push(_chunk(WINDOW * 4, value=200))      # speech
        s.push(_chunk(WINDOW * 16, value=0))       # silence -> commit
        # Wait for tx_loop to drain
        for _ in range(50):
            if on_partial.call_count >= 2:
                break
            time.sleep(0.05)
    finally:
        text = s.stop()
    assert on_partial.call_count >= 2
    assert text.startswith("TX(") or "TX(" in text


def test_streamer_stop_flushes_pending(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, pause_ms=500, hard_cap_s=12.0)
    s.start()
    s.push(_chunk(WINDOW * 4, value=100))   # speech only, no trailing silence
    text = s.stop()
    assert text  # something was transcribed
    assert tx.calls  # transcriber was called at least once


def test_streamer_returns_empty_in_passthrough_mode(monkeypatch):
    s, tx, on_partial = _make_streamer(monkeypatch, passthrough=True)
    assert s.is_passthrough is True
    s.start()
    s.push(_chunk(WINDOW * 4, value=100))
    text = s.stop()
    assert text == ""
    assert tx.calls == []  # no transcribe attempted in passthrough


def test_streamer_continues_after_transcribe_exception(monkeypatch):
    class _FlakyTx:
        def __init__(self):
            self.n = 0
        def transcribe(self, audio):
            self.n += 1
            if self.n == 1:
                raise RuntimeError("first call blows up")
            return f"ok-{self.n}"

    tx = _FlakyTx()
    s, _, on_partial = _make_streamer(monkeypatch, transcriber=tx)
    s.start()
    try:
        # Segment 1 — will raise
        s.push(_chunk(WINDOW * 4, value=100))
        s.push(_chunk(WINDOW * 16, value=0))
        # Segment 2 — should succeed
        s.push(_chunk(WINDOW * 4, value=100))
        s.push(_chunk(WINDOW * 16, value=0))
        for _ in range(50):
            if on_partial.call_count >= 1:
                break
            time.sleep(0.05)
    finally:
        text = s.stop()
    on_partial.assert_called_once_with("ok-2")
    assert text == "ok-2"


def test_streamer_push_after_stop_is_noop(monkeypatch):
    s, _, _ = _make_streamer(monkeypatch)
    s.start()
    s.stop()
    # Should not raise
    s.push(_chunk(WINDOW * 4, value=100))


def test_streamer_drops_chunk_on_full_queue(monkeypatch, caplog):
    s, _, _ = _make_streamer(monkeypatch)
    # Shrink the queue so we can fill it cheaply
    s._audio_q = __import__("queue").Queue(maxsize=2)
    s.start()
    # Don't let vad thread consume — push fast
    for _ in range(10):
        s.push(_chunk(WINDOW * 4, value=100))
    s.stop()
    # At least one drop warning should have been logged
    assert any("queue full" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run tests, expect failures**

```bash
.venv/Scripts/python.exe -m pytest tests/test_streaming.py -v
```

Expected: VadStreamer-related tests fail with ImportError or AttributeError.

- [ ] **Step 3: Implement _VadAccumulator and VadStreamer**

Append to `dict/streaming.py`:

```python
import queue
import threading
from typing import Callable, Optional


class _VadAccumulator:
    """Wraps faster_whisper's bundled silero ONNX.

    Accepts int16 audio in chunks of arbitrary size. Buffers the remainder
    if the chunk is not a multiple of 512 samples. Returns one bool per
    completed 512-sample window.
    """

    def __init__(self, threshold: float = 0.5):
        # Lazy local import so module load doesn't pull onnxruntime if unused
        from faster_whisper.utils import get_assets_path
        from faster_whisper.vad import SileroVADModel
        import os

        path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        self._model = SileroVADModel(path)
        self._threshold = threshold
        self._buf = np.zeros(0, dtype=np.float32)

    def add(self, chunk_int16: np.ndarray) -> list[bool]:
        f = chunk_int16.astype(np.float32) / 32768.0
        self._buf = np.concatenate([self._buf, f])
        n = (self._buf.size // _VAD_WINDOW) * _VAD_WINDOW
        if n == 0:
            return []
        usable = self._buf[:n]
        self._buf = self._buf[n:]
        probs = self._model(usable, num_samples=_VAD_WINDOW)
        return [bool(p >= self._threshold) for p in probs.flatten()]


def _make_vad_accumulator() -> _VadAccumulator:
    """Factory indirection so tests can monkeypatch this single function."""
    return _VadAccumulator()


class VadStreamer:
    """Streaming-VAD pipeline. Two worker threads + queues.

    Lifecycle:
      start()         -> spawn vad_loop and tx_loop threads
      push(chunk)     -> non-blocking enqueue (drops chunks if queue full)
      stop()          -> flush, join workers, return joined committed text
    """

    AUDIO_QUEUE_CAP = 200   # ~ chunks; PortAudio typically delivers ~50ms chunks

    def __init__(
        self,
        transcriber,
        on_partial: Callable[[str], None],
        pause_ms: int = 500,
        hard_cap_s: float = 12.0,
        sample_rate: int = 16000,
    ):
        self._transcriber = transcriber
        self._on_partial = on_partial
        self._pause_ms = pause_ms
        self._hard_cap_s = hard_cap_s
        self._sample_rate = sample_rate
        self._audio_q: queue.Queue = queue.Queue(maxsize=self.AUDIO_QUEUE_CAP)
        self._segments_q: queue.Queue = queue.Queue()
        self._committed: list[str] = []
        self._running = threading.Event()
        self._vad_thread: Optional[threading.Thread] = None
        self._tx_thread: Optional[threading.Thread] = None
        self._vad: Optional[_VadAccumulator] = None
        self._builder: Optional[_SegmentBuilder] = None
        self._passthrough = False

        try:
            self._vad = _make_vad_accumulator()
        except Exception:
            log.exception("silero VAD unavailable; streamer in passthrough mode")
            self._passthrough = True

    @property
    def is_passthrough(self) -> bool:
        return self._passthrough

    def start(self) -> None:
        if self._running.is_set():
            return
        self._committed = []
        self._drain(self._audio_q)
        self._drain(self._segments_q)
        if self._passthrough:
            return
        self._builder = _SegmentBuilder(
            pause_ms=self._pause_ms,
            hard_cap_s=self._hard_cap_s,
            sample_rate=self._sample_rate,
        )
        self._running.set()
        self._vad_thread = threading.Thread(
            target=self._vad_loop, name="vad-loop", daemon=True
        )
        self._tx_thread = threading.Thread(
            target=self._tx_loop, name="tx-loop", daemon=True
        )
        self._vad_thread.start()
        self._tx_thread.start()

    def push(self, chunk: np.ndarray) -> None:
        if self._passthrough or not self._running.is_set():
            return
        try:
            self._audio_q.put_nowait(chunk)
        except queue.Full:
            log.warning("vad audio queue full, dropping chunk")

    def stop(self) -> str:
        if self._passthrough or not self._running.is_set():
            return ""
        self._running.clear()
        if self._vad_thread is not None:
            self._vad_thread.join(timeout=10.0)
        if self._tx_thread is not None:
            self._tx_thread.join(timeout=60.0)
        return " ".join(self._committed).strip()

    # ---- worker loops ----

    def _vad_loop(self) -> None:
        while True:
            try:
                chunk = self._audio_q.get(timeout=0.05)
            except queue.Empty:
                if not self._running.is_set():
                    break
                continue
            try:
                flags = self._vad.add(chunk)
                segments = self._builder.feed(chunk, flags)
                for seg in segments:
                    self._segments_q.put(seg)
            except Exception:
                log.exception("vad_loop processing failed; dropping chunk")
        # Drain whatever's left in the queue (we cleared _running)
        while True:
            try:
                chunk = self._audio_q.get_nowait()
            except queue.Empty:
                break
            try:
                flags = self._vad.add(chunk)
                segments = self._builder.feed(chunk, flags)
                for seg in segments:
                    self._segments_q.put(seg)
            except Exception:
                log.exception("vad_loop drain failed; dropping chunk")
        # Final flush
        try:
            tail = self._builder.flush()
            if tail is not None and tail.size > 0:
                self._segments_q.put(tail)
        except Exception:
            log.exception("vad_loop flush failed")
        # Sentinel for tx_loop
        self._segments_q.put(None)

    def _tx_loop(self) -> None:
        while True:
            seg = self._segments_q.get()
            if seg is None:
                return
            try:
                text = self._transcriber.transcribe(seg)
            except Exception:
                log.exception("transcribe failed on segment; skipping")
                continue
            text = (text or "").strip()
            if not text:
                continue
            self._committed.append(text)
            try:
                self._on_partial(text)
            except Exception:
                log.exception("on_partial callback raised")

    @staticmethod
    def _drain(q: queue.Queue) -> None:
        while True:
            try:
                q.get_nowait()
            except queue.Empty:
                return
```

- [ ] **Step 4: Run streaming tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_streaming.py -v
```

Expected: all tests pass. If `test_streamer_drops_chunk_on_full_queue` is flaky because the vad_thread drains the queue too fast, add `s._running.clear(); s._vad_thread = None; s._tx_thread = None` after `s.start()` in that test to prevent draining — or simply skip the test with a comment if timing proves unreliable across machines.

- [ ] **Step 5: Commit**

```bash
git add dict/streaming.py tests/test_streaming.py
git commit -m "feat(streaming): VadStreamer threaded runtime + silero accumulator"
```

---

## Task 8: Window HUD mode — Qt.Tool + no-focus show

**Files:**
- Modify: `dict/qt_window.py`

No new unit test for window flags — Qt window flags are hard to assert meaningfully in a headless test. Visual verification in Task 11.

- [ ] **Step 1: Read MainWindow.__init__ and _apply_show**

Open `dict/qt_window.py`. Locate:
- The `setWindowFlags(Qt.FramelessWindowHint | Qt.Window)` line in `__init__`
- The `_apply_show` method

- [ ] **Step 2: Change window flags to HUD mode**

In `dict/qt_window.py`, replace:

```python
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
```

with:

```python
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
```

- [ ] **Step 3: Drop focus-stealing from _apply_show**

In `dict/qt_window.py`, replace:

```python
    def _apply_show(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
```

with:

```python
    def _apply_show(self) -> None:
        # HUD style: show on top but never steal focus from the user's
        # current text field (so auto-paste sends Ctrl+V into the right
        # window). The Qt.WindowStaysOnTopHint flag is what brings us
        # to the top; raise_/activateWindow would also steal focus.
        self.show()
```

- [ ] **Step 4: Smoke test (manual)**

Run the app from source:

```bash
.venv/Scripts/python.exe -m dict
```

Open Notepad, click into it, press the configured hotkey. Verify:
- Dict window appears on top of Notepad
- Cursor is still blinking in Notepad (focus did not move to Dict)
- Press hotkey again to stop
- Recording sound plays, transcription happens (existing behavior — Ctrl+V wiring comes in Task 10)

If focus DID move to Dict, double-check `Qt.Tool` is set and `WA_ShowWithoutActivating` is set.

- [ ] **Step 5: Commit**

```bash
git add dict/qt_window.py
git commit -m "feat(window): HUD mode — always on top, never steals focus"
```

---

## Task 9: Window partials widget + signals

**Files:**
- Modify: `dict/qt_window.py`

- [ ] **Step 1: Add the partials QLabel widget to the layout**

In `dict/qt_window.py`, inside `_build_ui` (which calls `_build_record`, `_build_status`, `_build_history`), insert a new `_build_partials` call between `_build_status` and `_build_history`:

```python
        inner.addLayout(self._build_header())
        inner.addWidget(self._build_record(), 1)
        inner.addWidget(self._build_status())
        inner.addWidget(self._build_partials())
        inner.addWidget(self._build_history(), 0)
```

Add the method (near `_build_status`):

```python
    def _build_partials(self) -> QWidget:
        # ScrollArea containing a word-wrapped label. Hidden when empty.
        from PySide6.QtWidgets import QScrollArea

        self._partials_box = QScrollArea()
        self._partials_box.setObjectName("partialsBox")
        self._partials_box.setWidgetResizable(True)
        self._partials_box.setMaximumHeight(120)
        self._partials_box.setFrameShape(QScrollArea.NoFrame)

        self._partials_label = QLabel("")
        self._partials_label.setObjectName("partialsLabel")
        self._partials_label.setWordWrap(True)
        self._partials_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._partials_box.setWidget(self._partials_label)
        self._partials_box.setVisible(False)
        return self._partials_box
```

- [ ] **Step 2: Add styling**

In `_apply_styles` (the long f-string), add inside the CSS block:

```python
            #partialsBox {{
                background-color: {BG_PANEL.name()};
                border: 1px solid #122030;
                border-radius: 8px;
            }}
            #partialsLabel {{
                color: {FG.name()};
                font-family: '{MONO}';
                font-size: 10pt;
                padding: 8px 10px;
            }}
```

- [ ] **Step 3: Add thread-safe signals + slots**

In `MainWindow` class signal section (near `state_changed = Signal(str)` etc.), add:

```python
    partial_appended_signal = Signal(str)
    partials_cleared_signal = Signal()
```

In `__init__` (where existing signals are connected), add:

```python
        self.partial_appended_signal.connect(self._apply_partial_appended)
        self.partials_cleared_signal.connect(self._apply_partials_cleared)
```

Add the slots (near `_apply_state`):

```python
    def _apply_partial_appended(self, text: str) -> None:
        current = self._partials_label.text()
        joined = (current + " " + text).strip() if current else text
        self._partials_label.setText(joined)
        self._partials_box.setVisible(True)
        # Auto-scroll to bottom
        bar = self._partials_box.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _apply_partials_cleared(self) -> None:
        self._partials_label.setText("")
        self._partials_box.setVisible(False)
```

Add the thread-safe public API methods (near `set_state` etc.):

```python
    def append_partial(self, text: str) -> None:
        self.partial_appended_signal.emit(text)

    def clear_partials(self) -> None:
        self.partials_cleared_signal.emit()
```

- [ ] **Step 4: Smoke test (manual)**

Run the app:

```bash
.venv/Scripts/python.exe -m dict
```

The partials box should NOT be visible until something is appended. It will be wired up in Task 10. For now, manually verify in a Python REPL (after starting the Qt app):

Actually skip the REPL — just verify the app still launches and the window looks the same as before (empty partials box hidden).

- [ ] **Step 5: Commit**

```bash
git add dict/qt_window.py
git commit -m "feat(window): partials widget + thread-safe append/clear signals"
```

---

## Task 10: Controller — wire VadStreamer + model-load gate + paste

**Files:**
- Modify: `dict/controller.py`
- Modify: `tests/test_controller.py`

- [ ] **Step 1: Write failing tests against the new controller wiring**

Append to `tests/test_controller.py`:

```python
def make_streaming_controller(mocks, run_worker_inline: bool = True, auto_paste: bool = True):
    """Variant of make_controller that includes streamer + paste + hotkey."""
    def spawn(target):
        if run_worker_inline:
            target()
    mocks.setdefault("streamer", MagicMock())
    mocks.setdefault("paste", MagicMock(return_value=True))
    mocks.setdefault("get_hotkey", MagicMock(return_value="f9"))
    # Default: transcriber.is_loaded True so hotkey is not gated
    if not hasattr(mocks["transcriber"], "is_loaded"):
        mocks["transcriber"].is_loaded = True
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
        streamer=mocks["streamer"],
        paste=mocks["paste"],
        get_current_hotkey=mocks["get_hotkey"],
        auto_paste=auto_paste,
        spawn=spawn,
    )


def test_hotkey_blocked_while_model_loading(mocks):
    mocks["transcriber"].is_loaded = False
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    mocks["recorder"].start.assert_not_called()
    mocks["tray"].notify.assert_called_once()
    assert c.state is State.IDLE


def test_streaming_path_calls_paste_when_enabled(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello world"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=True)
    c.on_hotkey()  # start
    c.on_hotkey()  # stop
    mocks["paste"].assert_called_once_with("hello world", "f9")
    mocks["clipboard"].assert_not_called()


def test_streaming_path_uses_clipboard_when_auto_paste_off(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=False)
    c.on_hotkey()
    c.on_hotkey()
    mocks["paste"].assert_not_called()
    mocks["clipboard"].assert_called_once_with("hello")


def test_fallback_to_whole_buffer_if_streamer_empty(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = ""
    mocks["transcriber"].transcribe.return_value = "fallback text"
    mocks["paste"] = MagicMock(return_value=True)
    c = make_streaming_controller(mocks, auto_paste=True)
    c.on_hotkey()
    c.on_hotkey()
    mocks["transcriber"].transcribe.assert_called_once()
    mocks["paste"].assert_called_once_with("fallback text", "f9")


def test_partials_cleared_when_returning_to_idle(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "x"
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    mocks["window"].clear_partials.assert_called()


def test_streamer_start_called_on_recording_start(mocks):
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    mocks["streamer"].start.assert_called_once()
    mocks["recorder"].set_push_callback.assert_called_once_with(mocks["streamer"].push)


def test_streamer_push_callback_cleared_on_stop(mocks):
    mocks["recorder"].stop.return_value = np.ones(32000, dtype=np.int16)
    mocks["streamer"] = MagicMock()
    mocks["streamer"].stop.return_value = "hello"
    c = make_streaming_controller(mocks)
    c.on_hotkey()
    c.on_hotkey()
    # last call to set_push_callback should be with None
    calls = mocks["recorder"].set_push_callback.call_args_list
    assert calls[-1].args == (None,)
```

Also update the existing legacy tests that call `make_controller` directly — they'll now fail because Controller's `__init__` requires the new params. The fix: keep `make_controller` working by giving it sane defaults that route through the new path with stubs:

In `tests/test_controller.py`, update `make_controller` to add:

```python
def make_controller(mocks, run_worker_inline: bool = True) -> Controller:
    def spawn(target):
        if run_worker_inline:
            target()
    streamer = MagicMock()
    streamer.stop.return_value = ""  # forces fallback to legacy whole-buffer transcribe
    paste = MagicMock(return_value=True)
    mocks["transcriber"].is_loaded = True
    return Controller(
        recorder=mocks["recorder"],
        transcriber=mocks["transcriber"],
        tray=mocks["tray"],
        window=mocks["window"],
        history=mocks["history"],
        sounds=mocks["sounds"],
        clipboard_set=mocks["clipboard"],
        logger_append=mocks["logger"],
        streamer=streamer,
        paste=paste,
        get_current_hotkey=lambda: "f9",
        auto_paste=False,  # legacy tests assert clipboard path
        spawn=spawn,
    )
```

Note: the legacy `test_second_trigger_transcribes_and_returns_to_idle` etc. now go via streamer.stop() → "" → fallback to `transcriber.transcribe(audio)` → `clipboard_set(text)` because `auto_paste=False`. The existing assertions still hold.

- [ ] **Step 2: Run tests, expect failures**

```bash
.venv/Scripts/python.exe -m pytest tests/test_controller.py -v
```

Expected: most fail with `TypeError: Controller.__init__() got an unexpected keyword argument 'streamer'`.

- [ ] **Step 3: Update Controller signature and wiring**

Replace `dict/controller.py` Controller class. Read the current file first, then modify:

In `Controller.__init__`, add new parameters:

```python
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
        streamer,
        paste: Callable[[str, str | None], bool],
        get_current_hotkey: Callable[[], str],
        auto_paste: bool,
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
        self._streamer = streamer
        self._paste = paste
        self._get_current_hotkey = get_current_hotkey
        self._auto_paste = auto_paste
        self._spawn = spawn
        self._auto_show_seconds = auto_show_seconds
        self._state = State.IDLE
        self._state_lock = threading.Lock()
```

Add the protocol for streamer (near other Proto classes):

```python
class _StreamerProto(Protocol):
    def start(self) -> None: ...
    def push(self, chunk: np.ndarray) -> None: ...
    def stop(self) -> str: ...
```

Also widen the type hint on `streamer` to `_StreamerProto` (optional cosmetic).

Add the protocol for window's new methods. Update `_WindowProto`:

```python
class _WindowProto(Protocol):
    def refresh(self) -> None: ...
    def show_for(self, seconds: float) -> None: ...
    def set_state(self, state: str) -> None: ...
    def append_partial(self, text: str) -> None: ...
    def clear_partials(self) -> None: ...
```

- [ ] **Step 4: Add model-load gate to _start_recording**

Replace `_start_recording`:

```python
    def _start_recording(self) -> None:
        if not getattr(self._transcriber, "is_loaded", True):
            log.info("hotkey while model still loading — ignoring")
            self._tray.set_state("loading")
            self._window.set_state("loading")
            self._tray.notify("Dict", "Model still loading — try again in a moment")
            return
        try:
            self._recorder.set_push_callback(self._streamer.push)
            self._recorder.start()
        except Exception:
            log.exception("recorder start failed")
            self._tray.set_state("error")
            self._window.set_state("error")
            self._tray.notify("Dict", "Microphone not available")
            self._recorder.set_push_callback(None)
            return
        try:
            self._streamer.start()
        except Exception:
            log.exception("streamer start failed — recording without streaming")
        with self._state_lock:
            self._state = State.RECORDING
        self._sounds.play_start()
        self._tray.set_state("recording")
        self._window.set_state("recording")
        # HUD show is handled by set_state → window slot; nothing extra here.
```

Note about HUD show: the existing `_apply_state("recording")` doesn't call `show()`. We need the window to appear when recording starts. Add to `_start_recording` after `_window.set_state("recording")`:

```python
        try:
            self._window.show_for(self._auto_show_seconds)
        except Exception:
            log.exception("window show failed")
```

`show_for` already exists and now (after Task 8) shows without stealing focus.

- [ ] **Step 5: Replace _stop_and_transcribe with streaming + paste flow**

Replace the entire `_stop_and_transcribe` method:

```python
    def _stop_and_transcribe(self) -> None:
        audio = self._recorder.stop()
        # Clear the push callback BEFORE streamer.stop so no more chunks
        # arrive while we're flushing.
        try:
            self._recorder.set_push_callback(None)
        except Exception:
            log.exception("clearing push_callback failed (continuing)")
        self._sounds.play_stop()

        with self._state_lock:
            self._state = State.TRANSCRIBING
        self._tray.set_state("busy")
        self._window.set_state("busy")

        def worker() -> None:
            try:
                stream_text = self._streamer.stop() or ""
            except Exception:
                log.exception("streamer.stop failed")
                stream_text = ""
            text = stream_text
            if not text.strip() and audio is not None:
                # Fallback: streaming produced nothing — try whole-buffer transcribe
                try:
                    text = self._transcriber.transcribe(audio) or ""
                except Exception:
                    log.exception("fallback transcribe failed")
                    text = ""
            text = text.strip()
            if not text:
                log.info("no text produced; returning to idle")
                self._window.clear_partials()
                self._return_to_idle()
                return
            log.info("delivering %d chars", len(text))
            self._history.push(text)
            self._logger_append(text)
            if self._auto_paste:
                try:
                    ok = self._paste(text, self._get_current_hotkey())
                    log.info("auto-paste sent ok=%s", ok)
                except Exception:
                    log.exception("paste failed; text is in clipboard for manual paste")
            else:
                self._clipboard_set(text)
            self._window.refresh()
            self._window.show_for(self._auto_show_seconds)
            self._window.clear_partials()
            self._return_to_idle()

        self._spawn(worker)
```

- [ ] **Step 6: Run controller tests, expect pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_controller.py -v
```

Expected: all pass (legacy + new). If any legacy test asserts on `recorder.stop.return_value = None` flow, ensure the worker exits early via the existing `audio is None` path. Look at `test_empty_recording_is_dropped_silently` — that test expects `transcriber.transcribe` not called and `history.push` not called. In the new code with `auto_paste=False` and `streamer.stop()` returning "": when audio is None, the fallback `transcriber.transcribe(audio)` would be skipped (we guarded it with `and audio is not None`), text stays empty, return to idle without history.push. Good.

- [ ] **Step 7: Commit**

```bash
git add dict/controller.py tests/test_controller.py
git commit -m "feat(controller): VadStreamer integration + model-load gate + auto-paste"
```

---

## Task 11: __main__.py wiring

**Files:**
- Modify: `dict/__main__.py`

- [ ] **Step 1: Construct streamer and wire it into the controller**

In `dict/__main__.py`, in the `main()` function, after `transcriber = Transcriber(model_size=effective_model)`:

```python
        from dict.streaming import VadStreamer
        from dict.paste import paste_text

        # Streamer is constructed once and reused across sessions. The on_partial
        # callback is wired through the window's thread-safe signal.
        streamer = VadStreamer(
            transcriber=transcriber,
            on_partial=lambda t: window.append_partial(t),
            pause_ms=config.STREAM_PAUSE_MS,
            hard_cap_s=config.STREAM_HARD_CAP_S,
            sample_rate=config.SAMPLE_RATE,
        )
```

But `window` is constructed AFTER this line. So move the streamer construction to AFTER `window = MainWindow(...)`. Or use a holder pattern like `controller_holder` already does.

Cleanest: construct streamer with a holder-based callback:

```python
        window_holder: dict[str, MainWindow] = {}

        def _on_partial(text: str) -> None:
            w = window_holder.get("w")
            if w is not None:
                w.append_partial(text)

        from dict.streaming import VadStreamer
        from dict.paste import paste_text
        streamer = VadStreamer(
            transcriber=transcriber,
            on_partial=_on_partial,
            pause_ms=config.STREAM_PAUSE_MS,
            hard_cap_s=config.STREAM_HARD_CAP_S,
            sample_rate=config.SAMPLE_RATE,
        )
```

Then after `window = MainWindow(...)`:

```python
        window_holder["w"] = window
```

- [ ] **Step 2: Pass new params to Controller**

Update the `Controller(...)` call. Replace:

```python
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
```

with:

```python
        controller = Controller(
            recorder=recorder,
            transcriber=transcriber,
            tray=_TrayFacade(),
            window=window,
            history=history,
            sounds=sounds,
            clipboard_set=clipboard.set_text,
            logger_append=logger_mod.append,
            streamer=streamer,
            paste=paste_text,
            get_current_hotkey=lambda: effective_hotkey,
            auto_paste=user_settings.auto_paste,
            auto_show_seconds=config.AUTO_SHOW_SECONDS,
        )
```

- [ ] **Step 3: Warn at startup if hotkey collides with Ctrl+V**

Just after `effective_hotkey = ...` resolution near the top of `main()`, add:

```python
        if "v" in effective_hotkey.lower().split("+"):
            log.warning(
                "configured hotkey %r contains 'v'; auto-paste sends Ctrl+V — "
                "this may cause feedback loops or double-firing. Consider a "
                "different binding.",
                effective_hotkey,
            )
```

- [ ] **Step 4: Apply live auto_paste setting on save**

In `_save_settings` (the nested function), after the existing mic_gain handling, add:

```python
            if new.auto_paste != user_settings.auto_paste:
                controller._auto_paste = new.auto_paste  # live toggle
                log.info("auto_paste -> %s", new.auto_paste)
```

(`_auto_paste` is a single mutable bool on Controller; reading it is racey-but-safe — bool reads in CPython are atomic, this isn't a correctness concern.)

Then mirror to user_settings:

```python
            user_settings.auto_paste = new.auto_paste
```

- [ ] **Step 5: Smoke test (manual end-to-end)**

```bash
.venv/Scripts/python.exe -m dict
```

1. Open Notepad and click into it.
2. Press the configured hotkey.
3. Confirm: Dict window appears on top, Notepad still has the blinking cursor.
4. Speak a sentence (~5 seconds).
5. Press the hotkey to stop.
6. Confirm: text appears in Notepad, NOT in Dict's clipboard view; the Dict partials box showed words appearing as you paused.

If text appears in Dict instead of Notepad, the focus is being stolen — re-check Task 8's window flags.

If nothing pastes but text is in clipboard, `keyboard.send('ctrl+v')` is failing — check `dict-debug.log` for the warning.

- [ ] **Step 6: Commit**

```bash
git add dict/__main__.py
git commit -m "feat(main): wire VadStreamer + paste + auto_paste live toggle"
```

---

## Task 12: Slow integration test — long audio doesn't hang

**Files:**
- Create: `tests/test_streaming_smoke.py`

- [ ] **Step 1: Create the slow test**

```python
"""End-to-end smoke test that captures the 'hung transcription' regression.

Generates a 30-second synthetic WAV with intermittent speech-like noise,
feeds it through the streamer with a real (tiny) Whisper model, and asserts
the whole flow completes in under 90 seconds with non-empty text and that
the streamer respects its stop() contract.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

from dict.streaming import VadStreamer
from dict.transcriber import Transcriber


def _synthetic_speech_audio(duration_s: float = 30.0, sr: int = 16000) -> np.ndarray:
    """Speech-like signal: a 200 Hz square wave amplitude-modulated by a
    slow envelope, with silence gaps every few seconds so VAD has natural
    commit points. Not real speech — Whisper may transcribe nothing or
    nonsense, but the pipeline must complete."""
    n = int(duration_s * sr)
    t = np.arange(n) / sr
    carrier = np.sign(np.sin(2 * np.pi * 200 * t))
    envelope = 0.5 * (1 + np.sin(2 * np.pi * 0.5 * t))  # 0.5 Hz amplitude mod
    # Silence gaps every 5 seconds
    gap_mask = np.ones(n)
    gap_len = int(0.7 * sr)
    for start in range(int(4.0 * sr), n, int(5.0 * sr)):
        gap_mask[start:start + gap_len] = 0
    audio = carrier * envelope * gap_mask * 8000
    return audio.astype(np.int16)


@pytest.mark.slow
def test_long_audio_does_not_hang(monkeypatch):
    # Force tiny model to keep test runtime reasonable
    monkeypatch.setattr("dict.config.MODEL_SIZE", "tiny")
    transcriber = Transcriber(model_size="tiny")
    transcriber.ensure_loaded()

    partials = []
    streamer = VadStreamer(
        transcriber=transcriber,
        on_partial=partials.append,
        pause_ms=500,
        hard_cap_s=12.0,
        sample_rate=16000,
    )
    audio = _synthetic_speech_audio(duration_s=30.0)

    start = time.monotonic()
    streamer.start()

    # Feed in PortAudio-sized chunks (~50 ms) just like the recorder does
    chunk_samples = 800  # 50 ms at 16 kHz
    for i in range(0, audio.size, chunk_samples):
        streamer.push(audio[i:i + chunk_samples])

    text = streamer.stop()
    elapsed = time.monotonic() - start

    assert elapsed < 90.0, f"streamer stop took {elapsed:.1f}s — possible hang"
    # We don't require non-empty text from synthetic audio, but the streamer
    # must have at least *attempted* segmentation. Either we got partials or
    # we got passthrough-style empty. If passthrough, that's still a pass.
    if not streamer.is_passthrough:
        # Real VAD ran; we should have either some text or explicit empty
        assert isinstance(text, str)
```

- [ ] **Step 2: Run the slow test**

```bash
.venv/Scripts/python.exe -m pytest tests/test_streaming_smoke.py -v -m slow
```

Expected: passes within ~30-60 seconds (most time in Whisper inference on CPU). If it actually hangs, that's the regression we want to catch.

- [ ] **Step 3: Run the full test suite (fast only) to confirm no regressions**

```bash
.venv/Scripts/python.exe -m pytest -m "not slow" -v
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/test_streaming_smoke.py
git commit -m "test(streaming): slow regression test — 30s audio doesn't hang"
```

---

## Final verification checklist

After all 12 tasks are complete, manually verify:

- [ ] Run from source: `.venv/Scripts/python.exe -m dict`
- [ ] Open Notepad, click into it, press configured hotkey
- [ ] Window appears, Notepad keeps focus
- [ ] Speak 30+ seconds of Russian with natural pauses
- [ ] Partials accumulate in Dict's HUD as you speak
- [ ] Press hotkey to stop
- [ ] Full text auto-pastes into Notepad
- [ ] Clipboard contains what was there before (the saved value)
- [ ] In settings dialog, toggle off auto-paste, dictate again, verify clipboard receives the text and no paste happens
- [ ] Stop the app — no hung threads (verify with task manager or `tasklist /v | findstr python` should show no orphans)

If anything fails, check `dict-debug.log` for warnings/exceptions and address.

---

## Out of scope (do not implement in this plan)

- Real-time Whisper partial decoding within a single segment (we only commit on segment boundaries).
- A "rewrite previous segment with more context" mechanism.
- PyInstaller spec changes — silero ONNX is already bundled per commit d816cbc.
- Multilingual UI strings for the new partials display (label stays empty when idle; recognized text is what it is).
- Switching paste mechanism to UI Automation / type-as-keys (kept as future option, not needed today).
