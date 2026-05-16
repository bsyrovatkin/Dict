# VAD streaming, HUD-on-top, and auto-paste — design

**Status:** approved by user 2026-05-16
**Author:** brainstorm session
**Scope:** `dict/` package only. No changes to build/packaging.

## Problem

Today the transcription flow is fully batch: hotkey → record-everything → on stop, send the whole buffer to Whisper → put the single result in clipboard. Three problems with that:

1. **Long speeches are fragile.** Whisper's accuracy and stability degrade on long monolithic inputs (sometimes truncates, sometimes hallucinates the tail), and the user has no feedback during transcription.
2. **The "hang" the user reported.** Diagnosis from `dict-debug.log` (10:40:36 → 10:42:26): the first transcribe after model-switch synchronously waits for the warm-up to finish loading the `medium` model from Hugging Face. UI shows "DECODING…" silently for ~2 minutes. Not a deadlock, but indistinguishable from one.
3. **Manual paste.** User has to switch to the target field and press Ctrl+V themselves. For a dictation tool that's friction.

## Goals

- Streaming recognition that commits text in segments at natural pauses, accumulating in a HUD that stays visible during recording.
- After F9-stop, paste the full text directly into whatever text field has focus.
- No regressions in the existing F9 → speak → F9 → text-in-clipboard flow if streaming fails.
- Make the model-load hang impossible (or at least loud and obvious).

## Non-goals

- No partial-result streaming within a single segment (only commit on segment close).
- No "edit last committed segment based on more audio" — commits are final.
- No changes to history format, settings serialization (beyond one new field), tray, or PyInstaller spec.
- No replacement of `keyboard` or `pyperclip` libs.

---

## Architecture

A new component, `VadStreamer`, owns the streaming pipeline end-to-end. The Recorder feeds it raw audio chunks (in addition to its existing full-buffer capture). The Controller orchestrates start/stop and downstream delivery (paste, history, log). The Window grows a partials display and a HUD-mode show that doesn't steal focus.

### New files

- `dict/streaming.py` — `VadStreamer` class.
- `dict/paste.py` — `paste_text(text)` helper that does save-clip / set-clip / Ctrl+V / restore-clip.
- `tests/test_streaming.py` — unit tests with mocked VAD and Transcriber.
- `tests/test_paste.py` — unit tests with mocked pyperclip and keyboard.
- `tests/test_streaming_smoke.py` — slow integration test (real Whisper, generated/sample 30s audio).

### Modified files

- `dict/clipboard.py` — add `get_text() -> str`.
- `dict/transcriber.py` — add `is_loaded` property.
- `dict/recorder.py` — add optional `push_callback` invoked from `_on_audio` after existing chunk storage.
- `dict/controller.py` — wire VadStreamer, gate hotkey on model load, replace clipboard-only delivery with `paste_text`.
- `dict/qt_window.py` — HUD window flags, no-focus show, partials label widget, new thread-safe signals.
- `dict/settings.py` + `dict/config.py` — add `auto_paste: bool = True`.
- `dict/__main__.py` — pass `auto_paste` setting down to controller, set window into HUD mode on start.

---

## Components

### `VadStreamer` (`dict/streaming.py`)

```python
class VadStreamer:
    def __init__(
        self,
        transcriber: Transcriber,
        on_partial: Callable[[str], None],         # invoked per committed segment
        on_status: Callable[[str], None] | None,   # "speaking"|"silence"|"transcribing"
        pause_ms: int = 500,
        hard_cap_s: float = 12.0,
        sample_rate: int = 16000,
    ): ...

    def start(self) -> None: ...
    def push(self, chunk: np.ndarray) -> None: ...    # int16 mono at sample_rate; non-blocking
    def stop(self) -> str: ...                        # flush, join, return joined committed text
    @property
    def committed_text(self) -> str: ...              # snapshot of " ".join(_committed_text)
```

**Threads owned:**
- `_vad_thread` — pulls audio chunks from `_audio_q`, runs silero VAD frame-by-frame, decides "speaking" / "silence", commits a segment to `_segments_q` on a 500ms silence run or on 12s hard-cap.
- `_tx_thread` — pulls segments from `_segments_q`, calls `transcriber.transcribe(segment)`, appends text to `_committed_text`, invokes `on_partial(text)`.

**State:**
- `_audio_q: queue.Queue[np.ndarray]` (bounded, ~10s of audio so PortAudio never blocks)
- `_current_segment: bytearray` (in-flight speech being collected by VAD)
- `_segments_q: queue.Queue[np.ndarray]`
- `_committed_text: list[str]`
- `_running: threading.Event`

**Contracts:**
- `push()` is non-blocking and safe from PortAudio callback. If queue is full, drop the chunk and log a warning (better than blocking PortAudio).
- `stop()` is synchronous:
  1. Set `_running.clear()`
  2. Drain `_audio_q`, flush any `_current_segment` as a final segment to `_segments_q`
  3. Sentinel `None` to `_segments_q`
  4. Join `_tx_thread`
  5. Return `" ".join(_committed_text).strip()`
- `on_partial(text)` fires ONLY when a segment is fully transcribed by Whisper (not intermediate Whisper output).

**Failure modes:**
- Silero ONNX import/load fails → constructor logs error, sets `_passthrough = True`. In passthrough, `push()` accumulates everything into one segment in memory. On `stop()`, returns `""` (no transcription attempted). Controller's fallback path handles it.
- `transcriber.transcribe(segment)` raises → log exception, drop segment, continue. The user sees a "skip" in their partials, but recording continues.
- Queue overflow → log warning, drop oldest chunk. Should not happen in practice (10s buffer vs 16kHz mono int16 = 320KB — trivial).

### `paste_text` (`dict/paste.py`)

```python
def paste_text(text: str, restore_delay_s: float = 0.2) -> bool:
    """Save clipboard, copy text, send Ctrl+V, restore clipboard.

    Returns True if Ctrl+V was sent successfully. Returns False on
    keyboard.send failure (text remains in clipboard; user can paste
    manually).
    """
```

Flow:
1. `saved = pyperclip.paste()` (string; if clipboard has non-text content, returns "")
2. `pyperclip.copy(text)`
3. Try `keyboard.send('ctrl+v')`. On failure: log warning, return False, do NOT restore (text stays in clipboard).
4. Schedule a `threading.Timer(restore_delay_s, restore)` where `restore` does `pyperclip.copy(saved)`. Timer is daemon. Errors in restore are swallowed and logged.

**Why a timer and not synchronous wait:** the active app processes Ctrl+V asynchronously. Restoring immediately can race with the paste read and result in no text appearing. 200ms is enough for all common Windows apps tested in the wild for similar tools (Power Toys Quick Accent, Whisper Writer, etc.).

**Edge cases:**
- Focused field is read-only / rejects paste → text is in clipboard, user can retry. No way for us to detect.
- App in security mode (UAC dialog, password field) → Windows may block `SendInput`. Same as above.
- User had non-text content in clipboard (image, file) → `pyperclip.paste()` returns "" → after restore, clipboard becomes empty. Document this limitation.

### `MainWindow` HUD mode (`dict/qt_window.py`)

**Window flags change** (one-time at construction):
- Add `Qt.WindowStaysOnTopHint`
- Add `Qt.Tool` (critical: Tool windows do not appear in taskbar/Alt-Tab and do not deactivate the parent app, i.e., do not steal focus)
- Keep existing `Qt.FramelessWindowHint`
- Set `Qt.WA_ShowWithoutActivating` attribute

**New show path:**
- New signal `show_hud_requested = Signal()` → slot calls `show()` but NOT `raise_()` and NOT `activateWindow()`. Window appears on top because of the flags, but Notepad/browser/etc. retains focus.
- **All shows become no-focus-steal.** Existing `_apply_show()` drops `raise_()`/`activateWindow()`. Reason: stealing focus after auto-paste would yank the user away from the field where the text just appeared. Even with auto_paste off, the "show result" notification has no business stealing focus — the clipboard is what matters. The window already comes to top via `WindowStaysOnTopHint`; that's enough visibility.
- The history-click "copy" action still works (user explicitly interacted with the HUD, so it has focus then).

**New partials widget:**
- New `QLabel` (`_partials_label`) placed between `_status` and `_history_box` in the inner layout. Properties: word-wrap on, max-height ~120px, vertical scroll if exceeded (`QScrollArea` wrapping the label is the cleanest). Hidden when empty.
- Styling: cyan dim text on `BG_PANEL`, monospaced 10pt.
- New thread-safe API: `append_partial(text: str)` emits `partial_appended_signal`. Slot appends `text + " "` to label.
- New thread-safe API: `clear_partials()` emits a signal that clears the label. Called by controller on return-to-idle.

### `Controller` (`dict/controller.py`)

**New init params:** `streamer: VadStreamer`, `paste: Callable[[str], bool]`, `auto_paste: bool`.

**On hotkey (state=IDLE):**
1. If `not transcriber.is_loaded`: set status="loading", `tray.notify("Dict", "Model still loading")`, return without recording.
2. `streamer.start()`
3. `recorder.start()` (with `push_callback=streamer.push` set just before)
4. `window.show_hud()` (no-focus-steal show)
5. state = RECORDING

**On hotkey (state=RECORDING):**
1. `audio = recorder.stop()`
2. `streamer.stop()` returns `text`
3. If `text == ""`: fallback to `transcriber.transcribe(audio)`
4. If still empty: return to idle, hide partials
5. Else:
   - If `auto_paste`: call `paste_text(text)`. This call sends Ctrl+V synchronously but the clipboard-restore runs on a daemon `threading.Timer` and Controller does not wait for it. Controller continues to history/log immediately after Ctrl+V returns.
   - Else: `clipboard_set(text)` (legacy path)
   - `history.push(text)`, `logger_append(text)`, `window.refresh()`
6. `window.clear_partials()`
7. state = IDLE. The HUD stays visible for `auto_show_seconds` then hides (existing behavior).

**Recorder push wiring:** Controller, not Recorder, knows about Streamer. So Controller sets `recorder.set_push_callback(streamer.push)` before start, and `recorder.set_push_callback(None)` after stop. Recorder just stores and invokes — no knowledge of streamer.

### `Recorder` (`dict/recorder.py`) — additive change

```python
def set_push_callback(self, cb: Callable[[np.ndarray], None] | None) -> None: ...
```

In `_on_audio()`, after the existing `_chunks.append` and `level_cb`, add:

```python
if self._push_cb is not None:
    try:
        # Resample on the fly only if native != target (rare; usually equal)
        if self._native_sr != self._target_sr:
            chunk_at_target = _linear_resample(chunk, self._native_sr, self._target_sr)
        else:
            chunk_at_target = chunk
        self._push_cb(chunk_at_target)
    except Exception:
        log.exception("push_callback raised")
```

The full `_chunks` buffer is still maintained — it's the fallback if streamer returns empty.

### `Transcriber` (`dict/transcriber.py`) — additive

```python
@property
def is_loaded(self) -> bool:
    return self._model is not None
```

### `Settings` + `config.py` — additive

- `dict/config.py`: `AUTO_PASTE: bool = True`, `STREAM_PAUSE_MS: int = 500`, `STREAM_HARD_CAP_S: float = 12.0`
- `dict/settings.py`: `auto_paste: bool = field(default_factory=lambda: config.AUTO_PASTE)`

---

## Data flow (single dictation session)

```
F9 ↓
└─ Controller.on_hotkey() [state=IDLE]
   ├─ guard: transcriber.is_loaded? else status=loading, notify, return
   ├─ recorder.set_push_callback(streamer.push)
   ├─ recorder.start()
   ├─ streamer.start()                            (vad_thread + tx_thread start)
   ├─ window.show_hud()                           (Tool+OnTop+ShowWithoutActivating)
   └─ state = RECORDING

[user speaks]
PortAudio callback (in recorder) → _on_audio()
   ├─ _chunks.append(chunk)                       (full-buffer fallback)
   ├─ level_cb(rms)                               (VU ring)
   └─ push_cb(chunk_at_target_sr) → streamer.push(chunk)
                                    └─ _audio_q.put_nowait(chunk)

streamer._vad_loop:
   chunk = _audio_q.get()
   classify via silero VAD →
   ├─ speech    → _current_segment.extend(chunk); silence_run_ms = 0
   ├─ silence   → silence_run_ms += chunk_ms
   │              if silence_run_ms >= 500 and _current_segment:
   │                  _segments_q.put(_current_segment.copy())
   │                  _current_segment.clear()
   └─ hard-cap check: if len(_current_segment) >= 12s:
                        _segments_q.put(_current_segment.copy())
                        _current_segment.clear()

streamer._tx_loop:
   segment = _segments_q.get()
   if segment is None: break  (stop sentinel)
   text = transcriber.transcribe(segment)
   if text:
       _committed_text.append(text)
       on_partial(text)        → window.append_partial(text)

F9 ↓
└─ Controller.on_hotkey() [state=RECORDING]
   ├─ recorder.set_push_callback(None)
   ├─ audio = recorder.stop()                     (full int16 buffer)
   ├─ text = streamer.stop()                      (flushes pending, joins tx_thread)
   ├─ if not text: text = transcriber.transcribe(audio)   (fallback)
   ├─ if text:
   │  ├─ if auto_paste: paste_text(text)          (clip-save / set / Ctrl+V / restore in 200ms)
   │  │  else:          clipboard_set(text)       (legacy)
   │  ├─ history.push(text); logger_append(text); window.refresh()
   │  └─ (HUD remains visible for AUTO_SHOW_SECONDS, then hides)
   ├─ window.clear_partials()
   └─ state = IDLE
```

---

## Error handling

| Failure | Behavior |
|---|---|
| Silero ONNX load fails at streamer init | Streamer goes to passthrough mode. `stop()` returns "". Controller falls back to whole-buffer `transcriber.transcribe(audio)`. App-level UX unchanged from today. |
| `transcriber.transcribe(segment)` raises | Log exception, drop segment, tx_thread continues. User sees gap in partials. |
| `_audio_q` full | Log warning, drop chunk. (Won't happen with sane buffer size.) |
| `recorder.push_callback` raises | Caught in `_on_audio`, logged, PortAudio thread stays alive. (Same pattern as existing `level_cb`.) |
| `keyboard.send('ctrl+v')` fails | Log warning, text stays in clipboard, user pastes manually. Restore timer is not scheduled. |
| `pyperclip.paste()`/`copy()` fails | Log exception, return False, do not restore. |
| Restore timer's `pyperclip.copy(saved)` fails | Log warning, swallow. Worst case: clipboard contains recognized text instead of pre-recording content. |
| Hotkey fired during model load | Notify + status="loading", no recording starts. |
| Hotkey fired during transcribing (legacy state) | Ignored, as today. With streaming, the TRANSCRIBING state is much shorter (only the final flush). |

---

## Testing strategy

### Unit (fast)

**`tests/test_streaming.py`** (mocked silero VAD and Transcriber):
- `test_streamer_emits_partial_after_silence` — push speech-silence-speech, expect on_partial called twice with mock transcribe results.
- `test_streamer_hard_cap_forces_commit` — push 13s of synthetic "speech" chunks with no silence gap, expect commit at 12s.
- `test_streamer_stop_flushes_pending` — push one speech segment without trailing silence, call stop(), expect committed text contains that segment's transcription.
- `test_streamer_passthrough_if_vad_unavailable` — patch silero import to raise, verify stop() returns "" and no crash.
- `test_streamer_drops_chunk_on_full_queue` — fill _audio_q, push more, expect warn log, no exception.
- `test_streamer_continues_after_transcribe_exception` — first segment raises, second succeeds; verify on_partial called once with second segment's text.

**`tests/test_paste.py`** (mocked pyperclip and keyboard):
- `test_paste_text_saves_and_restores_clipboard` — verify call order: paste() → copy(text) → send('ctrl+v') → timer fires → copy(saved).
- `test_paste_text_handles_keyboard_send_failure` — send raises, expect return False, no restore scheduled, text still in clipboard.
- `test_paste_text_handles_empty_saved_clipboard` — saved="" → restore still called with "". No crash.
- `test_paste_text_swallows_restore_failure` — copy in timer raises → no exception bubbles to caller.

**Additions to `tests/test_controller.py`**:
- `test_hotkey_blocked_while_model_loading` — `transcriber.is_loaded == False` → recorder.start not called, tray.notify called.
- `test_streaming_path_calls_paste_when_enabled` — auto_paste=True, streamer.stop returns "hello", verify paste_fn("hello") called, clipboard_set NOT called.
- `test_streaming_path_calls_clipboard_when_paste_disabled` — auto_paste=False, verify clipboard_set called, paste_fn NOT called.
- `test_fallback_to_whole_buffer_if_streamer_empty` — streamer.stop returns "", transcriber.transcribe(audio) returns "x" → paste_fn("x") called.
- `test_partials_cleared_on_idle` — verify window.clear_partials called on return to idle.

### Integration (slow, marked `@pytest.mark.slow`)

**`tests/test_streaming_smoke.py`**:
- `test_long_audio_does_not_hang` — generate or read a 30-second WAV with Russian speech, run through real `VadStreamer` + real `Transcriber` (`tiny` model for speed). Assert `stop()` returns within 90 seconds and result is non-empty. **This is the explicit regression test against the "hang" symptom the user reported.**
- `test_short_audio_passes_through_streamer` — 5-second WAV, verify text is reasonable (length > 5 chars).

CI note: slow tests are not run by default (`pytest -m "not slow"`). User runs them manually with `pytest -m slow`.

---

## Out of scope (explicit)

- No partial-result streaming inside a single Whisper call (Whisper's `transcribe` is one-shot per segment; we don't try to intercept its internal decoder).
- No "rewrite already-committed segment with more context" semantics.
- No tray menu changes.
- No PyInstaller spec changes (silero ONNX is already bundled per commit `d816cbc`).
- No history-format changes.
- No multi-language UI for the new partials label (label is empty when not recording; recognized text speaks for itself).

---

## Open questions

None at design time. All design decisions confirmed during the brainstorming session:
- UX: partials in HUD (chosen)
- Display: accumulating text (chosen)
- Chunk policy: 500ms pause, 12s hard-cap (chosen)
- Paste mode: clipboard + Ctrl+V with restore (chosen)
- Test scope: unit + slow integration (defaulted on user's "no preference")
- Window behavior: HUD-on-top without focus steal (user request, locked in)
