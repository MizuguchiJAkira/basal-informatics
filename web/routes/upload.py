"""Upload routes — hunter photo upload interface.

GET  /upload   — Upload form
POST /upload   — Accept ZIP, enqueue for worker, redirect to results
GET  /upload/status/<job_id> — Poll endpoint for async job status

Architecture:
  - Web container accepts the ZIP, validates it, pushes to Spaces, then
    writes a ProcessingJob row with status='queued' and zip_key set.
  - A separate worker Droplet polls `processing_jobs WHERE status='queued'`,
    claims a row, downloads the ZIP, runs the pipeline, uploads artifacts,
    marks status='complete'.
  - Demo mode (no real photos) still runs inline in the web container since
    there's no ZIP to ship — it uses bundled demo fixtures.
"""

import json
import logging
import os
import tempfile
import threading
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, current_app, jsonify, redirect, render_template, request,
    url_for,
)

from config import settings
from strecker import storage

upload_bp = Blueprint("upload", __name__)
logger = logging.getLogger(__name__)

# Thread-safe in-memory cache (authoritative state lives in DB)
_jobs_lock = threading.Lock()
_jobs = {}

# Max upload size: 500 MB
MAX_UPLOAD_BYTES = 500 * 1024 * 1024


def _get_job(job_id: str) -> dict:
    """Get job from memory cache, falling back to DB."""
    with _jobs_lock:
        if job_id in _jobs:
            return _jobs[job_id].copy()

    try:
        from db.models import ProcessingJob
        pj = ProcessingJob.query.filter_by(job_id=job_id).first()
        if pj:
            return pj.to_dict()
    except Exception:
        logger.exception("Failed to load job %s from DB", job_id)
    return None


def _set_job(job_id: str, data: dict):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(data)
        else:
            _jobs[job_id] = data


def _persist_job(job_id: str, app):
    """Persist current in-memory job state to the database."""
    try:
        with app.app_context():
            from db.models import db, ProcessingJob
            pj = ProcessingJob.query.filter_by(job_id=job_id).first()
            if not pj:
                pj = ProcessingJob(job_id=job_id)
                db.session.add(pj)

            with _jobs_lock:
                data = _jobs.get(job_id, {})

            # Scalar fields
            for col in ("property_name", "state", "status", "error_message",
                        "n_photos", "n_species", "n_events",
                        "report_path", "appendix_path",
                        "zip_key", "report_key", "appendix_key",
                        "demo"):
                if col in data:
                    setattr(pj, col, data[col])

            if "completed_at" in data and data["completed_at"]:
                pj.completed_at = datetime.fromisoformat(data["completed_at"])

            if "species" in data and data["species"]:
                pj.species_json = json.dumps(data["species"])

            db.session.commit()
    except Exception:
        logger.exception("Failed to persist job %s to DB", job_id)


def _run_demo_pipeline(job_id: str, property_name: str, app):
    """Run the demo pipeline inline (no real ZIP, bundled fixtures)."""
    try:
        from strecker.ingest import ingest
        from strecker.classify import classify
        from strecker.report import generate_report
        from config.species_reference import SPECIES_REFERENCE

        _set_job(job_id, {"status": "processing"})
        photos = ingest(demo=True)

        _set_job(job_id, {"status": "classifying"})
        detections = classify(photos, demo=True)

        _set_job(job_id, {"status": "reporting"})
        output_dir = Path(tempfile.mkdtemp(prefix=f"demo_{job_id}_"))
        report_path = str(output_dir / "game_inventory_report.pdf")
        generate_report(
            detections, output_path=report_path,
            property_name=property_name, demo=True,
        )

        # Upload artifacts to Spaces so /download works the same way as real jobs
        r_key = storage.report_key(job_id)
        storage.put_file(report_path, r_key, content_type="application/pdf")

        species_stats = defaultdict(lambda: {
            "events": set(), "photos": 0, "cameras": set()
        })
        for det in detections:
            sp = species_stats[det.species_key]
            sp["events"].add(det.independent_event_id)
            sp["photos"] += 1
            sp["cameras"].add(det.camera_id)

        species_list = []
        for sp_key, stats in sorted(species_stats.items(),
                                    key=lambda x: -len(x[1]["events"])):
            ref = SPECIES_REFERENCE.get(sp_key, {})
            species_list.append({
                "common_name": ref.get("common_name",
                                       sp_key.replace("_", " ").title()),
                "events": len(stats["events"]),
                "photos": stats["photos"],
                "cameras": len(stats["cameras"]),
            })
        n_events = sum(s["events"] for s in species_list)

        _set_job(job_id, {
            "status": "complete",
            "n_photos": f"{len(detections):,}",
            "n_species": len(species_list),
            "n_events": f"{n_events:,}",
            "report_key": r_key,
            "species": species_list,
            "completed_at": datetime.utcnow().isoformat(),
        })
        _persist_job(job_id, app)

    except Exception as e:
        logger.exception("Demo pipeline failed for job %s", job_id)
        _set_job(job_id, {"status": "error", "error_message": str(e)})
        _persist_job(job_id, app)


@upload_bp.route("/upload", methods=["GET", "POST"])
def upload():
    """GET: show upload form. POST: accept ZIP and enqueue."""
    if request.method == "GET":
        return render_template("upload.html")

    job_id = str(uuid.uuid4())[:8]
    property_name = request.form.get("property_name", "My Property")
    state = request.form.get("state", "TX")
    demo_mode = current_app.config.get("DEMO_MODE", False)
    app = current_app._get_current_object()

    _set_job(job_id, {
        "job_id": job_id,
        "status": "queued",
        "property_name": property_name,
        "state": state,
        "demo": demo_mode,
        "submitted_at": datetime.utcnow().isoformat(),
    })

    # ── Demo path: no ZIP, run inline with bundled fixtures ──
    if demo_mode:
        _persist_job(job_id, app)
        thread = threading.Thread(
            target=_run_demo_pipeline,
            args=(job_id, property_name, app),
            daemon=True,
        )
        thread.start()
        return redirect(url_for("results.results", job_id=job_id))

    # ── Production path: upload ZIP to object storage, let worker handle it ──
    uploaded_file = request.files.get("photos")
    if not uploaded_file or uploaded_file.filename == "":
        _set_job(job_id, {"status": "error", "error_message": "No file uploaded"})
        _persist_job(job_id, app)
        return redirect(url_for("results.results", job_id=job_id))

    if not uploaded_file.filename.lower().endswith(".zip"):
        _set_job(job_id, {"status": "error",
                          "error_message": "Please upload a ZIP file"})
        _persist_job(job_id, app)
        return redirect(url_for("results.results", job_id=job_id))

    # Stream to /tmp so we don't rely on the container filesystem
    tmpdir = tempfile.mkdtemp(prefix=f"upload_{job_id}_")
    local_zip = os.path.join(tmpdir, "upload.zip")
    try:
        uploaded_file.save(local_zip)

        file_size = os.path.getsize(local_zip)
        if file_size > MAX_UPLOAD_BYTES:
            _set_job(job_id, {
                "status": "error",
                "error_message": (
                    f"File too large ({file_size // (1024*1024)} MB). "
                    f"Maximum is {MAX_UPLOAD_BYTES // (1024*1024)} MB."
                ),
            })
            _persist_job(job_id, app)
            return redirect(url_for("results.results", job_id=job_id))

        # Validate ZIP integrity + has images
        try:
            with zipfile.ZipFile(local_zip, "r") as zf:
                bad = zf.testzip()
                if bad is not None:
                    raise zipfile.BadZipFile(f"Corrupt file in ZIP: {bad}")
                image_exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
                has_images = any(
                    Path(n).suffix.lower() in image_exts
                    for n in zf.namelist()
                    if not n.startswith("__MACOSX") and not n.endswith("/")
                )
                if not has_images:
                    _set_job(job_id, {
                        "status": "error",
                        "error_message": "ZIP contains no image files.",
                    })
                    _persist_job(job_id, app)
                    return redirect(url_for("results.results", job_id=job_id))
        except zipfile.BadZipFile as e:
            _set_job(job_id, {"status": "error",
                              "error_message": f"Invalid ZIP: {e}"})
            _persist_job(job_id, app)
            return redirect(url_for("results.results", job_id=job_id))

        # Push to object storage
        zip_key = storage.upload_zip_key(job_id)
        storage.put_file(local_zip, zip_key, content_type="application/zip")

        _set_job(job_id, {
            "status": "queued",
            "zip_key": zip_key,
        })
        _persist_job(job_id, app)
        logger.info("Job %s queued: %d KB -> %s (property '%s')",
                    job_id, file_size // 1024, zip_key, property_name)

    finally:
        # Local temp copy no longer needed; authoritative copy is in Spaces.
        try:
            if os.path.exists(local_zip):
                os.unlink(local_zip)
            os.rmdir(tmpdir)
        except Exception:
            pass

    return redirect(url_for("results.results", job_id=job_id))


@upload_bp.route("/upload/status/<job_id>")
def job_status(job_id):
    """Poll endpoint for async job status."""
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify({
        "job_id": job.get("job_id", job_id),
        "status": job["status"],
        "error_message": job.get("error_message"),
    })
