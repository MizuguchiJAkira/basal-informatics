"""Results routes — display classification and sorting results.

GET /results/<job_id>                 — Show summary + downloads
GET /download/<job_id>/<file_type>    — Stream generated files (proxy from Spaces)
"""

import logging
import os
import tempfile

from flask import Blueprint, abort, redirect, render_template, send_file

from strecker import storage

results_bp = Blueprint("results", __name__)
logger = logging.getLogger(__name__)


@results_bp.route("/results/<job_id>")
def results(job_id):
    """Results page for a processing job (any status)."""
    from web.routes.upload import _get_job
    job = _get_job(job_id)
    species = job.get("species", []) if job else []
    return render_template("results.html", job=job, species=species)


def _serve_key(key: str, download_name: str):
    """Stream an object-storage key as a download.

    For Spaces, we could redirect to a presigned URL, but proxying keeps the
    URL inside our domain (nicer UX, avoids credential leakage via referrer).
    """
    try:
        # Download to a temp file then stream. boto3 doesn't have a clean
        # "stream to response" for presigned-less local-fallback parity.
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix="_" + download_name)
        tmp.close()
        storage.get_file(key, tmp.name)

        # Flask's send_file handles the Content-Disposition header.
        resp = send_file(tmp.name, as_attachment=True, download_name=download_name)

        # Clean up tempfile after response is sent.
        @resp.call_on_close
        def _cleanup():
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        return resp
    except FileNotFoundError:
        abort(404)
    except Exception:
        logger.exception("Failed to serve storage key %s", key)
        abort(500)


@results_bp.route("/download/<job_id>/<file_type>")
def download(job_id, file_type):
    """Serve generated files (report PDF, appendix CSV)."""
    from web.routes.upload import _get_job
    job = _get_job(job_id)
    if not job:
        abort(404)

    if file_type == "report":
        key = job.get("report_key")
        if key:
            return _serve_key(key, "game_inventory_report.pdf")
        # Legacy jobs may still have a local path
        path = job.get("report_path")
        if path and os.path.exists(path):
            return send_file(path, as_attachment=True,
                             download_name="game_inventory_report.pdf")
    elif file_type == "appendix":
        key = job.get("appendix_key")
        if key:
            return _serve_key(key, "events_appendix.csv")
        path = job.get("appendix_path")
        if path and os.path.exists(path):
            return send_file(path, as_attachment=True,
                             download_name="events_appendix.csv")

    abort(404)
