"""Pre-signed Spaces upload flow for parcel-scoped data submission.

Flow:
  1. POST /api/parcels/<id>/uploads/request
       body: {filename, size_bytes}
     -> returns {upload_id, upload_url, key, method, headers, expires_in}

  2. Browser PUTs the ZIP bytes directly to ``upload_url`` (bypasses web
     container entirely; Spaces accepts the PUT, file lands at ``key``).

  3. POST /api/parcels/<id>/uploads/<upload_id>/confirm
       body: {key}
     -> verifies the file exists in Spaces via HEAD, validates size,
        creates the ProcessingJob row, returns {job_id, status}.

  4. Worker polls processing_jobs, claims the job, runs the pipeline.

  5. GET /api/parcels/<id>/uploads/<upload_id>/status
     -> poll endpoint. Returns {status, ...}.

Why this shape, per the Week 2 architectural note in SESSION_LOG:
  - The prior /api/properties/<pid>/uploads path streamed the ZIP through
    the web container, where storage.put_file() could hang an entire
    gunicorn worker for 5+ minutes on misconfig.
  - Pre-signed PUT eliminates that failure class: the web container
    never touches the bytes. Spaces is a separate failure domain that
    can't take the site down.
  - Browser gets progress events out of the box (XHR upload progress).

Both routes require access to the target parcel: either the uploader owns
the parcel (landowner self-submit) or is a LenderClient member authorized
to collect data on the parcel. V1: ``is_owner=TRUE`` covers demo + pilot
until per-landowner auth lands.
"""

import logging
import re
import secrets

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from db.models import (Camera, DetectionSummary, LenderClient, ProcessingJob,
                       Property, Season, Upload, db)
from strecker import storage

logger = logging.getLogger(__name__)

parcel_uploads_bp = Blueprint(
    "parcel_uploads_api", __name__, url_prefix="/api/parcels"
)

# Hunter-facing alias — identical handlers, property-scoped URLs.
# The Strecker site's "Upload Photos" button routes to
# /properties/<id>/upload which expects `/api/properties/<id>/uploads/...`
# as the upload endpoints. Rather than duplicating the three handlers we
# attach them to a second blueprint with the same view functions.
property_uploads_bp = Blueprint(
    "property_uploads_api", __name__, url_prefix="/api/properties"
)

# Real hunter SD cards routinely run 1-2 GB across a full season
# (~4,000-8,000 JPEGs @ 300-500 KB each). The prior 500 MB cap was
# a sanity floor that rejected a real-world first-upload test ZIP
# (TNDeer, 1.18 GB, 855 photos). 2 GB covers the realistic upper
# bound; larger cards should be split by the hunter or by year.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024   # 2 GB
MIN_UPLOAD_BYTES = 100                        # obvious-junk floor
PRESIGN_TTL_SECONDS = 1800                    # 30 min for big PUTs


def _user_can_upload(parcel: Property) -> bool:
    """v1 access check: owner tier OR the parcel's landowner user_id.

    v2 will add LenderClient staff + per-parcel upload tokens for
    passwordless landowner submission.
    """
    if getattr(current_user, "is_owner", False):
        return True
    if getattr(parcel, "user_id", None) == getattr(current_user, "id", None):
        return True
    return False


def _is_safe_filename(name: str) -> bool:
    if not name or len(name) > 200:
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    # Must end in .zip
    return name.lower().endswith(".zip")


@parcel_uploads_bp.route("/<int:parcel_id>/uploads/request", methods=["POST"])
@property_uploads_bp.route("/<int:parcel_id>/uploads/request", methods=["POST"])
@login_required
def request_upload(parcel_id):
    """Phase 1: issue a pre-signed PUT URL for a new upload.

    Expects JSON body: {filename: str, size_bytes: int}.
    """
    parcel = Property.query.get(parcel_id)
    if not parcel:
        return jsonify({"error": "Parcel not found"}), 404
    if not _user_can_upload(parcel):
        return jsonify({"error": "Not authorized"}), 403

    body = request.get_json(silent=True) or {}
    filename = (body.get("filename") or "").strip()
    size_bytes = int(body.get("size_bytes") or 0)

    if not _is_safe_filename(filename):
        return jsonify({"error": "filename must be a .zip, max 200 chars, no slashes"}), 400
    if size_bytes < MIN_UPLOAD_BYTES:
        return jsonify({"error": f"size_bytes too small (<{MIN_UPLOAD_BYTES})"}), 400
    if size_bytes > MAX_UPLOAD_BYTES:
        return jsonify({
            "error": f"File too large ({size_bytes // (1024*1024)} MB). "
                     f"Max {MAX_UPLOAD_BYTES // (1024*1024)} MB."
        }), 413

    # Synthesize an 8-hex-char token that becomes both the ProcessingJob
    # job_id (at /confirm time) AND the zip_key prefix. Lets the worker
    # find the ZIP from the job_id alone.
    token = secrets.token_hex(4)
    zip_key = storage.upload_zip_key(token)

    # Create the Upload row now so the browser has an id to poll on.
    # Status stays "pending_upload" until /confirm rolls it to "queued".
    upload = Upload(
        property_id=parcel.id,
        user_id=current_user.id,
        status="pending_upload",
        photo_count=None,
    )
    db.session.add(upload)
    db.session.commit()

    presign = storage.generate_presigned_put(
        key=zip_key,
        expires_in=PRESIGN_TTL_SECONDS,
        max_bytes=MAX_UPLOAD_BYTES,
        content_type="application/zip",
    )
    logger.info("Parcel %d: issued pre-signed PUT for upload %d (token=%s, %d bytes)",
                parcel.id, upload.id, token, size_bytes)
    return jsonify({
        "upload_id": upload.id,
        "job_id_reservation": token,
        **presign,
    }), 201


@parcel_uploads_bp.route(
    "/<int:parcel_id>/uploads/<int:upload_id>/confirm", methods=["POST"]
)
@property_uploads_bp.route(
    "/<int:parcel_id>/uploads/<int:upload_id>/confirm", methods=["POST"]
)
@login_required
def confirm_upload(parcel_id, upload_id):
    """Phase 3: verify the ZIP landed in Spaces + enqueue the worker job.

    Expects JSON body: {key: str, job_id_reservation: str}.
    """
    parcel = Property.query.get(parcel_id)
    if not parcel:
        return jsonify({"error": "Parcel not found"}), 404
    if not _user_can_upload(parcel):
        return jsonify({"error": "Not authorized"}), 403

    upload = Upload.query.get(upload_id)
    if not upload or upload.property_id != parcel.id:
        return jsonify({"error": "Upload not found"}), 404
    if upload.status != "pending_upload":
        return jsonify({"error": f"Upload already in state {upload.status!r}"}), 409

    body = request.get_json(silent=True) or {}
    zip_key = (body.get("key") or "").strip()
    token = (body.get("job_id_reservation") or "").strip()
    if not zip_key or not token:
        return jsonify({"error": "key and job_id_reservation are required"}), 400
    # Defense: the zip_key must match the reserved-token path we issued.
    expected_prefix = f"uploads/{token}/"
    if not zip_key.startswith(expected_prefix):
        return jsonify({"error": "key does not match reserved token"}), 400

    meta = storage.head(zip_key)
    if not meta:
        return jsonify({
            "error": "Upload not found in storage. Did the PUT complete?"
        }), 404
    size_bytes = meta.get("size_bytes") or 0
    if size_bytes > MAX_UPLOAD_BYTES:
        storage.delete_file(zip_key)
        return jsonify({"error": "Upload exceeds max size"}), 413
    if size_bytes < MIN_UPLOAD_BYTES:
        storage.delete_file(zip_key)
        return jsonify({"error": "Upload too small"}), 400

    # Reserve the token as the ProcessingJob job_id. Unique-constraint
    # protects against collision.
    pj = ProcessingJob(
        job_id=token,
        property_id=parcel.id,
        upload_id=upload.id,
        property_name=parcel.name,
        state=parcel.state or "TX",
        status="queued",
        zip_key=zip_key,
        demo=False,
    )
    upload.status = "queued"
    db.session.add(pj)
    db.session.commit()

    logger.info("Parcel %d upload %d confirmed: zip=%s size=%d -> job %s queued",
                parcel.id, upload.id, zip_key, size_bytes, token)
    return jsonify({
        "upload_id": upload.id,
        "job_id": pj.job_id,
        "status": "queued",
        "size_bytes": size_bytes,
    })


@parcel_uploads_bp.route(
    "/<int:parcel_id>/uploads/<int:upload_id>/status", methods=["GET"]
)
@property_uploads_bp.route(
    "/<int:parcel_id>/uploads/<int:upload_id>/status", methods=["GET"]
)
@login_required
def upload_status(parcel_id, upload_id):
    """Phase 5: poll endpoint used by the UI progress component."""
    parcel = Property.query.get(parcel_id)
    if not parcel:
        return jsonify({"error": "Parcel not found"}), 404
    if not _user_can_upload(parcel):
        return jsonify({"error": "Not authorized"}), 403

    upload = Upload.query.get(upload_id)
    if not upload or upload.property_id != parcel.id:
        return jsonify({"error": "Upload not found"}), 404

    pj = ProcessingJob.query.filter_by(upload_id=upload.id).first()
    status = (pj.status if pj else None) or upload.status
    return jsonify({
        "upload_id": upload.id,
        "job_id": pj.job_id if pj else None,
        "status": status,
        "error_message": (pj.error_message if pj else upload.error_message),
        "photo_count": upload.photo_count,
        "n_species": pj.n_species if pj else None,
        "n_events": pj.n_events if pj else None,
        "uploaded_at": upload.uploaded_at.isoformat() if upload.uploaded_at else None,
        "processed_at": upload.processed_at.isoformat() if upload.processed_at else None,
    })
