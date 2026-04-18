# Dict

Tray-resident voice-to-clipboard transcriber for Windows. Press `Ctrl+Shift+V` to start recording, press again to stop — the transcription lands in your clipboard and a small history window.

## Install

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

First launch downloads `faster-whisper small` (~470 MB) into the Hugging Face cache.

## Run

- **Normal:** double-click `launch.bat` (no console window).
- **Debug:** double-click `launch-debug.bat` to keep a console with logs open.

You can also record without the hotkey by clicking the big **Start / Stop** button in the window.

## Manual smoke test

1. Launch. Tray icon appears.
2. `Ctrl+Shift+V`, say "проверка связи", `Ctrl+Shift+V`.
3. Start/stop sounds play. History window appears for ~2 s. Clipboard contains the text. `dict.log` has a new line.
4. Click tray icon — window toggles. Click a history row — clipboard re-updated.
5. Launch a second instance — it exits with "Dict already running".
6. Right-click tray → Quit — process exits cleanly.

## Troubleshooting

- **Nothing happens on Ctrl+Shift+V:** another app may be holding the hotkey, or pynput lost the listener. Use the **Start / Stop** button in the window as a fallback, or change `HOTKEY` in `dict/config.py` (e.g. `"<ctrl>+<alt>+v"`) and relaunch.
- **"Microphone not available":** check Windows Sound settings → Input. Close apps that may be holding exclusive access (Teams, Discord, OBS).
- **Transcription is slow:** without a CUDA GPU (≥4 GB VRAM) Whisper runs on CPU int8. A 10-second clip takes roughly 3–6 s on a modern laptop CPU.
- **Words missed at the start/end of recordings:** leave ~0.3 s of silence before speaking and before pressing the hotkey again.
- **Model re-downloads every run:** set `HF_HOME` to a persistent directory.

## Files

- `dict.log` — append-only transcription log in the project root.
- `%TEMP%/dict.lock` — single-instance lockfile.
- Model cache — `%USERPROFILE%\.cache\huggingface\hub\` (shared with Content Mashine).
