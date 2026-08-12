# Video Compressor

Compress videos to a **target file size** (2-pass x264, accurate to ~2%) or to a
**target quality** (CRF). Ships as a CLI, a desktop GUI, and a local web app —
all built on ffmpeg, with zero Python dependencies for the core.

**Live docs:** https://ronaldbvirinyangwe.github.io/video_compressor

## Requirements

- Python 3.9+
- `ffmpeg` + `ffprobe` on your PATH ([download](https://ffmpeg.org/download.html))

## Install

```bash
pip install 'scales-video-compressor[web]'   # from PyPI (includes the web UI)
pip install .                                # from source: CLI + desktop GUI
```

This gives you a global `video-compressor` command. You can also run it
without installing: `python -m video_compressor.cli compress <file>`.

## Usage

```
video-compressor compress input.mp4                       # CRF 23 quality default
video-compressor compress input.mp4 -c 18                 # higher quality
video-compressor compress input.mp4 -s 100                # target ~100 MiB (2-pass)
video-compressor compress input.mp4 -s 64 -o out.mp4 -p veryslow -a 96
video-compressor compress input.mp4 -c 18 -e nvenc        # hardware encode
video-compressor web                                     # open local web UI
video-compressor gui                                     # launch desktop GUI
```

### Options

| Flag | Meaning |
|------|---------|
| `-s, --size MiB` | Target output size (2-pass encode). |
| `-c, --crf N` | Constant Rate Factor. Lower = better. 18 high, 23 good, 28 small. |
| `-e, --encoder` | `software` (default), `nvenc`, `vaapi` or `videotoolbox`. Hardware encoders are single-pass, so size becomes approximate. |
| `-o, --output FILE` | Output path (default: `INPUT_compressed.mp4`). |
| `-p, --preset` | x264 preset: `ultrafast`…`veryslow` (default `medium`). |
| `-a, --audio-kbps N` | Audio bitrate, 32–320 (default `128`). Freed if unused. |
| `-y, --yes` | Overwrite existing output without prompting. |

`-s` wins when both are given; with neither, quality mode (CRF 23) is used.
Set `VC_VAAPI_DEVICE` to override the VAAPI device (default `/dev/dri/renderD128`).
The web UI and GUI only offer the encoders your ffmpeg build actually supports.

## How target-size works

For a target `S` MiB over `D` seconds:

```
total = S * 8 * 1024 / D           # kbps overall
video = total * 0.95 - audio_kbps  # 5% headroom for container/muxer overhead
```

The video track is then encoded in two passes at that bitrate, so the final file
lands within ~1–2% of the target (muxing overhead matters most at very small sizes).

## Interfaces

- **CLI** — scriptable, works headless.
- **Web UI** (`video-compressor web`) — drag & drop in your browser, target
  size/quality sliders, live progress, download link. Files never leave your machine.
- **Desktop GUI** (`video-compressor gui`) — native Tkinter window, zero extra deps.

## Tests

```bash
pip install '.[dev]'
pytest
```

Integration tests need ffmpeg and are skipped automatically when it's missing.

## Release pipeline

- **CI** — pytest on Python 3.9 & 3.12 for every push/PR (.github/workflows/ci.yml).
- **PyPI** — push a `v*` tag to build the sdist+wheel, publish to PyPI via trusted
  publishing, and draft a GitHub release (.github/workflows/publish.yml).
- **Docs** — `docs/` deploys to GitHub Pages on push to `main`
  (.github/workflows/docs.yml); enable Pages with "GitHub Actions" as the source.

## Notes

- Refuses to write over the input file.
- Output is H.264/AAC MP4 with `+faststart` for instant web streaming.
- Say `n` to the overwrite prompt to abort.