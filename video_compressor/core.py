"""Core video compression logic shared by the CLI, web UI and desktop GUI.

The library shells out to the system ``ffmpeg``/``ffprobe`` binaries and has
no third-party Python dependencies.
"""

import os
import json
import shutil
import subprocess
import sys
import tempfile

PRESETS = [
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
]

ENCODERS = {
    "software": {"codec": "libx264", "two_pass": True, "label": "Software (libx264)"},
    "nvenc": {"codec": "h264_nvenc", "two_pass": False, "label": "NVIDIA NVENC"},
    "vaapi": {"codec": "h264_vaapi", "two_pass": False, "label": "Intel/AMD VAAPI"},
    "videotoolbox": {"codec": "h264_videotoolbox", "two_pass": False, "label": "Apple VideoToolbox"},
}

VAAPI_DEVICE = os.environ.get("VC_VAAPI_DEVICE", "/dev/dri/renderD128")

MEDIA_HEADROOM = 0.95  # reserve ~5% of budget for container/muxer overhead
MIN_VIDEO_KBPS = 150   # below this quality is unwatchable -> bail out


class CompressError(Exception):
    """A user-facing error (bad input, missing ffmpeg, impossible target...)."""


def _resolve_binary(name):
    """Locate ffmpeg/ffprobe: VC_FFMPEG_DIR > PyInstaller bundle > PATH."""
    search = []
    env_dir = os.environ.get("VC_FFMPEG_DIR")
    if env_dir:
        search.append(env_dir)
    bundle = getattr(sys, "_MEIPASS", None)  # one-file extraction dir
    if bundle:
        search.append(bundle)
    if getattr(sys, "frozen", False):  # dir of the packaged executable
        search.append(os.path.dirname(sys.executable))
    for d in search:
        path = os.path.join(d, name)
        if os.path.isfile(path):
            return path
    return shutil.which(name)


def check_ffmpeg():
    missing = [b for b in ("ffmpeg", "ffprobe") if _resolve_binary(b) is None]
    if missing:
        raise CompressError(
            f"{', '.join(missing)} not found (searched PATH and the app folder). "
            "Install ffmpeg (https://ffmpeg.org/download.html) or point "
            "VC_FFMPEG_DIR at a folder containing ffmpeg/ffprobe."
        )


def ffmpeg_path():
    return _resolve_binary("ffmpeg")


def ffprobe_path():
    return _resolve_binary("ffprobe")


def parse_probe(data):
    """Turn ffprobe JSON into the small info dict the encoders need."""
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise CompressError("input contains no video stream")

    try:
        duration = float(data["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        try:
            duration = float(video.get("duration", 0))
        except (TypeError, ValueError):
            duration = 0.0

    return {
        "duration": duration,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "video_codec": video.get("codec_name", "unknown"),
        "width": video.get("width"),
        "height": video.get("height"),
    }


def probe(input_path):
    check_ffmpeg()
def probe(input_path):
    check_ffmpeg()
    cmd = [
        ffprobe_path(), "-v", "error",
        "-print_format", "json",
        "-show_format", "-show_streams",
        input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise CompressError(f"could not read '{input_path}': {result.stderr.strip()}")
    return parse_probe(json.loads(result.stdout))


def default_output(input_path):
    root, _ = os.path.splitext(input_path)
    return f"{root}_compressed.mp4"


def ensure_safe_paths(input_path, output_path):
    src = os.path.realpath(input_path)
    dst = os.path.realpath(output_path)
    if src == dst:
        raise CompressError("output path must differ from the input file (refusing to overwrite the source)")
    if os.path.exists(dst) and os.path.samefile(src, dst):
        raise CompressError("output path points at the input file (refusing to overwrite the source)")


def compute_video_kbps(size_mb, duration, audio_kbps, has_audio):
    """Split a total size budget into video/audio bitrates (kbps)."""
    if size_mb <= 0:
        raise CompressError("target size must be a positive number of MiB")
    if not duration or duration <= 0:
        raise CompressError("could not determine video duration; cannot compute a size target")

    total_kbps = size_mb * 8 * 1024 / duration
    audio_budget = audio_kbps if has_audio else 0
    video_kbps = int(total_kbps * MEDIA_HEADROOM - audio_budget)

    if video_kbps < MIN_VIDEO_KBPS:
        raise CompressError(
            f"target too small: {size_mb} MiB over {duration:.0f}s leaves only "
            f"{video_kbps} kbps for video (minimum {MIN_VIDEO_KBPS} kbps). "
            "Increase the target size or lower the audio bitrate."
        )
    return video_kbps


def available_encoders():
    """Return the encoder keys this machine can actually run."""
    check_ffmpeg()
    out = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    got = ["software"]
    for name, spec in ENCODERS.items():
        if name != "software" and spec["codec"] in out:
            got.append(name)
    return got


def _base_prefix(encoder):
    cmd = [ffmpeg_path(), "-hide_banner", "-nostdin", "-y"]
    if encoder == "vaapi":
        cmd += ["-vaapi_device", VAAPI_DEVICE]
    return cmd


def _hw_quality_args(encoder, crf):
    cq = max(0, min(51, int(crf)))
    if encoder == "nvenc":
        return ["-cq", str(cq), "-rc", "vbr"]
    if encoder == "vaapi":
        return ["-qp", str(cq)]
    if encoder == "videotoolbox":
        return ["-q:v", str(cq)]
    raise CompressError(f"unsupported encoder: {encoder}")


def _video_args(encoder, preset, crf=None, video_kbps=None, passnum=None, logfile=None):
    spec = ENCODERS[encoder]
    if spec["two_pass"]:
        args = ["-c:v", spec["codec"], "-preset", preset]
        if crf is not None:
            args += ["-crf", str(crf)]
        else:
            args += ["-b:v", f"{video_kbps}k"]
            if passnum is not None:
                args += ["-pass", str(passnum), "-passlogfile", logfile]
        return args

    args = ["-c:v", spec["codec"]]
    if crf is not None:
        args += _hw_quality_args(encoder, crf)
    else:
        args += ["-b:v", f"{video_kbps}k"]
        if encoder == "nvenc":
            args += ["-maxrate", f"{int(video_kbps * 1.2)}k",
                     "-bufsize", f"{int(video_kbps * 2)}k", "-rc", "vbr"]
    return args


def _audio_args(audio_kbps, has_audio):
    if not has_audio:
        return []
    return ["-map", "0:a:0?", "-c:a", "aac", "-b:a", f"{audio_kbps}k"]


def build_size_commands(input_path, output_path, video_kbps, preset, audio_kbps, has_audio, logfile, encoder="software"):
    prefix = _base_prefix(encoder) + ["-i", input_path]
    audio = _audio_args(audio_kbps, has_audio)
    if ENCODERS[encoder]["two_pass"]:
        return [
            prefix + ["-map", "0:v:0"]
            + _video_args(encoder, preset, video_kbps=video_kbps, passnum=1, logfile=logfile)
            + ["-an", "-f", "null", "-"],
            prefix + ["-map", "0:v:0"]
            + _video_args(encoder, preset, video_kbps=video_kbps, passnum=2, logfile=logfile)
            + audio + ["-movflags", "+faststart", output_path],
        ]
    return [
        prefix + ["-map", "0:v:0"]
        + _video_args(encoder, preset, video_kbps=video_kbps)
        + audio + ["-movflags", "+faststart", output_path],
    ]


def build_crf_command(input_path, output_path, crf, preset, audio_kbps, has_audio, encoder="software"):
    return (
        _base_prefix(encoder) + ["-i", input_path, "-map", "0:v:0"]
        + _video_args(encoder, preset, crf=crf)
        + _audio_args(audio_kbps, has_audio)
        + ["-movflags", "+faststart", output_path]
    )


def run_command(cmd, on_progress=None):
    """Run ffmpeg.

    Without ``on_progress`` the terminal shows ffmpeg's live stats. With it,
    ffmpeg is switched to ``-progress pipe:1`` and the callback is invoked
    with the number of encoded seconds, which is handy for web/GUI progress.
    """
    if on_progress is None:
        result = subprocess.run(cmd, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            raise CompressError(f"ffmpeg exited with status {result.returncode}")
        return

    progress_cmd = cmd + ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]
    proc = subprocess.Popen(
        progress_cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.strip()
        if not line or b"=" not in line:
            continue
        key, _, value = line.partition(b"=")
        if key == b"out_time_us":
            try:
                on_progress(int(value) / 1_000_000)
            except ValueError:
                pass
        elif key == b"progress" and value == b"end":
            break
    stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
    if proc.wait() != 0:
        raise CompressError(f"ffmpeg exited with status {proc.returncode}: {stderr.strip()}")


def _wrap_progress(on_progress, duration, pass_index, pass_total):
    """Adapt run_command's seconds-callback to a percent + message callback."""
    def inner(sec):
        frac = min(sec, duration) / duration
        pct = ((pass_index - 1) + frac) / pass_total * 100
        on_progress(pct, f"Pass {pass_index}/{pass_total} ({frac * 100:.0f}%)")
    return inner


def encode_to_size(input_path, output_path, size_mb, preset="medium", audio_kbps=128, encoder="software", on_progress=None):
    info = probe(input_path)
    video_kbps = compute_video_kbps(size_mb, info["duration"], audio_kbps, info["has_audio"])

    logdir = tempfile.mkdtemp(prefix="vc2pass_")
    logfile = os.path.join(logdir, "x264")
    commands = build_size_commands(
        input_path, output_path, video_kbps, preset, audio_kbps, info["has_audio"], logfile, encoder
    )
    try:
        for i, cmd in enumerate(commands, start=1):
            cb = _wrap_progress(on_progress, info["duration"], i, len(commands)) if on_progress else None
            run_command(cmd, on_progress=cb)
    finally:
        shutil.rmtree(logdir, ignore_errors=True)
    return info


def encode_crf(input_path, output_path, crf=23, preset="medium", audio_kbps=128, encoder="software", on_progress=None):
    info = probe(input_path)
    cmd = build_crf_command(input_path, output_path, crf, preset, audio_kbps, info["has_audio"], encoder)
    cb = _wrap_progress(on_progress, info["duration"], 1, 1) if on_progress else None
    run_command(cmd, on_progress=cb)
    return info


def encode(input_path, output_path, size_mb=None, crf=None, preset="medium", audio_kbps=128,
           encoder="software", on_progress=None):
    """The single entry point. ``size_mb`` wins over ``crf`` when both are given.

    Returns the probed info dict and the ``--crf`` actually used when falling
    back to quality mode.
    """
    if size_mb is not None and size_mb > 0:
        info = encode_to_size(input_path, output_path, size_mb, preset, audio_kbps, encoder, on_progress)
        crf = None
    else:
        crf = 23 if crf is None else crf
        info = encode_crf(input_path, output_path, crf, preset, audio_kbps, encoder, on_progress)
    return info, crf


def size_report(input_path, output_path):
    in_size = os.path.getsize(input_path)
    out_size = os.path.getsize(output_path)
    mb = lambda n: n / (1024 * 1024)
    reduction = (1 - out_size / in_size) * 100
    return {
        "input_bytes": in_size,
        "output_bytes": out_size,
        "input_mb": mb(in_size),
        "output_mb": mb(out_size),
        "reduction": reduction,
    }


def fmt_mb(num_bytes):
    return f"{num_bytes / (1024 * 1024):.2f} MiB"