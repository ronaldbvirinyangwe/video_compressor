import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_compressor import core  # noqa: E402


def _which(name):
    for path in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return True
    return False


def run_ffmpeg(args):
    if subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *args]).returncode != 0:
        raise RuntimeError("ffmpeg failed to build test fixture")


# ---------------------------------------------------------------- probe ----

def test_parse_probe():
    data = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "duration": 10.5},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": 10.0},
    }
    info = core.parse_probe(data)
    assert info == {
        "duration": 10.0,
        "has_audio": True,
        "video_codec": "h264",
        "width": 1920,
        "height": 1080,
    }


def test_parse_probe_falls_back_to_stream_duration():
    data = {"streams": [{"codec_type": "video", "duration": "7.25"}], "format": {"duration": "N/A"}}
    assert core.parse_probe(data)["duration"] == 7.25


def test_parse_probe_rejects_no_video():
    with pytest.raises(core.CompressError):
        core.parse_probe({"streams": [{"codec_type": "audio"}]})


# --------------------------------------------------------- size budget ----

def test_compute_video_kbps_basic():
    # 32 MiB over 60 s: total = 32*8192/60 = 4369 kbps; minus headroom & audio
    v = core.compute_video_kbps(32, 60, audio_kbps=128, has_audio=True)
    assert 4000 <= v <= 4100


def test_compute_video_kbps_no_audio_frees_budget():
    with_audio = core.compute_video_kbps(32, 60, audio_kbps=128, has_audio=True)
    without = core.compute_video_kbps(32, 60, audio_kbps=128, has_audio=False)
    assert without == with_audio + 128


def test_compute_video_kbps_too_small_raises():
    with pytest.raises(core.CompressError, match="target too small"):
        core.compute_video_kbps(0.01, 60, audio_kbps=128, has_audio=True)


def test_compute_video_kbps_bad_input():
    with pytest.raises(core.CompressError):
        core.compute_video_kbps(0, 10, audio_kbps=128, has_audio=True)
    with pytest.raises(core.CompressError):
        core.compute_video_kbps(10, 0, audio_kbps=128, has_audio=True)


# ------------------------------------------------------------ paths -------

def test_default_output_replaces_extension():
    assert core.default_output("clips/video.mov") == "clips/video_compressed.mp4"


def test_ensure_safe_paths_same_file_raises(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    with pytest.raises(core.CompressError, match="refusing to overwrite"):
        core.ensure_safe_paths(str(src), str(src))
    # even via a symlink
    link = tmp_path / "link.mp4"
    link.symlink_to(src)
    with pytest.raises(core.CompressError):
        core.ensure_safe_paths(str(src), str(link))


def test_ensure_safe_paths_distinct_ok(tmp_path):
    src = tmp_path / "a.mp4"
    dst = tmp_path / "b.mp4"
    src.write_bytes(b"x")
    core.ensure_safe_paths(str(src), str(dst))  # must not raise


# -------------------------------------------------------- cmd building ----

def test_build_size_commands_structure():
    cmds = core.build_size_commands("in.mov", "out.mp4", 4000, "medium", 128, True, "/tmp/x264")
    assert len(cmds) == 2
    assert "-pass" in cmds[0] and "1" in cmds[0] and "-an" in cmds[0]
    assert "-pass" in cmds[1] and "2" in cmds[1]
    assert cmds[1][-1] == "out.mp4"
    assert "0:a:0?" in cmds[1] and "-c:a" in cmds[1]
    assert "libx264" in cmds[0] and "4000k" in cmds[0]


def test_build_size_commands_no_audio_omits_audio_args():
    cmds = core.build_size_commands("in.mov", "out.mp4", 4000, "medium", 128, False, "/tmp/x264")
    assert "0:a:0?" not in cmds[1] and "-c:a" not in cmds[1]


def test_build_crf_command():
    cmd = core.build_crf_command("in.mov", "out.mp4", 18, "slow", 192, True)
    assert cmd[-1] == "out.mp4"
    assert "-crf" in cmd and "18" in cmd
    assert "slow" in cmd and "192k" in cmd
    assert "+faststart" in cmd


# ---------------------------------------------------------- encoders ------

def test_build_crf_command_nvenc():
    cmd = core.build_crf_command("in.mov", "out.mp4", 18, "medium", 128, True, encoder="nvenc")
    joined = " ".join(cmd)
    assert "h264_nvenc" in joined
    assert "-cq" in joined and "18" in joined
    assert "-rc" in joined and "vbr" in joined
    assert "-crf" not in joined


def test_build_crf_command_vaapi():
    cmd = core.build_crf_command("in.mov", "out.mp4", 18, "medium", 128, False, encoder="vaapi")
    joined = " ".join(cmd)
    assert "h264_vaapi" in joined and "-vaapi_device" in joined
    assert "-qp" in joined and "18" in joined


def test_build_size_commands_hw_is_single_pass():
    cmds = core.build_size_commands("in.mov", "out.mp4", 4000, "medium", 128, True, "/tmp/x264", encoder="nvenc")
    assert len(cmds) == 1
    joined = " ".join(cmds[0])
    assert "h264_nvenc" in joined and "-b:v" in joined and "4000k" in joined
    assert "-pass" not in joined and "-maxrate" in joined


def test_build_size_commands_software_is_two_pass():
    cmds = core.build_size_commands("in.mov", "out.mp4", 4000, "medium", 128, True, "/tmp/x264", encoder="software")
    assert len(cmds) == 2


def test_available_encoders_contains_software():
    if _which("ffmpeg"):
        assert "software" in core.available_encoders()


def test_unknown_encoder_raises():
    with pytest.raises(core.CompressError):
        core._hw_quality_args("bogus", 20)


# -------------------------------------------------------- encode helper ---

def test_encode_falls_back_to_crf(monkeypatch):
    calls = []
    for name in ("encode_to_size", "encode_crf"):
        monkeypatch.setattr(core, name, lambda *a, name=name, **kw: calls.append(name) or {"duration": 1})
    info, crf = core.encode("a", "b", size_mb=-1, crf=None)
    assert calls == ["encode_crf"] and crf == 23


def test_encode_uses_size_when_positive(monkeypatch):
    calls = []
    for name in ("encode_to_size", "encode_crf"):
        monkeypatch.setattr(core, name, lambda *a, name=name, **kw: calls.append(name) or {"duration": 1})
    info, crf = core.encode("a", "b", size_mb=50, crf=23)
    assert calls == ["encode_to_size"] and crf is None


# --------------------------------------------------- integration (ffmpeg) --

@pytest.mark.skipif(not _which("ffmpeg"), reason="ffmpeg/ffprobe not available")
def test_end_to_end_crf(tmp_path):
    src = tmp_path / "src.mp4"
    run_ffmpeg([
        "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "fast", "-c:a", "aac",
        str(src),
    ])
    out = tmp_path / "out.mp4"
    info = core.encode_crf(str(src), str(out), crf=23, preset="fast")
    assert out.exists() and out.stat().st_size > 0
    assert core.probe(str(out))["width"] == 320
    assert info["width"] == 320


@pytest.mark.skipif(not _which("ffmpeg"), reason="ffmpeg/ffprobe not available")
def test_end_to_end_size_and_progress(tmp_path):
    src = tmp_path / "src.mp4"
    run_ffmpeg([
        "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=30",
        "-c:v", "libx264", "-preset", "fast",
        str(src),
    ])
    out = tmp_path / "out.mp4"
    ticks = []
    core.encode_to_size(str(src), str(out), size_mb=2, preset="fast", audio_kbps=128,
                        on_progress=lambda pct, msg: ticks.append((pct, msg)))
    assert out.exists() and out.stat().st_size > 0
    assert ticks and ticks[0][1].startswith("Pass 1")
    assert any(t[1].startswith("Pass 2") for t in ticks)
    assert ticks[-1][0] >= 95  # final -progress tick can stop at the last frame's timestamp


# ------------------------------------------------------ ffmpeg absence -----

def test_check_ffmpeg_missing_raises(monkeypatch):
    monkeypatch.setattr(core.shutil, "which", lambda b: None)
    with pytest.raises(core.CompressError, match="ffmpeg"):
        core.check_ffmpeg()