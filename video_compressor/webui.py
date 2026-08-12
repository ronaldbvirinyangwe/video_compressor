"""Local web UI built on Flask: drag & drop a video, pick a target, download."""

import os
import threading
import tempfile
import uuid

from flask import Flask, abort, jsonify, redirect, render_template, request, send_from_directory, url_for
from werkzeug.utils import secure_filename

from . import core

BASE_DIR = tempfile.mkdtemp(prefix="video_compressor_")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024**3  # 100 GiB local upload cap

JOBS = {}
_LOCK = threading.Lock()


def _update_job(job_id, **fields):
    with _LOCK:
        JOBS[job_id].update(fields)


def run_job(job_id, upload_path, keep_name, params):
    job = {"status": "processing", "progress": 0.0, "message": "Starting…",
           "output": None, "error": None, "filename": keep_name}
    with _LOCK:
        JOBS[job_id] = job

    output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")

    def on_progress(pct, msg):
        with _LOCK:
            job["progress"] = round(pct)
            job["message"] = msg

    try:
        info, _ = core.encode(upload_path, output_path, **params, on_progress=on_progress)
        report = core.size_report(upload_path, output_path)
        with _LOCK:
            job.update(status="done", progress=100.0,
                       message="Compression finished — grab your file below.",
                       output=output_path, info={
                           "width": info["width"], "height": info["height"],
                           "duration": round(info["duration"], 1),
                           "size_mb": round(report["output_mb"], 2),
                           "reduction": round(report["reduction"], 1),
                       })
    except core.CompressError as e:
        with _LOCK:
            job.update(status="error", message=str(e))
    finally:
        if os.path.exists(upload_path):
            os.remove(upload_path)


@app.route("/", methods=["GET"])
def index():
    encoders = {name: core.ENCODERS[name]["label"] for name in core.available_encoders()}
    return render_template("index.html", presets=core.PRESETS, encoders=encoders)


@app.route("/upload", methods=["POST"])
def upload():
    upload = request.files.get("video")
    if upload is None or upload.filename == "":
        abort(400, "no file uploaded")

    safe = secure_filename(upload.filename)
    if not os.path.splitext(safe)[1]:
        abort(400, "file must have an extension")

    keep_name = safe
    job_id = uuid.uuid4().hex[:12]
    upload_path = os.path.join(OUTPUT_DIR, f"{job_id}_in{safe}")
    upload.save(upload_path)

    kind = request.form.get("mode", "crf")
    params = {"preset": request.form.get("preset", "medium")}
    try:
        params["audio_kbps"] = int(request.form.get("audio_kbps", "128"))
    except ValueError:
        params["audio_kbps"] = 128
    params["encoder"] = request.form.get("encoder", "software")
    if params["encoder"] not in core.ENCODERS:
        params["encoder"] = "software"
    if kind == "size":
        try:
            params["size_mb"] = float(request.form.get("size_mb"))
        except (TypeError, ValueError):
            params["size_mb"] = None
        params["crf"] = None
    else:
        try:
            params["crf"] = min(int(request.form.get("crf", "23")), 51)
        except ValueError:
            params["crf"] = 23
        params["size_mb"] = None

    threading.Thread(target=run_job, args=(job_id, upload_path, keep_name, params), daemon=True).start()
    return redirect(url_for("job", job_id=job_id))


@app.route("/job/<job_id>")
def job(job_id):
    if job_id not in JOBS:
        abort(404, "no such job")
    return render_template("job.html", job_id=job_id)


@app.route("/status/<job_id>")
def status(job_id):
    if job_id not in JOBS:
        abort(404)
    with _LOCK:
        job = dict(JOBS[job_id])
    return jsonify(job)


@app.route("/download/<job_id>")
def download(job_id):
    if job_id not in JOBS:
        abort(404)
    with _LOCK:
        job = dict(JOBS[job_id])
    if job["status"] != "done" or not job["output"]:
        abort(409, "job not finished")
    return send_from_directory(OUTPUT_DIR, os.path.basename(job["output"]),
                               as_attachment=True, download_name=job.get("filename", "compressed.mp4"))


def run(host="127.0.0.1", port=8000):
    print(f"Video Compressor web UI running at http://{host}:{port}")
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    run()