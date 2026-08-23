"""Entry point for the packaged desktop app (PyInstaller).

Build with:  pyinstaller --clean --noconfirm video-compressor.spec
"""

from video_compressor.gui import main

if __name__ == "__main__":
    main()
