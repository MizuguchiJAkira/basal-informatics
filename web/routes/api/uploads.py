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
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024   # 2 GB (matches pre-signed flow)
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
    """DEPRECATED — replaced by the pre-signed PUT flow.

    The old streaming POST held the HTTP request open while boto3 wrote
    the ZIP through the web container. That had hung gunicorn workers
    for minutes on a misconfigured Space, so it was replaced with the
    three-step flow:

      POST /api/properties/<pid>/uploads/request         -> presigned PUT URL
      PUT  <spaces-url>                                   -> bytes go direct
      POST /api/properties/<pid>/uploads/<uid>/confirm   -> enqueue job

    All three handlers live in web/routes/api/parcel_uploads.py and are
    exposed under both /api/parcels and /api/properties.

    This route now returns 410 Gone with a pointer to the new flow so
    any stale UI hitting the old endpoint fails loudly instead of
    hanging.
    """
    return jsonify({
        "error": "This endpoint is deprecated; use /api/properties/"
                 "<pid>/uploads/request + /confirm. See "
                 "docs/UPLOAD_FLOW.md.",
        "replacement": {
            "request": f"/api/properties/{property_id}/uploads/request",
            "confirm": (f"/api/properties/{property_id}/uploads/"
                        "<upload_id>/confirm"),
            "status":  (f"/api/properties/{property_id}/uploads/"
                        "<upload_id>/status"),
        },
    }), 410


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
