"""Passwordless upload tokens — the v2 auth flow.

Validates:
  - Owner can mint an UploadToken via /api/properties/<pid>/upload-tokens
  - The token opens the /u/<token>/uploads/{request,confirm,status}
    flow WITHOUT a login session
  - Revoked / expired / exhausted tokens are rejected
  - Uses counter decrements on successful confirm
  - Token scoped to its parcel: can't be used to upload to another
"""

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest


_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-toktok-", suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def ctx():
    from web.app import create_app
    from db.models import db, Property, User, UploadToken
    app = create_app(demo=True, site="strecker")
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        owner = User.query.filter_by(email="demo@strecker.app").first()
        if owner is None:
            owner = User(email="demo@strecker.app", is_owner=True,
                         password_hash="x")
            db.session.add(owner); db.session.commit()
        parcel = Property.query.filter_by(name="Token Parcel").first()
        if parcel is None:
            b = {"type": "Feature", "geometry": {"type": "Polygon",
                 "coordinates": [[[-96.5,30.5],[-96.5,30.6],
                                  [-96.4,30.6],[-96.4,30.5],[-96.5,30.5]]]}}
            parcel = Property(
                user_id=owner.id, name="Token Parcel",
                county="Brazos", state="TX", acreage=320,
                boundary_geojson=json.dumps(b), crop_type="corn")
            db.session.add(parcel); db.session.commit()
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
        "etag": "beef", "last_modified": None,
    }


# ---------------------------------------------------------------------------
# Owner mints a token, landowner uses it
# ---------------------------------------------------------------------------

def test_owner_issues_token_and_lists_it(ctx):
    _, c, pid = ctx
    r1 = c.post(f"/api/properties/{pid}/upload-tokens",
                json={"label": "Matagorda pilot",
                      "email_hint": "phil@matagorda-ag.test",
                      "uses": 3, "ttl_days": 30})
    assert r1.status_code == 201, r1.data
    j = r1.get_json()
    assert j["token"] and len(j["token"]) >= 32
    assert j["share_url"].endswith(j["token"])
    assert j["uses_remaining"] == 3

    r2 = c.get(f"/api/properties/{pid}/upload-tokens")
    assert r2.status_code == 200
    toks = r2.get_json()["tokens"]
    assert any(t["token"] == j["token"] for t in toks)


def test_token_info_describes_parcel(ctx):
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken
        t = UploadToken.query.filter_by(property_id=pid).first()
        tok = t.token
    r = c.get(f"/u/{tok}")
    assert r.status_code == 200
    body = r.get_json()
    assert body["parcel_name"] == "Token Parcel"
    assert body["county"] == "Brazos"
    assert body["uses_remaining"] >= 1


def test_tokenized_upload_flow_happy_path(ctx):
    """request → confirm → status, NO login_required, uses counter decrements."""
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken, db as _db
        t = UploadToken(
            token="t" + "a" * 31, property_id=pid,
            uses_remaining=5,
            expires_at=datetime.utcnow() + timedelta(days=5),
        )
        _db.session.add(t); _db.session.commit()
        tok = t.token

    # Fresh client with no session — this is the key guarantee.
    fresh = c.application.test_client()

    with patch("web.routes.api.token_uploads.storage.generate_presigned_put",
               side_effect=_fake_presign):
        r1 = fresh.post(f"/u/{tok}/uploads/request",
                        json={"filename": "sd.zip",
                              "size_bytes": 4_000_000})
    assert r1.status_code == 201, r1.data
    req = r1.get_json()

    with patch("web.routes.api.token_uploads.storage.head",
               side_effect=_fake_head(4_000_000)):
        r2 = fresh.post(
            f"/u/{tok}/uploads/{req['upload_id']}/confirm",
            json={"key": req["key"],
                  "job_id_reservation": req["job_id_reservation"]})
    assert r2.status_code == 200, r2.data
    assert r2.get_json()["status"] == "queued"

    r3 = fresh.get(f"/u/{tok}/uploads/{req['upload_id']}/status")
    assert r3.status_code == 200
    assert r3.get_json()["status"] == "queued"

    # uses_remaining decremented by confirm
    with app.app_context():
        from db.models import UploadToken
        t = UploadToken.query.filter_by(token=tok).first()
        assert t.uses_remaining == 4
        assert t.last_used_at is not None


# ---------------------------------------------------------------------------
# Rejections
# ---------------------------------------------------------------------------

def test_invalid_token_returns_404(ctx):
    _, c, _ = ctx
    r = c.get("/u/does-not-exist-0000")
    assert r.status_code == 404


def test_revoked_token_rejected(ctx):
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken, db as _db
        t = UploadToken(token="r" * 32, property_id=pid,
                        uses_remaining=3, revoked=True)
        _db.session.add(t); _db.session.commit()
    r = c.post(f"/u/{'r' * 32}/uploads/request",
               json={"filename": "x.zip", "size_bytes": 1_000})
    assert r.status_code == 404


def test_exhausted_token_rejected(ctx):
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken, db as _db
        t = UploadToken(token="e" * 32, property_id=pid, uses_remaining=0)
        _db.session.add(t); _db.session.commit()
    r = c.post(f"/u/{'e' * 32}/uploads/request",
               json={"filename": "x.zip", "size_bytes": 1_000})
    assert r.status_code == 404


def test_expired_token_rejected(ctx):
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken, db as _db
        t = UploadToken(
            token="x" * 32, property_id=pid, uses_remaining=3,
            expires_at=datetime.utcnow() - timedelta(seconds=5))
        _db.session.add(t); _db.session.commit()
    r = c.post(f"/u/{'x' * 32}/uploads/request",
               json={"filename": "x.zip", "size_bytes": 1_000})
    assert r.status_code == 404


def test_revoke_endpoint_marks_token_revoked(ctx):
    app, c, pid = ctx
    with app.app_context():
        from db.models import UploadToken, db as _db
        t = UploadToken(token="v" * 32, property_id=pid, uses_remaining=3)
        _db.session.add(t); _db.session.commit()
    r = c.delete(f"/api/properties/{pid}/upload-tokens/{'v' * 32}")
    assert r.status_code == 200
    assert r.get_json()["revoked"] is True
    # and it's now refused on the token endpoint
    r2 = c.get(f"/u/{'v' * 32}")
    assert r2.status_code == 404


def test_token_cannot_target_other_parcel(ctx):
    """A token for parcel A cannot be used to upload to parcel B —
    since the endpoints key authorization off the token's property_id,
    there is no parcel-override path to exploit. This guards against
    accidental route drift.
    """
    app, c, pid = ctx
    # Create a second parcel with a different owner — confirming that
    # the token never leaks into it.
    with app.app_context():
        from db.models import (User, Property, UploadToken, db as _db)
        other_user = User(email="other@landowner.test", password_hash="x")
        _db.session.add(other_user); _db.session.commit()
        b = {"type": "Feature", "geometry": {"type": "Polygon",
             "coordinates": [[[-97,30],[-97,31],[-96,31],[-96,30],[-97,30]]]}}
        other = Property(user_id=other_user.id, name="Other Parcel",
                         county="Hays", state="TX", acreage=100,
                         boundary_geojson=json.dumps(b), crop_type="corn")
        _db.session.add(other); _db.session.commit()
        other_id = other.id
        other_user_id = other_user.id

        tok_for_pid = UploadToken(
            token="p" * 32, property_id=pid, uses_remaining=3)
        _db.session.add(tok_for_pid); _db.session.commit()

    # A token-auth upload confirms against a row only if the upload's
    # property_id matches the token's property_id. Use an upload_id
    # that belongs to a different parcel — expect 404.
    from db.models import Upload, db as _db
    with app.app_context():
        u = Upload(property_id=other_id, user_id=other_user_id,
                   status="pending_upload", photo_count=None)
        _db.session.add(u); _db.session.commit()
        uid = u.id

    r = c.post(f"/u/{'p' * 32}/uploads/{uid}/confirm",
               json={"key": "uploads/deadbeef/upload.zip",
                     "job_id_reservation": "deadbeef"})
    assert r.status_code == 404
