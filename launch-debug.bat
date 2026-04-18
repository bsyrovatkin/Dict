@echo off
rem Debug launcher: keeps console visible so you can see logs/errors.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m dict
) else (
    python -m dict
)
echo.
echo [process exited, press any key to close window]
pause > nul
