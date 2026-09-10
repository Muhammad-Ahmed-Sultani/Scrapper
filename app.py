"""
Flask web server for the business-directory scraper.

Flow: the page posts keyword + location + chosen directories to /start,
which kicks the pipeline off in a background thread and returns a job id.
The page polls /progress/<job_id> once a second; the server answers with
a structured snapshot (overall phase + one status row per directory).
When the run finishes the snapshot carries the Excel filename, served by
/download/<file>.
"""
import threading
import uuid

from flask import Flask, jsonify, render_template, request, send_from_directory

from config import OUTPUT_DIR
from core.models import RunState
from core.pipeline import run_scrape
from scrapers import SCRAPER_CLASSES

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

OUTPUT_DIR.mkdir(exist_ok=True)

JOBS = {}  # job_id -> RunState
JOBS_LOCK = threading.Lock()


def run_job(job_id, keyword, location, directories, find_emails):
    state = JOBS[job_id]
    try:
        run_scrape(keyword, location, directories, state, find_emails=find_emails)
    except Exception as e:
        # surface crashes as a friendly message instead of a silent hang
        with state._lock:
            state.done = True
            state.error = str(e)
            state.message = f"Something went wrong: {e}"


@app.route("/")
def index():
    directories = [
        {"key": cls.key, "label": cls.label, "tos_note": cls.tos_note,
         "default_on": cls.enabled_by_default}
        for cls in SCRAPER_CLASSES
    ]
    return render_template("index.html", directories=directories)


@app.route("/start", methods=["POST"])
def start():
    keyword = (request.form.get("keyword") or "").strip()
    location = (request.form.get("location") or "").strip()
    directories = request.form.getlist("directories")
    # Opt-in: visiting every business website is by far the slowest stage,
    # and no row is dropped for lacking an email either way.
    find_emails = (request.form.get("find_emails") or "").lower() in ("1", "true", "on", "yes")

    if not keyword:
        return jsonify({"error": "Please enter a keyword (category or service)."}), 400
    if not location:
        return jsonify({"error": "Please enter a location."}), 400
    valid_keys = {cls.key for cls in SCRAPER_CLASSES}
    directories = [d for d in directories if d in valid_keys]
    if not directories:
        return jsonify({"error": "Please tick at least one directory."}), 400

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = RunState(keyword=keyword, location=location)

    threading.Thread(
        target=run_job,
        args=(job_id, keyword, location, directories, find_emails),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress(job_id):
    with JOBS_LOCK:
        state = JOBS.get(job_id)
    if state is None:
        return jsonify({"error": "Unknown job."}), 404
    return jsonify(state.snapshot())


@app.route("/download/<path:filename>")
def download(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    print("Starting server. Open http://localhost:5000 in your browser.")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
