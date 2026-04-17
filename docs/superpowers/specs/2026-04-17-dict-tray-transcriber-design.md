# Dict — Tray Voice Transcriber (Design)

Date: 2026-04-17
Project: `D:/Projects/Dict`
Author: brainstorming session

## 1. Summary

Tray-resident Windows utility that records microphone audio on a global hotkey, transcribes it with local Whisper (auto-detect RU/EN), copies the result to the clipboard, and keeps a small visible history. Reuses `faster-whisper` already wired up in `D:/Games/Content Mashine Project`.

## 2. Product decisions (fixed)

| Decision | Value |
|---|---|
| Whisper model | `faster-whisper` `small` (multilingual) |
| Language | auto-detect |
| Stack | Python 3.10+, Windows only |
| GUI | `pystray` tray + `tkinter` history window |
| Global hotkey | `Win+B`, toggle (press = start, press = stop) |
| Hotkey lib | `pynput` (no admin required) |
| Audio capture | `sounddevice` @ 16 kHz mono int16 |
| History window | list of last **5** transcriptions with timestamp; click = copy to clipboard |
| Window open/close | single click on tray icon toggles; plus auto-show for 2 s after each transcription |
| Sounds | short (~100 ms) generated sine WAVs: start 880 Hz, stop 440 Hz |
| Clipboard | `pyperclip` |
| Log | append-only `dict.log`, format `YYYY-MM-DD HH:MM:SS \| <text>\n` |
| WAV retention | none; audio discarded after transcription |
| Windows autostart | no; launched manually via `launch.bat` |
| Empty/silent recording | silently dropped, nothing written |
| Max recording length | none |
| Single-instance | yes, lockfile in `%TEMP%/dict.lock` |

## 3. Architecture

Single-process Python app with modules communicating via a `queue.Queue` and Tk `after()` callbacks. Three threads:

- **Main thread** — pystray event loop (tray + Tk UI).
- **Recorder thread** — implicit, owned by `sounddevice.InputStream` callback.
- **Transcriber thread** — spawned ad-hoc per job so UI never blocks.

```
HotkeyWatcher ──▶ Controller ──▶ Recorder ──▶ Transcriber
                      │                              │
                      ▼                              ▼
                  TrayIcon                    Clipboard + Logger
                      │                              │
                      ▼                              ▼
                 HistoryWindow ◀── new-entry event ──┘
```

State machine (`Controller`):

```
idle ──Win+B──▶ recording ──Win+B──▶ transcribing ──result or error──▶ idle
```

`Win+B` is ignored while in `transcribing`.

## 4. Components

Source layout under `D:/Projects/Dict/`:

```
pyproject.toml
launch.bat
README.md
assets/
  icon_idle.ico
  icon_recording.ico
  icon_busy.ico
  start.wav
  stop.wav
dict/
  __main__.py          # single-instance lock, wire & run Controller
  config.py            # constants (hotkey, model, sample rate, paths)
  controller.py        # state machine; orchestrates recorder/transcriber/tray/history
  hotkey.py            # pynput GlobalHotKeys wrapper
  recorder.py          # sounddevice capture; start()/stop()->np.ndarray
  transcriber.py       # lazy-loaded faster-whisper; transcribe(np.ndarray)->str
  tray.py              # pystray icon, menu (Quit), icon switching
  window.py            # tkinter history window, click-to-copy, auto-show
  history.py           # deque(maxlen=5) of (timestamp, text)
  clipboard.py         # pyperclip wrapper
  logger.py            # append-only text logger
  sounds.py            # winsound.PlaySound async
tests/
  test_controller.py
  test_history.py
  test_logger.py
  test_transcriber_smoke.py
```

### Module responsibilities & interfaces

- **`config.HOTKEY = "<cmd>+b"`**, `MODEL_SIZE = "small"`, `SAMPLE_RATE = 16000`, `HISTORY_MAX = 5`, `MIN_RECORDING_SEC = 0.5`, `SILENCE_RMS_INT16 = 200` (audio considered silent if its RMS over the whole recording is below this value on a ±32768 int16 scale — ≈ -44 dBFS, a permissive threshold).
- **`hotkey.HotkeyWatcher(on_trigger: Callable[[], None])`** — `start()` / `stop()`.
- **`recorder.Recorder(sample_rate)`** — `start()`, `stop() -> np.ndarray[int16] | None`. Returns `None` if below `MIN_RECORDING_SEC` or silent (RMS threshold).
- **`transcriber.Transcriber(model_size)`** — `ensure_loaded()`, `transcribe(audio: np.ndarray) -> str` (empty string if Whisper returns nothing).
- **`tray.Tray(icons: dict[str, Path], on_left_click, on_quit)`** — `set_state("idle"|"recording"|"busy"|"error")`, `run()`.
- **`window.HistoryWindow(history, on_copy)`** — `toggle()`, `show_for(seconds)`, `refresh()`.
- **`history.History(maxlen)`** — `push(text)`, `items() -> list[Entry]`.
- **`clipboard.set_text(text)`**, **`logger.append(text)`**, **`sounds.play_start()` / `sounds.play_stop()`**.
- **`controller.Controller`** — wires the above; one method per queued command.

## 5. Data flow (one cycle)

1. `HotkeyWatcher` detects `Win+B` → enqueues `HOTKEY` command.
2. `Controller` (idle) → `state=recording`, `Recorder.start()`, `sounds.play_start()`, `tray.set_state("recording")`.
3. User speaks. `Recorder` callback appends int16 chunks to a list.
4. `HotkeyWatcher` detects `Win+B` again → enqueues `HOTKEY`.
5. `Controller` (recording) → `audio = Recorder.stop()`, `sounds.play_stop()`, `tray.set_state("busy")`, `state=transcribing`, spawn worker thread.
6. Worker: `text = Transcriber.transcribe(audio)`; posts `DONE(text)` back via `queue`.
7. `Controller` (transcribing) on `DONE`:
   - If `text` non-empty: `clipboard.set_text(text)`, `history.push(text)`, `logger.append(text)`, `window.refresh()`, `window.show_for(2)`.
   - Always: `tray.set_state("idle")`, `state=idle`.
8. If `audio is None` in step 5 (empty/silent): skip steps 6-7 apart from state reset.

## 6. Error handling

| Condition | Behavior |
|---|---|
| No input device | Tray → `error` icon, balloon `"Microphone not available"`, log `[ERROR]`, hotkey disabled until restart. |
| Whisper model missing on first run | Before tray shows: blocking model download with balloon `"Downloading Whisper small…"`; hotkey registered only after load. |
| Recorder exception mid-capture | Log exception, play `stop.wav`, state → `idle`, no transcription attempted. |
| Transcriber exception | Log exception, balloon `"Transcription failed"`, state → `idle`. |
| Hotkey pressed during `transcribing` | Ignored, debug-log only. |
| Clipboard write fails | Log warning; history+log still updated so user can copy from window. |
| Second instance launched | Lock acquire fails → print `"Dict already running"`, exit 0. |
| Recording < 0.5 s or RMS < silence threshold | Silently drop, no clipboard/log/history entry, state → `idle`. |

## 7. Testing strategy

**TDD-friendly (unit):**
- `test_controller.py` — `Controller` with mocked `Recorder`, `Transcriber`, `Tray`, `Clipboard`, `Logger`. Assert state transitions and the precise sequence of calls for: idle→rec→trans→idle (happy), empty-drop, transcribe-exception.
- `test_history.py` — `deque(maxlen=5)` eviction; most-recent-first ordering.
- `test_logger.py` — line format, append semantics, creation of parent dirs.

**Smoke (integration, not in CI — requires model):**
- `test_transcriber_smoke.py` — bundled short RU WAV in `tests/fixtures/ru_ping.wav`; loads model; asserts non-empty output. Marked `@pytest.mark.slow`.

**Manual E2E (documented in README):**
1. `launch.bat`; tray icon appears.
2. `Win+B`, say "проверка связи", `Win+B`.
3. Verify: start/stop sounds played, history window auto-appears for ~2 s, list shows new entry with timestamp, clipboard contains the text, `dict.log` has the line.
4. Click tray icon — window toggles.
5. Click history entry — clipboard re-updated.
6. Launch a second `launch.bat` — second instance exits without taking over.

## 8. Dependencies

`pyproject.toml`:

```
faster-whisper  # transcription (reuse from Content Mashine)
sounddevice     # audio capture
numpy           # buffers
pynput          # global hotkey
pystray         # tray icon
pillow          # icon loading
pyperclip       # clipboard
# tkinter and winsound are stdlib on Windows Python
```

CUDA auto-detect reused via a slimmed-down copy of `probe_cuda_available` from `app/services/whisper.py` (falls back to CPU int8).

## 9. Out of scope (explicit YAGNI)

- Cross-platform (Linux/macOS) — Windows-only, Win+B + winsound.
- Windows autostart registration.
- Editing transcriptions in the window.
- Search over log history in the window.
- Multiple hotkeys / multiple modes.
- Pause-during-recording.
- Whisper model selector UI.
- WAV retention / re-transcription.
- Tests for tray/GUI layer (manual E2E covers it).

## 10. Risks

- **pynput + Win key**: pynput sometimes leaks `Win` press events to Windows shell; will validate during first spike by pressing `Win+B` while a full-screen app is focused.
- **faster-whisper model download on first run is ~470 MB**: blocking UI is fine but must show feedback; cached under `%HF_HOME%` and reused after.
- **tkinter + pystray on same thread**: both drive their own loop; `pystray` runs in main thread and Tk windows are created via `pystray.Icon.run_detached()` pattern or Tk mainloop with `pystray` in a daemon thread — decision deferred to implementation spike (first task in the plan).
