# PyInstaller spec for macOS. Build on a Mac with:
#     pyinstaller dict-mac.spec
# Produces: dist/Dict.app
from __future__ import annotations
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs  # noqa

PROJECT_DIR = Path(SPEC).resolve().parent  # noqa

_fw_data = collect_data_files("faster_whisper")
_ort_data = collect_data_files("onnxruntime")
_ct_dlls = collect_dynamic_libs("ctranslate2")

a = Analysis(  # noqa
    ["dict/__main__.py"],
    pathex=[str(PROJECT_DIR)],
    binaries=_ct_dlls,
    datas=[
        ("assets/*.wav", "assets"),
        ("assets/*.png", "assets"),
        ("assets/*.ico", "assets"),
        ("assets/fonts/*.ttf", "assets/fonts"),
        *_fw_data,
        *_ort_data,
    ],
    hiddenimports=[
        "faster_whisper",
        "faster_whisper.vad",
        "ctranslate2",
        "tokenizers",
        "onnxruntime",
        "pynput",
        "pynput.keyboard._darwin",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)  # noqa

exe = EXE(  # noqa
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Dict",
    debug=False,
    strip=False, upx=False,
    console=False,
    icon=None,  # add an .icns later if desired
    argv_emulation=False,
)

coll = COLLECT(  # noqa
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, upx_exclude=[],
    name="Dict",
)

app = BUNDLE(  # noqa
    coll,
    name="Dict.app",
    icon=None,
    bundle_identifier="dev.bsyrovatkin.dict",
    info_plist={
        "CFBundleDisplayName": "Dict",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "NSHighResolutionCapable": True,
        # Microphone access (required for any audio capture on modern macOS)
        "NSMicrophoneUsageDescription": "Dict needs the microphone to transcribe your speech.",
        # Accessibility for global hotkey + simulated typing
        # (User must grant explicitly in System Settings -> Privacy & Security
        # -> Accessibility after first launch.)
    },
)
