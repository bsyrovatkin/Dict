# Dict

<p align="center">
  <img src="assets/icon_idle.png" width="160" alt="Dict icon">
</p>

**Jarvis-style voice-to-clipboard transcriber for Windows and macOS.**
Press `F9` (or your bound hotkey), speak, press again — Russian/English speech
is transcribed locally via Whisper and lands in your clipboard. A small
history window shows the last five transcriptions with one-click copy.

<p align="center">
  <img src="docs/screenshot.png" width="360" alt="Main window">
</p>

## Features

- **Local transcription** with `faster-whisper` (tiny → large-v3 selectable)
- **Neon HUD** with 54-segment VU ring reacting to your voice in real time
- **Configurable hotkey** — rebind live, supports Russian keyboard layout
- **Mic gain** 0.5×–5.0× software boost for quiet microphones
- **Start / stop audio cues**, customisable
- **Single-instance**, stays in the system tray

## Install — from source

Requires **Python 3.10+** and a working microphone.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
python scripts\gen_assets.py         # regenerate icons / sounds
python -m dict                       # run
```

First launch downloads the Whisper model (~470 MB for `small`).

## Install — pre-built

Grab `dict-windows-x64.zip` from [Releases](../../releases), extract anywhere,
double-click `dict.exe`. No Python needed.

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
