"""API routes for property-scoped photo uploads.

POST   /api/properties/<pid>/uploads  — accept ZIP, stream to Spaces,
                                         enqueue worker job
GET    /api/uploads/<id>/status       — poll ProcessingJob status
DELETE /api/uploads/<id>              — remove an Upload row with no
                                         ProcessingJob attached (cleanup)

The ZIP is processed by strecker.worker on the Droplet; the web container
never loads PyTorch / SpeciesNet. When the worker finishes, it auto-creates
Cameras from top-level ZIP folder names, derives a quarterly Season from
photo timestamps, and aggregates DetectionSummary rows.
"""

import logging
import os
import secrets
import tempfile
import zipfile

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from db.models import Property, ProcessingJob, Upload, db
from strecker import storage

logger = logging.getLogger(__name__)

uploads_api_bp = Blueprint("uploads_api", __name__, url_prefix="/api")

# Same cap as the Strecker /upload flow
MAX_UPLOAD_BYTES = 500 * 1024 * 1024
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp")


def _get_user_property(property_id):
    prop = Property.query.get(property_id)
    if prop and prop.user_id == current_user.id:
        return prop
    return None


def _new_job_id() -> str:
    # 8 hex chars, matches ProcessingJob.job_id column width
    return secrets.token_hex(4)


@uploads_api_bp.route("/properties/<int:property_id>/uploads", methods=["POST"])
@login_required
def create_upload(property_id):
    """Accept a ZIP, push to Spaces, create Upload + ProcessingJob rows.

    The worker (strecker.worker) picks it up by polling processing_jobs.
    """
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    uploaded_file = request.files.get("file") or request.files.get("photos")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"error": "No file uploaded"}), 400
    if not uploaded_file.filename.lower().endswith(".zip"):
        return jsonify({"error": "Please upload a ZIP file"}), 400

    # Stream to /tmp so we never rely on the container's writable volume.
    tmpdir = tempfile.mkdtemp(prefix=f"prop_upload_{prop.id}_")
    local_zip = os.path.join(tmpdir, "upload.zip")
    try:
        uploaded_file.save(local_zip)

        file_size = os.path.getsize(local_zip)
        if file_size > MAX_UPLOAD_BYTES:
            return jsonify({
                "error": f"File too large ({file_size // (1024*1024)} MB). "
                         f"Max {MAX_UPLOAD_BYTES // (1024*1024)} MB."
            }), 413

        # Validate ZIP + confirm it contains at least one image.
        try:
            with zipfile.ZipFile(local_zip) as zf:
                if zf.testzip() is not None:
                    return jsonify({"error": "ZIP file is corrupt"}), 400
                has_image = any(
                    n.lower().endswith(_IMG_EXTS) for n in zf.namelist()
                )
                if not has_image:
                    return jsonify({"error": "ZIP contains no images"}), 400
        except zipfile.BadZipFile as e:
            return jsonify({"error": f"Invalid ZIP: {e}"}), 400

        # Create Upload row first so we have its id for the job.
        upload = Upload(
            property_id=prop.id,
            user_id=current_user.id,
            status="queued",
            photo_count=None,
        )
        db.session.add(upload)
        db.session.commit()

        # Push to object storage under a unique job key.
        job_id = _new_job_id()
        zip_key = storage.upload_zip_key(job_id)
        storage.put_file(local_zip, zip_key, content_type="application/zip")

        pj = ProcessingJob(
            job_id=job_id,
            property_id=prop.id,
            upload_id=upload.id,
            property_name=prop.name,
            state=prop.state or "TX",
            status="queued",
            zip_key=zip_key,
            demo=False,
        )
        db.session.add(pj)
        db.session.commit()

        logger.info(
            "Property %d upload %d queued: %d KB -> %s (job %s)",
            prop.id, upload.id, file_size // 1024, zip_key, job_id,
        )

        return jsonify({
            "id": upload.id,
            "job_id": job_id,
            "status": "queued",
            "property_id": prop.id,
        }), 201

    finally:
        try:
            if os.path.exists(local_zip):
                os.unlink(local_zip)
            os.rmdir(tmpdir)
        except Exception:
            pass


@uploads_api_bp.route("/uploads/<int:upload_id>/status", methods=["GET"])
@login_required
def get_upload_status(upload_id):
    """Poll the ProcessingJob linked to this Upload."""
    upload = Upload.query.get(upload_id)
    if not upload:
        return jsonify({"error": "Upload not found"}), 404

    prop = Property.query.get(upload.property_id)
    if not prop or prop.user_id != current_user.id:
        return jsonify({"error": "Upload not found"}), 404

    pj = ProcessingJob.query.filter_by(upload_id=upload.id).first()

    # Prefer the ProcessingJob status (source of truth once the worker has it);
    # fall back to the Upload row for the brief window before commit.
    status = (pj.status if pj else None) or upload.status
    error_message = (pj.error_message if pj else None) or upload.error_message

    return jsonify({
        "id": upload.id,
        "job_id": pj.job_id if pj else None,
        "status": status,
        "photo_count": upload.photo_count,
        "error_message": error_message,
        "uploaded_at": upload.uploaded_at.isoformat() if upload.uploaded_at else None,
        "processed_at": upload.processed_at.isoformat() if upload.processed_at else None,
        "n_species": pj.n_species if pj else None,
        "n_events": pj.n_events if pj else None,
    })


@uploads_api_bp.route("/uploads/<int:upload_id>", methods=["DELETE"])
@login_required
def delete_upload(upload_id):
    """Delete an Upload row that has no ProcessingJob attached.

    Intended for cleaning up orphan rows created by fileless POSTs against
    the pre-37a03f5 route (which inserted status="pending" before validating
    the request). Refuses if a ProcessingJob exists for the upload — those
    represent real work and should not be removed through this endpoint.
    """
    upload = Upload.query.get(upload_id)
    if not upload:
        return jsonify({"error": "Upload not found"}), 404

    prop = Property.query.get(upload.property_id)
    if not prop or prop.user_id != current_user.id:
        return jsonify({"error": "Upload not found"}), 404

    pj = ProcessingJob.query.filter_by(upload_id=upload.id).first()
    if pj is not None:
        return jsonify({
            "error": "Upload has an attached ProcessingJob; refusing to delete",
            "job_id": pj.job_id,
            "job_status": pj.status,
        }), 409

    db.session.delete(upload)
    db.session.commit()
    return jsonify({"message": "Upload deleted", "id": upload_id}), 200
