# Dict

<p align="center">
  <img src="assets/icon_idle.png" width="160" alt="Dict icon">
</p>

**Jarvis-style voice-to-clipboard transcriber for Windows and macOS.**
Press `F9` (or your bound hotkey), speak, press again — Russian/English speech
is transcribed locally via Whisper and lands in your clipboard / auto-pastes
into the focused text field. A small history window shows the last five
transcriptions with one-click copy.

<p align="center">
  <img src="docs/screenshot.png" width="360" alt="Main window">
</p>

## Quick start (Windows, 2 minutes)

1. **[Download `dict-windows-x64.zip`](https://github.com/bsyrovatkin/Dict/releases/latest)** (~134 MB)
2. Extract anywhere (e.g. `C:\Tools\dict\`)
3. Run **`dict.exe`** — that's it. No Python, no compilation, no setup.
4. Press **F9** in any text field → speak → press F9 again → text is typed where your cursor was.

[Full install guide ↓](#install--windows-no-python-no-compilation)

## Features

- **Local transcription** with `faster-whisper` (tiny → large-v3 selectable)
- **Neon HUD** with 54-segment VU ring reacting to your voice in real time
- **Configurable hotkey** — rebind live, supports Russian keyboard layout
- **Mic gain** 0.5×–5.0× software boost for quiet microphones
- **Start / stop audio cues**, customisable
- **Single-instance**, stays in the system tray

## Install — Windows (no Python, no compilation)

This is the recommended path for end users.

1. Open the **[Releases page](https://github.com/bsyrovatkin/Dict/releases/latest)**
   and download **`dict-windows-x64.zip`** (~134 MB).
2. Extract the zip anywhere convenient, e.g. `C:\Tools\dict\`. You'll get a folder
   called `dict\` containing `dict.exe` and `_internal\` next to it.
3. Double-click **`dict.exe`** (or `launch-exe.bat` if you keep the folder structure).
4. On first launch, Windows may show a SmartScreen warning ("Windows protected your PC").
   Click **More info** → **Run anyway** — the binary is unsigned but built from this
   public repo via PyInstaller.
5. The Whisper model (~470 MB for `small`, ~3 GB for `large-v3`) downloads on first use
   into `%USERPROFILE%\.cache\huggingface\hub\`.

### CUDA acceleration (optional)

If you have an NVIDIA GPU with ≥4 GB VRAM, Dict auto-detects CUDA via ctranslate2 and
uses `int8_float16` compute — Whisper large-v3 transcribes a 10-second clip in
~0.5–1 s on RTX 30/40 series. No CUDA toolkit install needed — the runtime DLLs ship
inside the zip.

### Optional: LLM polish (matches ChatGPT-voice quality)

Whisper transcribes faithfully but raw — "um", "э", false starts, missing punctuation.
If you set the `ANTHROPIC_API_KEY` environment variable, Dict will pipe each transcript
through Claude Haiku for a final cleanup (~$0.0001 / dictation, ~200–500 ms). Fail-soft:
no key or no network → raw Whisper output as before.

```powershell
setx ANTHROPIC_API_KEY "sk-ant-…"   # one-time, then restart Dict
```

## Install — from source

For development. Requires **Python 3.10+** and a working microphone.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts\gen_assets.py         # regenerate icons / sounds
python -m dict                       # run
```

## Run

- **Normal:** double-click `launch.bat` (no console).
- **Debug:** double-click `launch-debug.bat` for a log console.
- **Built exe:** `dist\dict\dict.exe`.

Settings (⚙ icon in window header) — rebind hotkey, pick model, adjust mic
gain. Changes save to `%APPDATA%\dict\settings.json`.

## Build release

```powershell
.venv\Scripts\activate
pip install pyinstaller
pyinstaller dict.spec
```

Output: `dist\dict\dict.exe` (one-dir, ~330 MB with all runtimes).

## Build for macOS (run ON a Mac)

```bash
git clone https://github.com/bsyrovatkin/Dict.git && cd Dict
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" pyinstaller
pyinstaller dict-mac.spec
# Output: dist/Dict.app
```

**First-run permissions** (macOS only):
1. Launch `Dict.app` once — you'll be prompted for Microphone access (allow).
2. Open **System Settings → Privacy & Security → Accessibility**, click `+`, add `Dict.app`. This lets the global hotkey work and lets Dict type into the focused field.
3. Restart Dict.app.

On Apple Silicon (M1/M2/M3) Whisper runs on CPU via ctranslate2 (no Metal/CoreML support yet); a `small` model transcribes ~3s audio in ~1-2s.

## Troubleshooting

- **No input device / silent recording:** in Windows `Settings → Privacy →
  Microphone`, enable **Microphone access**, **Let apps access your
  microphone**, and **Let desktop apps access your microphone** (the last
  one is what controls Python). Then `Win+R → mmsys.cpl → Recording` —
  set your mic as **Default Device**.
- **Hotkey doesn't fire:** another app may suppress it. Use ⚙ to rebind,
  or click the record circle in the window instead.
- **Transcription slow:** without a ≥4 GB CUDA GPU, Whisper runs CPU int8.
  A 10-second clip ≈ 3–6 s on a modern laptop CPU. Pick a smaller model
  in settings.
- **Mic too quiet:** raise **MIC GAIN** in settings.

## Files

- `%APPDATA%\dict\settings.json` — user settings (hotkey, model, gain).
- `dict.log` — append-only transcription log (project root when run from
  source; next to `dict.exe` when run as a bundle).
- `%TEMP%\dict.lock` — single-instance lockfile.
- `%USERPROFILE%\.cache\huggingface\hub\` — Whisper model cache.

## Tech

- **UI:** PySide6 (Qt 6.6), frameless window, QPainter for the HUD widget.
- **STT:** faster-whisper (ctranslate2).
- **Audio:** sounddevice (PortAudio).
- **Hotkey:** pynput (cross-platform: low-level Windows hook on Win, CGEventTap on macOS).
- **Build:** PyInstaller one-dir.

## License

MIT — see [LICENSE](LICENSE).
