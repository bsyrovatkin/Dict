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
