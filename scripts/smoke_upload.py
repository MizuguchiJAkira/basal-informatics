#!/usr/bin/env python3
"""Local end-to-end smoke test for the hunter upload flow.

Runs the full three-phase upload path against an in-process Flask app
with local-filesystem storage (no Spaces credentials needed). Mints an
upload token via the owner-auth API, then exercises request → simulated
PUT → confirm → status using a cookieless client so the token is the
authorization — exactly the path a landowner follows from an emailed
share link.

This is NOT a substitute for a live SD-card run against the real Space
and the real GPU worker. It exists to catch wiring regressions after a
deploy or refactor: if the HTTP shape is intact and the DB rows land
in the right states, this script exits 0.

Usage
-----
    python scripts/smoke_upload.py

Exits 0 on success, non-zero with a diagnostic on failure.
"""

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Isolate from any dev DB + force local-fs storage.
# ---------------------------------------------------------------------------
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-smoke-upload-", suffix=".db", delete=False).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "smoke-test-secret")

# No Spaces → storage.py uses local-fs fallback.
os.environ.pop("SPACES_BUCKET", None)
UPLOAD_DIR = tempfile.mkdtemp(prefix="basal-smoke-uploads-")
os.environ["STRECKER_UPLOAD_DIR"] = UPLOAD_DIR


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_STEP_N = 0


def step(label: str) -> None:
    global _STEP_N
    _STEP_N += 1
    print(f"\n[{_STEP_N}] {label}")


def _make_fake_zip(dest: Path) -> Path:
    """Three tiny 'JPEGs' — enough bytes for HEAD to pass, no decode."""
    with zipfile.ZipFile(dest, "w") as z:
        for i in range(3):
            z.writestr(
                f"IMG_{i:04d}.jpg",
                b"\xFF\xD8\xFF\xE0" + b"0" * 2000,  # JPEG magic + filler
            )
    return dest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    from web.app import create_app
    from db.models import Property, User, db

    app = create_app(demo=True, site="strecker")
    app.config["WTF_CSRF_ENABLED"] = False
    owner_client = app.test_client()

    step("Seed demo owner + smoke parcel")
    with app.app_context():
        owner = User.query.filter_by(email="demo@strecker.app").first()
        if owner is None:
            owner = User(
                email="demo@strecker.app", is_owner=True,
                password_hash="x")
            db.session.add(owner)
            db.session.commit()
        parcel = Property.query.filter_by(name="Smoke Parcel").first()
        if parcel is None:
            b = {"type": "Feature", "geometry": {"type": "Polygon",
                 "coordinates": [[[-96.5, 30.5], [-96.5, 30.6],
                                  [-96.4, 30.6], [-96.4, 30.5],
                                  [-96.5, 30.5]]]}}
            parcel = Property(
                user_id=owner.id, name="Smoke Parcel",
                county="Brazos", state="TX", acreage=100,
                boundary_geojson=json.dumps(b), crop_type="corn")
            db.session.add(parcel)
            db.session.commit()
        pid = parcel.id
    print(f"    parcel_id={pid}")

    step("Mint an upload token (owner-auth)")
    r = owner_client.post(
        f"/api/properties/{pid}/upload-tokens",
        json={"label": "smoke-test", "uses": 1, "ttl_days": 1})
    assert r.status_code == 201, (r.status_code, r.data)
    t = r.get_json()
    token = t["token"]
    print(f"    token        {token[:12]}…")
    print(f"    share_url    {t['share_url']}")
    print(f"    expires_at   {t['expires_at']}")

    # Cookieless client — the token in the URL is the only auth.
    bare = app.test_client()

    step("GET /u/<token> — parcel preview")
    r = bare.get(f"/u/{token}")
    assert r.status_code == 200, (r.status_code, r.data)
    info = r.get_json()
    print(f"    parcel       {info['parcel_name']}")
    print(f"    county       {info['county']}, {info['state']}")
    print(f"    uses_left    {info['uses_remaining']}")

    step("Build a tiny fake SD-card ZIP")
    zip_path = Path(tempfile.mkdtemp()) / "smoke.zip"
    _make_fake_zip(zip_path)
    size = zip_path.stat().st_size
    print(f"    {zip_path}  {size} bytes")

    step("POST /u/<token>/uploads/request — presigned PUT")
    r = bare.post(
        f"/u/{token}/uploads/request",
        json={"filename": "smoke.zip", "size_bytes": size})
    assert r.status_code == 201, (r.status_code, r.data)
    req = r.get_json()
    assert req["upload_url"].startswith("local-put://"), \
        f"expected local-fs pseudo URL, got {req['upload_url']}"
    print(f"    upload_id    {req['upload_id']}")
    print(f"    job_token    {req['job_id_reservation']}")
    print(f"    key          {req['key']}")

    step("Simulate Spaces PUT by copying bytes to local-fs path")
    dest = Path(UPLOAD_DIR) / req["key"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(zip_path, dest)
    print(f"    -> {dest}")

    step("POST /u/<token>/uploads/<uid>/confirm — HEAD + enqueue")
    r = bare.post(
        f"/u/{token}/uploads/{req['upload_id']}/confirm",
        json={"key": req["key"],
              "job_id_reservation": req["job_id_reservation"]})
    assert r.status_code == 200, (r.status_code, r.data)
    conf = r.get_json()
    assert conf["status"] == "queued", conf
    print(f"    job_id       {conf['job_id']}")
    print(f"    status       {conf['status']}")
    print(f"    size_bytes   {conf['size_bytes']}")

    step("GET /u/<token>/uploads/<uid>/status")
    r = bare.get(f"/u/{token}/uploads/{req['upload_id']}/status")
    assert r.status_code == 200, (r.status_code, r.data)
    status = r.get_json()
    print(f"    response     {status}")
    assert status["status"] == "queued", status
    print(f"    status       {status['status']}")

    step("Verify DB state")
    with app.app_context():
        from db.models import ProcessingJob, UploadToken
        pj = ProcessingJob.query.filter_by(
            job_id=req["job_id_reservation"]).first()
        assert pj is not None, "ProcessingJob row missing"
        assert pj.zip_key == req["key"]
        assert pj.property_id == pid
        t2 = UploadToken.query.filter_by(token=token).first()
        assert t2.uses_remaining == 0, \
            f"uses_remaining should be 0 after one confirm; got {t2.uses_remaining}"
        assert t2.last_used_at is not None
        print(f"    ProcessingJob   job_id={pj.job_id} status={pj.status}")
        print(f"    UploadToken     uses_remaining={t2.uses_remaining} "
              f"last_used={t2.last_used_at.isoformat(timespec='seconds')}")

    step("Verify second use of a one-shot token is rejected")
    r = bare.post(
        f"/u/{token}/uploads/request",
        json={"filename": "again.zip", "size_bytes": size})
    assert r.status_code == 404, (r.status_code, r.data)
    print(f"    second request → 404 as expected")

    print()
    print("✓ hunter upload wiring end-to-end — all assertions passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\n✗ SMOKE FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
