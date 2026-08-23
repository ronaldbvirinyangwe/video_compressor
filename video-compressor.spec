# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Video Compressor desktop app (one-file build).

Build with:  pyinstaller --clean --noconfirm video-compressor.spec
Output:      dist/video-compressor(.exe) on Windows/Linux,
             dist/Video Compressor.app + dist/video-compressor on macOS.

If a bin/ folder with ffmpeg/ffprobe binaries exists at build time they are
bundled into the app (see .github/workflows/release.yml); otherwise the
packaged app falls back to ffmpeg on the user's PATH.
"""

import os

binaries = []
if os.path.isdir("bin"):
    binaries = [(os.path.join("bin", f), ".") for f in sorted(os.listdir("bin"))]

a = Analysis(
    ["desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["flask", "jinja2", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="video-compressor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

app = BUNDLE(
    exe,
    name="Video Compressor.app",
    icon=None,
)  # macOS only; ignored elsewhere
