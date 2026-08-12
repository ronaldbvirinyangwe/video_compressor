"""Command line interface: ``video-compressor compress|web|gui``."""

import argparse
import os
import sys

from . import __version__, core


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def build_compress_parser(subparsers):
    p = subparsers.add_parser(
        "compress", help="compress a single video to a size or quality",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", metavar="INPUT", help="input video file (any format ffmpeg reads)")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "-s", "--size", type=float, metavar="MiB",
        help="target output size in MiB (2-pass encode, very accurate)",
    )
    p.add_argument(
        "-c", "--crf", type=int, metavar="N",
        help="constant rate factor: lower is better quality (18 high, 23 good, 28 small). "
             "Defaults to 23 when --size is not given.",
    )
    p.add_argument("-o", "--output", metavar="FILE", help="output file path (default: INPUT_compressed.mp4)")
    p.add_argument("-p", "--preset", choices=core.PRESETS, default="medium", help="x264 speed/compression trade-off")
    p.add_argument("-a", "--audio-kbps", type=int, default=128, metavar="N", help="audio bitrate in kbps")
    p.add_argument(
        "-e", "--encoder", choices=list(core.ENCODERS), default="software",
        help="encoder to use (hardware encoders are single-pass, so size is approximate)",
    )
    p.add_argument("-y", "--yes", action="store_true", help="overwrite an existing output without prompting")
    p.set_defaults(func=cmd_compress)


def cmd_compress(args):
    if not os.path.isfile(args.input):
        die(f"input file not found: {args.input}")
    if args.size is not None and args.size <= 0:
        die("--size must be a positive number of MiB")
    if args.audio_kbps < 32 or args.audio_kbps > 320:
        die("--audio-kbps must be between 32 and 320")
    if args.encoder != "software" and args.encoder not in core.available_encoders():
        die(f"encoder '{args.encoder}' is not supported by this ffmpeg build "
            f"(available: {', '.join(core.available_encoders())})")

    output = args.output or core.default_output(args.input)
    try:
        core.ensure_safe_paths(args.input, output)
    except core.CompressError as e:
        die(str(e))
    if os.path.exists(output) and not args.yes:
        answer = input(f"'{output}' already exists. Overwrite? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            die("aborted")

    try:
        crf = args.crf if args.crf is not None else 23
        if args.size is not None:
            info = core.encode_to_size(args.input, output, args.size, args.preset, args.audio_kbps,
                                       encoder=args.encoder)
            label = f"target {args.size} MiB ({args.encoder})"
        else:
            info = core.encode_crf(args.input, output, crf, args.preset, args.audio_kbps,
                                   encoder=args.encoder)
            label = f"CRF {crf} ({args.encoder})"
    except core.CompressError as e:
        die(str(e))

    report = core.size_report(args.input, output)
    wh = f"{info['width']}x{info['height']}" if info["width"] and info["height"] else "?"
    print(f"Done ({label}): {core.fmt_mb(report['input_bytes'])} -> "
          f"{core.fmt_mb(report['output_bytes'])}  ({report['reduction']:.1f}% smaller)")
    print(f"Output: {os.path.abspath(output)}  |  {wh}  |  {info['duration']:.1f}s")


def cmd_web(args):
    try:
        from . import webui
    except ImportError as e:
        die(f"web UI unavailable: {e}\nInstall it with:  pip install 'video-compressor[web]'")
    webui.run(host=args.host, port=args.port)


def cmd_gui(args):
    from . import gui
    gui.main()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="video-compressor",
        description="Compress videos to a target file size (2-pass) or to a target quality (CRF).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    build_compress_parser(subparsers)
    web = subparsers.add_parser("web", help="start the local web UI")
    web.add_argument("-H", "--host", default="127.0.0.1", help="address to bind")
    web.add_argument("-p", "--port", type=int, default=8000, help="port to bind")
    web.set_defaults(func=cmd_web)

    gui = subparsers.add_parser("gui", help="launch the desktop GUI")
    gui.set_defaults(func=cmd_gui)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        die("interrupted")


if __name__ == "__main__":
    main()