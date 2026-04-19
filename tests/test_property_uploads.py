"""Property-scoped pre-signed upload flow — request / confirm / status.

Mirrors the parcel uploads tests but hits the /api/properties/<pid>/uploads/
alias the hunter-facing upload UI uses. Both URL trees share the same
handlers via the dual-blueprint registration, so this suite mainly
guards the alias wiring — if someone deletes the @property_uploads_bp
decorator, these fail.

Patches strecker.storage at the web.routes.api.parcel_uploads import
site so we never actually hit Spaces.
"""

import json
import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest


_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-propup-", suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def client():
    from web.app import create_app
    from db.models import db, Property, User
    # Strecker site is the hunter-facing one that has both the legacy
    # streaming POST (now 410) and the pre-signed-URL alias. Register
    # the site accordingly so the deprecation test can fire.
    app = create_app(demo=True, site="strecker")
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        # The strecker site's demo auto-login uses demo@strecker.app.
        # Parcel ownership must match that user for _user_can_upload()
        # to pass without is_owner=True.
        owner = User.query.filter_by(email="demo@strecker.app").first()
        if owner is None:
            owner = User(
                email="demo@strecker.app", is_owner=True,
                password_hash="x")
            db.session.add(owner)
            db.session.commit()
        parcel = Property.query.filter_by(name="PropUpload Parcel").first()
        if parcel is None:
            boundary = {"type": "Feature", "geometry": {"type": "Polygon",
                "coordinates": [[[-96.5, 30.5], [-96.5, 30.6], [-96.4, 30.6],
                                  [-96.4, 30.5], [-96.5, 30.5]]]}}
            parcel = Property(
                user_id=owner.id, name="PropUpload Parcel",
                county="Brazos", state="TX", acreage=400,
                boundary_geojson=json.dumps(boundary), crop_type="corn")
            db.session.add(parcel)
            db.session.commit()
        pid = parcel.id
    yield app, app.test_client(), pid


def _fake_presign(key, expires_in=600, max_bytes=None,
                  content_type="application/zip"):
    return {
        "upload_url": f"https://fake.nyc3.digitaloceanspaces.com/{key}",
        "key": key, "method": "PUT",
        "headers": {"Content-Type": content_type},
        "expires_in": expires_in, "max_bytes": max_bytes,
    }


def _fake_head(size):
    return lambda key: {
        "size_bytes": size, "content_type": "application/zip",
        "etag": "deadbeef", "last_modified": None,
    }


# ---------------------------------------------------------------------------
# request → confirm → status, happy path
# ---------------------------------------------------------------------------

def test_request_issues_presigned_put(client):
    _, c, pid = client
    with patch(
        "web.routes.api.parcel_uploads.storage.generate_presigned_put",
        side_effect=_fake_presign,
    ):
        r = c.post(f"/api/properties/{pid}/uploads/request",
                   json={"filename": "upload.zip", "size_bytes": 5_000_000})
    assert r.status_code == 201, r.data
    body = r.get_json()
    assert body["upload_url"].startswith("https://")
    assert body["method"] == "PUT"
    assert body["job_id_reservation"]
    assert body["key"].startswith(f"uploads/{body['job_id_reservation']}/")


def test_confirm_creates_processing_job(client):
    _, c, pid = client
    with patch(
        "web.routes.api.parcel_uploads.storage.generate_presigned_put",
        side_effect=_fake_presign,
    ):
        r1 = c.post(f"/api/properties/{pid}/uploads/request",
                    json={"filename": "upload.zip", "size_bytes": 1_000_000})
    req = r1.get_json()
    with patch("web.routes.api.parcel_uploads.storage.head",
               side_effect=_fake_head(1_000_000)):
        r2 = c.post(
            f"/api/properties/{pid}/uploads/{req['upload_id']}/confirm",
            json={"key": req["key"],
                  "job_id_reservation": req["job_id_reservation"]})
    assert r2.status_code == 200, r2.data
    conf = r2.get_json()
    assert conf["status"] == "queued"
    assert conf["job_id"] == req["job_id_reservation"]


def test_status_reflects_upload_state(client):
    _, c, pid = client
    with patch(
        "web.routes.api.parcel_uploads.storage.generate_presigned_put",
        side_effect=_fake_presign,
    ):
        r1 = c.post(f"/api/properties/{pid}/uploads/request",
                    json={"filename": "upload.zip", "size_bytes": 500_000})
    req = r1.get_json()
    with patch("web.routes.api.parcel_uploads.storage.head",
               side_effect=_fake_head(500_000)):
        c.post(f"/api/properties/{pid}/uploads/{req['upload_id']}/confirm",
               json={"key": req["key"],
                     "job_id_reservation": req["job_id_reservation"]})
    r3 = c.get(f"/api/properties/{pid}/uploads/{req['upload_id']}/status")
    assert r3.status_code == 200, r3.data
    assert r3.get_json()["status"] == "queued"


# ---------------------------------------------------------------------------
# validation failures
# ---------------------------------------------------------------------------

def test_request_rejects_non_zip(client):
    _, c, pid = client
    r = c.post(f"/api/properties/{pid}/uploads/request",
               json={"filename": "ball.txt", "size_bytes": 1_000})
    assert r.status_code == 400
    assert "zip" in r.get_json()["error"].lower()


def test_request_rejects_oversize(client):
    """Cap is 2 GB; 3 GB must be rejected."""
    _, c, pid = client
    r = c.post(f"/api/properties/{pid}/uploads/request",
               json={"filename": "huge.zip",
                     "size_bytes": 3 * 1024 * 1024 * 1024})
    assert r.status_code == 413


def test_confirm_without_upload_returns_404(client):
    _, c, pid = client
    with patch("web.routes.api.parcel_uploads.storage.head",
               return_value=None):
        r = c.post(f"/api/properties/{pid}/uploads/99999/confirm",
                   json={"key": "uploads/deadbeef/upload.zip",
                         "job_id_reservation": "deadbeef"})
    assert r.status_code == 404


def test_confirm_rejects_missing_storage_object(client):
    _, c, pid = client
    with patch(
        "web.routes.api.parcel_uploads.storage.generate_presigned_put",
        side_effect=_fake_presign,
    ):
        r1 = c.post(f"/api/properties/{pid}/uploads/request",
                    json={"filename": "upload.zip",
                          "size_bytes": 2_000_000})
    req = r1.get_json()
    with patch("web.routes.api.parcel_uploads.storage.head",
               return_value=None):
        r2 = c.post(
            f"/api/properties/{pid}/uploads/{req['upload_id']}/confirm",
            json={"key": req["key"],
                  "job_id_reservation": req["job_id_reservation"]})
    assert r2.status_code == 404
    assert "storage" in r2.get_json()["error"].lower()


# ---------------------------------------------------------------------------
# deprecated streaming POST → 410 Gone
# ---------------------------------------------------------------------------

def test_legacy_streaming_post_returns_410(client):
    _, c, pid = client
    r = c.post(f"/api/properties/{pid}/uploads",
               data={"file": (tempfile.NamedTemporaryFile(suffix=".zip"),
                              "upload.zip")},
               content_type="multipart/form-data")
    assert r.status_code == 410
    body = r.get_json()
    assert "request" in body["replacement"]
    assert body["replacement"]["request"].endswith(
        f"/api/properties/{pid}/uploads/request")
