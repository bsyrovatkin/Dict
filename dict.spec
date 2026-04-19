# PyInstaller spec for Dict. Build with:
#     pyinstaller dict.spec
# Produces:
#     dist/dict/dict.exe   (one-dir bundle, faster startup)
# Output is ~200-400 MB because faster-whisper pulls in ctranslate2
# and the user's chosen model is downloaded on first run (not bundled).
from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs  # noqa: F821

# `SPEC` is injected by PyInstaller when this spec is executed.
PROJECT_DIR = Path(SPEC).resolve().parent  # noqa: F821

# faster-whisper ships silero_vad_v6.onnx under faster_whisper/assets/ and
# that file is loaded at runtime via onnxruntime. PyInstaller does not copy
# non-py data files by default; collect_data_files pulls them all in.
_fw_data = collect_data_files("faster_whisper")
# onnxruntime has platform DLLs; some of them are pure data plugins
_ort_data = collect_data_files("onnxruntime")
# ctranslate2 ships the C++ runtime as DLLs
_ct_dlls = collect_dynamic_libs("ctranslate2")

a = Analysis(  # noqa: F821
    ["dict/__main__.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=_ct_dlls,
    datas=[
        ("assets/*.ico", "assets"),
        ("assets/*.wav", "assets"),
        ("assets/*.png", "assets"),
        *_fw_data,
        *_ort_data,
    ],
    hiddenimports=[
        # faster-whisper uses runtime imports that PyInstaller sometimes misses
        "faster_whisper",
        "faster_whisper.vad",
        "ctranslate2",
        "tokenizers",
        "onnxruntime",
        "onnxruntime.capi._pybind_state",
        # keyboard library registers handlers dynamically
        "keyboard._winkeyboard",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",     # we use Qt; excluding tkinter saves ~5 MB
        "matplotlib",
        "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dict",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                                       # windowed app
    icon=str(PROJECT_DIR / "assets" / "dict.ico"),
    version_info=None,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="dict",
)
