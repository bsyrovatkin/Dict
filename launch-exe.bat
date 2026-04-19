@echo off
rem Runs the bundled standalone dict.exe from dist\dict\.
rem Use this after you've run `pyinstaller dict.spec` or downloaded
rem the release zip and extracted it to dist\dict\.
cd /d "%~dp0"
if exist "dist\dict\dict.exe" (
    start "" "dist\dict\dict.exe"
) else (
    echo dist\dict\dict.exe not found.
    echo Build it with:  pyinstaller dict.spec
    echo Or download dict-windows-x64.zip from the Releases page
    echo and extract so that dist\dict\dict.exe exists.
    pause
)
