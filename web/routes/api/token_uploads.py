"""Tokenized upload flow — passwordless landowner submission.

Mirrors the ``/api/properties/<pid>/uploads/...`` flow but authenticates
by bearer token in the URL path instead of by login session. Let a
parcel's owner (or Basal ops) generate a token, email the share link to
the landowner, and let the landowner upload an SD-card ZIP without
creating an account.

Routes (site-agnostic, registered on both):

  POST /u/<token>/uploads/request
       body: {filename, size_bytes}
       → {upload_id, job_id_reservation, upload_url, key, ...}

  POST /u/<token>/uploads/<upload_id>/confirm
       body: {key, job_id_reservation}
       → {upload_id, job_id, status, size_bytes}

  GET  /u/<token>/uploads/<upload_id>/status
       → {upload_id, job_id, status, ...}

  GET  /u/<token>
       → {parcel_name, county, state, uses_remaining, expires_at}
       (lightweight preview so the landing page the landowner lands on
        can show the parcel they're submitting against)

Owner-scoped token issuance lives separately under
``/api/properties/<pid>/upload-tokens`` and requires login.
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from db.models import (
    ProcessingJob, Property, Upload, UploadToken, db,
)
from strecker import storage

logger = logging.getLogger(__name__)

token_uploads_bp = Blueprint(
    "token_uploads_api", __name__, url_prefix="/u"
)
# Owner-side issuance — sits under /api/properties so it shares the
# property namespace the rest of the owner UI uses.
upload_tokens_bp = Blueprint(
    "upload_tokens_api", __name__, url_prefix="/api"
)


# Match the authenticated-flow cap. A full-season hunter SD card
# routinely exceeds 500 MB; 2 GB is the realistic upper bound.
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MIN_UPLOAD_BYTES = 100
PRESIGN_TTL_SECONDS = 1800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_token(token_str: str, *, for_new_upload: bool = True) -> UploadToken:
    """Return the UploadToken row if usable for the caller's action.

    for_new_upload=True  (default) — caller is starting a new upload;
                          token must pass is_valid() (revoked, expired,
                          or exhausted all reject).

    for_new_upload=False — caller is confirming or polling an in-flight
                          upload; token must pass is_readable()
                          (revoked or expired reject; exhausted OK).
                          Single-use tokens exhaust on confirm but the
                          landowner still needs to poll /status.
    """
    t = UploadToken.query.filter_by(token=token_str).first()
    if not t:
        return None
    if for_new_upload:
        return t if t.is_valid() else None
    return t if t.is_readable() else None


def _is_safe_filename(name: str) -> bool:
    if not name or len(name) > 200:
        return False
    if ".." in name or "/" in name or "\\" in name:
        return False
    return name.lower().endswith(".zip")


def _share_url(token: str) -> str:
    """Absolute share URL for a landowner to open."""
    try:
        return url_for(
            "token_uploads_api.token_info", token=token, _external=True
        )
    except Exception:
        return f"/u/{token}"


# ---------------------------------------------------------------------------
# Token-auth flow (no login_required)
# ---------------------------------------------------------------------------

@token_uploads_bp.route("/<string:token>", methods=["GET"])
def token_info(token):
    """Preview the parcel + token health so the landing page can show
    "you are about to upload photos for <Parcel Name>" before the user
    picks a file.
    """
    t = _load_token(token)
    if not t:
        return jsonify({"error": "This upload link is invalid, revoked, "
                                   "or expired."}), 404
    p = Property.query.get(t.property_id)
    if not p:
        return jsonify({"error": "Parcel not found for this token."}), 404
    return jsonify({
        "parcel_name": p.name,
        "county": p.county, "state": p.state,
        "acreage": float(p.acreage) if p.acreage is not None else None,
        "uses_remaining": t.uses_remaining,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "label": t.label,
    })


@token_uploads_bp.route("/<string:token>/uploads/request", methods=["POST"])
def request_upload(token):
    t = _load_token(token)
    if not t:
        return jsonify({"error": "Invalid or expired upload token."}), 404
    parcel = Property.query.get(t.property_id)
    if not parcel:
        return jsonify({"error": "Parcel not found."}), 404

    body = request.get_json(silent=True) or {}
    filename = (body.get("filename") or "").strip()
    size_bytes = int(body.get("size_bytes") or 0)

    if not _is_safe_filename(filename):
        return jsonify({"error": "filename must be a .zip, max 200 chars, "
                                   "no slashes"}), 400
    if size_bytes < MIN_UPLOAD_BYTES:
        return jsonify({"error": "size_bytes too small"}), 400
    if size_bytes > MAX_UPLOAD_BYTES:
        return jsonify({
            "error": f"File too large ({size_bytes // (1024*1024)} MB). "
                     f"Max {MAX_UPLOAD_BYTES // (1024*1024)} MB."
        }), 413

    job_token = secrets.token_hex(4)
    zip_key = storage.upload_zip_key(job_token)

    # Upload row. The uploader has no account; attribute the row to
    # the token's creator if we have one, otherwise to the parcel's
    # owner. uploads.user_id is NOT NULL at the schema level, so we
    # always need a fallback.
    attrib_user_id = t.created_by_user_id or parcel.user_id
    upload = Upload(
        property_id=parcel.id,
        user_id=attrib_user_id,
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
    logger.info(
        "Token %s: issued pre-signed PUT for parcel %d, upload %d (job token %s)",
        token[:8], parcel.id, upload.id, job_token,
    )
    return jsonify({
        "upload_id": upload.id,
        "job_id_reservation": job_token,
        **presign,
    }), 201


@token_uploads_bp.route(
    "/<string:token>/uploads/<int:upload_id>/confirm", methods=["POST"]
)
def confirm_upload(token, upload_id):
    # Confirm uses is_valid() — a single-use token must still have one
    # use left at confirm time. Only the /status endpoint is permissive.
    t = _load_token(token, for_new_upload=True)
    if not t:
        return jsonify({"error": "Invalid or expired upload token."}), 404
    upload = Upload.query.get(upload_id)
    if not upload or upload.property_id != t.property_id:
        return jsonify({"error": "Upload not found."}), 404
    if upload.status != "pending_upload":
        return jsonify({
            "error": f"Upload already in state {upload.status!r}"
        }), 409

    body = request.get_json(silent=True) or {}
    zip_key = (body.get("key") or "").strip()
    job_token = (body.get("job_id_reservation") or "").strip()
    if not zip_key or not job_token:
        return jsonify({
            "error": "key and job_id_reservation are required"
        }), 400
    expected_prefix = f"uploads/{job_token}/"
    if not zip_key.startswith(expected_prefix):
        return jsonify({
            "error": "key does not match reserved token"
        }), 400

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

    pj = ProcessingJob(
        job_id=job_token,
        property_id=t.property_id,
        upload_id=upload.id,
        property_name=Property.query.get(t.property_id).name,
        state=(Property.query.get(t.property_id).state or "TX"),
        status="queued",
        zip_key=zip_key,
        demo=False,
    )
    upload.status = "queued"

    # Mark token usage: decrement counter, record last_used_at.
    if t.uses_remaining is not None:
        t.uses_remaining = max(0, t.uses_remaining - 1)
    t.last_used_at = datetime.utcnow()

    db.session.add(pj)
    db.session.commit()

    logger.info(
        "Token %s confirmed upload %d → job %s (uses_remaining=%s)",
        token[:8], upload.id, job_token, t.uses_remaining,
    )
    return jsonify({
        "upload_id": upload.id,
        "job_id": pj.job_id,
        "status": "queued",
        "size_bytes": size_bytes,
    })


@token_uploads_bp.route(
    "/<string:token>/uploads/<int:upload_id>/status", methods=["GET"]
)
def upload_status(token, upload_id):
    # Status polling uses is_readable() — an exhausted single-use
    # token should still be usable to check the status of the one
    # upload it initiated.
    t = _load_token(token, for_new_upload=False)
    if not t:
        return jsonify({"error": "Invalid or expired upload token."}), 404
    upload = Upload.query.get(upload_id)
    if not upload or upload.property_id != t.property_id:
        return jsonify({"error": "Upload not found."}), 404
    pj = ProcessingJob.query.filter_by(upload_id=upload.id).first()
    status = (pj.status if pj else None) or upload.status
    return jsonify({
        "upload_id": upload.id,
        "job_id": pj.job_id if pj else None,
        "status": status,
        "error_message": pj.error_message if pj else upload.error_message,
        "photo_count": upload.photo_count,
        "n_species": pj.n_species if pj else None,
        "n_events": pj.n_events if pj else None,
    })


# ---------------------------------------------------------------------------
# Owner-scoped token issuance (login_required)
# ---------------------------------------------------------------------------

@upload_tokens_bp.route(
    "/properties/<int:property_id>/upload-tokens", methods=["POST"]
)
@login_required
def issue_token(property_id):
    """Issue a new upload token for a parcel.

    Requires the caller to be the parcel owner (``user_id`` matches) or
    to hold the ``is_owner`` flag (Basal ops).

    Body (all optional):
      label        — free-form string ("Matagorda pilot · Phil Moore")
      email_hint   — email the link is being sent to
      uses         — how many uploads the token allows (default 10)
      ttl_days     — days until expiry (default 90)
    """
    prop = Property.query.get(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404
    allowed = (
        getattr(current_user, "is_owner", False)
        or getattr(prop, "user_id", None) == getattr(current_user, "id", None)
    )
    if not allowed:
        return jsonify({"error": "Not authorized"}), 403

    body = request.get_json(silent=True) or {}
    label = (body.get("label") or "").strip() or None
    email_hint = (body.get("email_hint") or "").strip() or None
    uses = int(body.get("uses") or 10)
    ttl_days = int(body.get("ttl_days") or 90)

    # 32-hex ≈ 128 bits. Plenty for an unguessable share link.
    token_str = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(days=ttl_days)

    t = UploadToken(
        token=token_str,
        property_id=prop.id,
        created_by_user_id=current_user.id,
        label=label,
        email_hint=email_hint,
        uses_remaining=uses,
        expires_at=expires_at,
    )
    db.session.add(t)
    db.session.commit()

    share_url = _share_url(token_str)
    resp = {
        "token": token_str,
        "share_url": share_url,
        "property_id": prop.id,
        "uses_remaining": t.uses_remaining,
        "expires_at": expires_at.isoformat(),
        "label": t.label,
    }

    # Best-effort email dispatch — token is already persisted, so a
    # send failure must not 500 the caller. We still surface the
    # result so the UI can show "emailed Phil" vs. "copy this link".
    if body.get("send_email") and email_hint and "@" in email_hint:
        try:
            from web.notify import send_upload_invite
            sent = send_upload_invite(
                to_email=email_hint,
                parcel_name=prop.name,
                share_url=share_url,
                expires_at_iso=expires_at.isoformat(),
                label=label,
            )
            resp["email_sent"] = bool(sent)
            if not sent:
                resp["email_error"] = "provider declined"
        except Exception as e:  # noqa: BLE001
            logger.exception("send_upload_invite failed for token %s", token_str[:8])
            resp["email_sent"] = False
            resp["email_error"] = str(e)

    return jsonify(resp), 201


@upload_tokens_bp.route(
    "/properties/<int:property_id>/upload-tokens", methods=["GET"]
)
@login_required
def list_tokens(property_id):
    prop = Property.query.get(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404
    allowed = (
        getattr(current_user, "is_owner", False)
        or getattr(prop, "user_id", None) == getattr(current_user, "id", None)
    )
    if not allowed:
        return jsonify({"error": "Not authorized"}), 403

    rows = (UploadToken.query
            .filter_by(property_id=prop.id)
            .order_by(UploadToken.created_at.desc())
            .all())
    return jsonify({
        "tokens": [
            {
                "token": r.token,
                "share_url": _share_url(r.token),
                "label": r.label,
                "email_hint": r.email_hint,
                "uses_remaining": r.uses_remaining,
                "revoked": r.revoked,
                "expires_at": (r.expires_at.isoformat()
                               if r.expires_at else None),
                "last_used_at": (r.last_used_at.isoformat()
                                 if r.last_used_at else None),
                "created_at": (r.created_at.isoformat()
                               if r.created_at else None),
            }
            for r in rows
        ],
    })


@upload_tokens_bp.route(
    "/properties/<int:property_id>/upload-tokens/<string:token>",
    methods=["DELETE"]
)
@login_required
def revoke_token(property_id, token):
    prop = Property.query.get(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404
    allowed = (
        getattr(current_user, "is_owner", False)
        or getattr(prop, "user_id", None) == getattr(current_user, "id", None)
    )
    if not allowed:
        return jsonify({"error": "Not authorized"}), 403

    t = UploadToken.query.filter_by(
        token=token, property_id=prop.id
    ).first()
    if not t:
        return jsonify({"error": "Token not found"}), 404
    t.revoked = True
    db.session.commit()
    return jsonify({"token": t.token, "revoked": True})
