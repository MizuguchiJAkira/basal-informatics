"""Layer 4 — API endpoint smoke tests.

The app has 66 registered routes. Rather than fixture-up every one
(many require real file uploads, image IDs, or background workers)
I hit the demo-critical subset with:

  - happy-path 200 on valid inputs (demo mode auto-login)
  - branded 404 on unknown slug / parcel
  - 401/302-to-login on non-demo-mode protected routes
  - method-not-allowed 405 where a POST-only route is GET'd

Not-in-scope:
  - upload pipeline routes that require a real SD-card ZIP
  - Strecker deer re-ID routes (torch-model dependent)
  - feedback POST routes (need prior detection rows)
"""

import json
import os
import tempfile
from datetime import date, datetime

import pytest


_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-api-", suffix=".db", delete=False
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


# ---------------------------------------------------------------------------
# Demo-mode fixture (basal-site, auto-login active)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def demo_client():
    from web.app import create_app
    from db.models import (db, User, LenderClient, Property, Season, Camera,
                            DetectionSummary)
    app = create_app(demo=True, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        owner = User.query.filter_by(email="owner@basal.eco").first()
        assert owner is not None
        lender = LenderClient.query.filter_by(slug="fcct").first()
        if lender is None:
            lender = LenderClient(
                name="Farm Credit of Central Texas", slug="fcct",
                state="TX", active=True)
            db.session.add(lender); db.session.commit()
        parcel = Property.query.filter_by(name="Route Test Parcel").first()
        if parcel is None:
            boundary = {
                "type": "Feature",
                "properties": {"name": "Route Test Parcel"},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-96.52, 30.57], [-96.52, 30.62], [-96.46, 30.62],
                    [-96.46, 30.57], [-96.52, 30.57]]]},
            }
            parcel = Property(user_id=owner.id, name="Route Test Parcel",
                              county="Brazos", state="TX", acreage=650,
                              boundary_geojson=json.dumps(boundary),
                              lender_client_id=lender.id, crop_type="corn")
            db.session.add(parcel); db.session.commit()

            season = Season(property_id=parcel.id, name="Spring 2026",
                            start_date=date(2026, 2, 1),
                            end_date=date(2026, 3, 31))
            db.session.add(season); db.session.commit()
            cams = [Camera(property_id=parcel.id, camera_label=f"CAM-{i:02d}",
                           lat=30.595 + i * 0.01, lon=-96.505,
                           placement_context="random" if i > 1 else "feeder",
                           is_active=True)
                    for i in range(4)]
            db.session.add_all(cams); db.session.commit()
            h24 = [0]*20 + [5, 8, 6, 4]
            for i, c in enumerate(cams):
                db.session.add(DetectionSummary(
                    season_id=season.id, camera_id=c.id,
                    species_key="feral_hog",
                    total_photos=80, independent_events=20,
                    avg_confidence=0.9,
                    first_seen=datetime(2026, 2, 3),
                    last_seen=datetime(2026, 3, 30),
                    peak_hour=22, hourly_distribution=json.dumps(h24)))
            db.session.commit()
        parcel_id = parcel.id
    client = app.test_client()
    yield app, client, parcel_id


# ---------------------------------------------------------------------------
# Happy-path 200s
# ---------------------------------------------------------------------------

def test_health_returns_200_with_db_true(demo_client):
    _, c, _ = demo_client
    r = c.get("/health")
    assert r.status_code == 200
    assert r.get_json()["db"] is True


def test_root_on_basal_site_redirects_to_owner_coverage(demo_client):
    _, c, _ = demo_client
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 308)
    # "basal" site redirects to /owner/coverage
    assert "/owner/coverage" in r.headers.get("Location", "")


def test_lender_index_redirects_when_one_lender(demo_client):
    _, c, _ = demo_client
    r = c.get("/lender/", follow_redirects=False)
    assert r.status_code in (200, 302, 301)


def test_lender_portfolio_happy_path(demo_client):
    _, c, _ = demo_client
    r = c.get("/lender/fcct/")
    assert r.status_code == 200


def test_lender_parcel_report_happy_path(demo_client):
    _, c, pid = demo_client
    r = c.get(f"/lender/fcct/parcel/{pid}")
    assert r.status_code == 200


def test_lender_parcel_exposure_json_happy_path(demo_client):
    _, c, pid = demo_client
    r = c.get(f"/lender/api/fcct/parcel/{pid}/exposure")
    assert r.status_code == 200
    j = r.get_json()
    assert "exposures" in j
    assert "season" in j


def test_lender_parcel_upload_form_happy_path(demo_client):
    _, c, pid = demo_client
    r = c.get(f"/lender/fcct/parcel/{pid}/upload")
    assert r.status_code == 200


def test_owner_coverage_happy_path(demo_client):
    _, c, _ = demo_client
    r = c.get("/owner/coverage")
    # Owner coverage needs is_owner=True which demo user is.
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 404s — branded template
# ---------------------------------------------------------------------------

def test_404_unknown_lender_slug(demo_client):
    _, c, _ = demo_client
    r = c.get("/lender/nonexistent/")
    assert r.status_code == 404
    assert b"Not found" in r.data


def test_404_unknown_parcel_id(demo_client):
    _, c, _ = demo_client
    r = c.get("/lender/fcct/parcel/999999")
    assert r.status_code == 404
    assert b"Not found" in r.data


def test_404_malformed_parcel_id(demo_client):
    """/lender/fcct/parcel/not-an-int → Flask routing 404."""
    _, c, _ = demo_client
    r = c.get("/lender/fcct/parcel/not-an-int")
    assert r.status_code == 404


def test_404_unknown_route(demo_client):
    _, c, _ = demo_client
    r = c.get("/this/route/does/not/exist")
    assert r.status_code == 404
    # Branded template should still fire.
    assert b"Not found" in r.data


def test_api_json_404_returns_json_error(demo_client):
    """JSON API route must return JSON on an unknown parcel, not the
    HTML branded 404 template (which would break any downstream
    Farm Credit importer)."""
    _, c, _ = demo_client
    r = c.get("/lender/api/fcct/parcel/999999/exposure")
    assert r.status_code == 404
    assert "json" in r.content_type.lower()
    body = r.get_json()
    assert "error" in body


# ---------------------------------------------------------------------------
# Methods / CSRF
# ---------------------------------------------------------------------------

def test_405_on_wrong_method(demo_client):
    """Portfolio route is GET-only; POST returns 405."""
    _, c, _ = demo_client
    r = c.post("/lender/fcct/")
    assert r.status_code == 405


# ---------------------------------------------------------------------------
# Non-demo auth gating
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def nondemo_client():
    """App built with demo=False so auth is actually enforced."""
    from web.app import create_app
    app = create_app(demo=False, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False
    client = app.test_client()
    yield client


def test_lender_portfolio_requires_login_nondemo(nondemo_client):
    """Without demo mode + no login session → redirect to /login."""
    r = nondemo_client.get("/lender/fcct/", follow_redirects=False)
    # @login_required redirects to login_view (auth.login)
    assert r.status_code in (302, 401)
    if r.status_code == 302:
        assert "/login" in r.headers.get("Location", "")


def test_lender_api_requires_login_nondemo(nondemo_client):
    r = nondemo_client.get("/lender/api/fcct/parcel/1/exposure",
                           follow_redirects=False)
    assert r.status_code in (302, 401)


def test_public_health_route_available_without_login(nondemo_client):
    """/health must be reachable without auth (DO probe hits it anon)."""
    r = nondemo_client.get("/health")
    assert r.status_code == 200
