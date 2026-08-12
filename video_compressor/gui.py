"""Desktop GUI built on Tkinter (stdlib only, no third-party dependencies)."""

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import core

PRESET_LABELS = {p.capitalize(): p for p in core.PRESETS}
AUDIO_CHOICES = ["96", "128", "160", "192", "256", "320"]


class App:
    def __init__(self, root):
        self.root = root
        root.title("Video Compressor")
        root.resizable(False, False)

        self.mode = tk.StringVar(value="size")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.size_mb = tk.IntVar(value=64)
        self.crf = tk.IntVar(value=23)
        self.preset = tk.StringVar(value="Medium")
        self.audio_kbps = tk.StringVar(value="128")
        self.encoder = tk.StringVar()
        self.status = tk.StringVar(value="Pick a video to get started.")

        self._encoders = core.available_encoders()
        self._enc_keys = {core.ENCODERS[k]["label"]: k for k in self._encoders}
        self.encoder.set(list(self._enc_keys)[0] if self._enc_keys else "Software (libx264)")
        self._running = False
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 24, "pady": 8}
        frame = ttk.Frame(self.root, padding=24)
        frame.grid()

        ttk.Label(frame, text="Video Compressor", font=("Helvetica", 18, "bold")).grid(row=0, column=0, columnspan=3, sticky="w")

        # Input / output
        ttk.Label(frame, text="Source").grid(row=1, column=0, sticky="w", pady=(16, 2))
        ttk.Entry(frame, textvariable=self.input_path).grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Button(frame, text="Browse…", command=self.browse).grid(row=2, column=2, padx=(8, 0))

        ttk.Label(frame, text="Output").grid(row=3, column=0, sticky="w", pady=(12, 2))
        ttk.Entry(frame, textvariable=self.output_path).grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(frame, text="Browse…", command=self.browse_output).grid(row=4, column=2, padx=(8, 0))

        # Mode
        mode_frame = ttk.LabelFrame(frame, text="Mode", padding=12)
        mode_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        ttk.Radiobutton(mode_frame, text="Target file size", value="size", variable=self.mode).grid(row=0, column=0, sticky="w")
        ttk.Spinbox(mode_frame, from_=1, to=5000, textvariable=self.size_mb, width=8).grid(row=0, column=1, padx=(8, 4))
        ttk.Label(mode_frame, text="MiB").grid(row=0, column=2, sticky="w")

        ttk.Radiobutton(mode_frame, text="Target quality (CRF)", value="crf", variable=self.mode).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Scale(mode_frame, from_=14, to=32, variable=self.crf, orient="horizontal").grid(row=1, column=1, columnspan=2, sticky="ew", padx=(8, 4))
        ttk.Label(mode_frame, textvariable=self.crf).grid(row=1, column=3, padx=(4, 0))
        mode_frame.columnconfigure(1, weight=1)

        # Encoding options
        opts = ttk.LabelFrame(frame, text="Encoding", padding=12)
        opts.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Label(opts, text="Preset").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.preset, values=list(PRESET_LABELS), state="readonly", width=12).grid(row=1, column=0, sticky="w")
        ttk.Label(opts, text="Audio").grid(row=0, column=1, sticky="w", padx=(24, 0))
        ttk.Combobox(opts, textvariable=self.audio_kbps, values=AUDIO_CHOICES, state="readonly", width=8).grid(row=1, column=1, sticky="w", padx=(24, 0))
        ttk.Label(opts, text="Encoder").grid(row=0, column=2, sticky="w", padx=(24, 0))
        ttk.Combobox(opts, textvariable=self.encoder, values=list(self._enc_keys),
                     state="readonly", width=22).grid(row=1, column=2, sticky="w", padx=(24, 0))

        # Progress
        self.bar = ttk.Progressbar(frame, maximum=100, mode="determinate", length=430)
        self.bar.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(24, 6))
        ttk.Label(frame, textvariable=self.status).grid(row=8, column=0, columnspan=3, sticky="w")

        self.compress_btn = ttk.Button(frame, text="Compress", command=self.compress, style="Accent.TButton")
        self.compress_btn.grid(row=9, column=0, columnspan=3, pady=(16, 0), sticky="ew")

        self.input_path.trace_add("write", self._update_output_hint)

    def browse(self):
        path = filedialog.askopenfilename(title="Choose a video", filetypes=[
            ("Videos", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.flv *.ts"),
            ("All files", "*.*"),
        ])
        if path:
            self.input_path.set(path)
            if not self.output_path.get():
                self.output_path.set(core.default_output(path))

    def _update_output_hint(self, *args):
        if self.output_path.get() == core.default_output(self.input_path.get()):
            self.output_path.set(core.default_output(self.input_path.get()))

    def browse_output(self):
        path = filedialog.asksaveasfilename(title="Save compressed video as",
                                            defaultextension=".mp4",
                                            initialfile=os.path.basename(self.output_path.get() or "output.mp4"))
        if path:
            self.output_path.set(path)

    def compress(self):
        if self._running:
            return
        src = self.input_path.get()
        dst = self.output_path.get()
        error = None
        if not src or not os.path.isfile(src):
            error = "Choose an existing source video first."
        elif not dst:
            error = "Choose an output path first."
        else:
            try:
                core.ensure_safe_paths(src, dst)
            except core.CompressError as e:
                error = str(e)
        if error:
            messagebox.showerror("Video Compressor", error)
            return
        if os.path.exists(dst) and not messagebox.askyesno("Video Compressor", f"Overwrite {os.path.basename(dst)}?"):
            return

        params = dict(
            input_path=src,
            output_path=dst,
            size_mb=None if self.mode.get() == "crf" else float(self.size_mb.get()),
            crf=None if self.mode.get() == "size" else int(self.crf.get()),
            preset=PRESET_LABELS[self.preset.get()],
            audio_kbps=int(self.audio_kbps.get()),
            encoder=self._enc_keys.get(self.encoder.get(), "software"),
        )
        self._params = params
        self._running = True
        self.compress_btn.state(["disabled"])
        self.status.set("Starting…")
        self.bar["value"] = 0
        threading.Thread(target=self._worker, args=(params,), daemon=True).start()

    def _worker(self, params):
        def on_progress(pct, msg):
            self.root.after(0, self._progress, pct, msg)
        try:
            info, _ = core.encode(
                params["input_path"], params["output_path"],
                size_mb=params["size_mb"], crf=params["crf"],
                preset=params["preset"], audio_kbps=params["audio_kbps"],
                on_progress=on_progress,
            )
            report = core.size_report(params["input_path"], params["output_path"])
            self.root.after(0, self._done, info, report)
        except core.CompressError as e:
            self.root.after(0, self._fail, str(e))
        except Exception as e:  # noqa: BLE001 - surface unexpected errors in the UI
            self.root.after(0, self._fail, f"Unexpected error: {e}")

    def _progress(self, pct, msg):
        self.bar["value"] = pct
        self.status.set(msg)

    def _done(self, info, report):
        self._running = False
        self.compress_btn.state(["!disabled"])
        self.bar["value"] = 100
        wh = f"{info['width']}x{info['height']}" if info["width"] and info["height"] else "?"
        self.status.set("Done.")
        messagebox.showinfo(
            "Video Compressor",
            f"{core.fmt_mb(report['input_bytes'])} -> {core.fmt_mb(report['output_bytes'])} "
            f"({report['reduction']:.1f}% smaller)\n"
            f"{wh}  ·  {info['duration']:.1f}s\n\nSaved to:\n{self._params['output_path']}",
        )

    def _fail(self, message):
        self._running = False
        self.compress_btn.state(["!disabled"])
        self.status.set("Failed.")
        messagebox.showerror("Video Compressor", message)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Accent.TButton", font=("Helvetica", 11, "bold"))
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()