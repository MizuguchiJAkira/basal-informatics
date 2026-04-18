"""Integration tests for web/routes/lender.py.

The lender route tree is the entire demo. It grew several helpers this
round (_hog_history, _hog_hourly_activity, _build_exec_summary,
_confidence_grade) with zero coverage — a template-level regression
(bad attr access, missing context var, Jinja syntax error) would only
surface on browser reload. These tests catch that class of failure
by actually rendering the full page via the Flask test client.

Strategy:
  - Build the app with demo=True + site=basal against in-memory SQLite.
  - Seed the minimum row set: User, LenderClient, Property with
    boundary GeoJSON, Season, 4 Cameras (random + biased mix),
    DetectionSummaries for feral_hog + a non-hog species, plus a
    prior-season DetectionSummary for the trend widget.
  - Hit /lender/fcct/, /lender/fcct/parcel/<id>, and
    /lender/api/fcct/parcel/<id>/exposure. Assert status 200 and
    presence of the markers we added this round.

The tests don't re-verify the underlying math — that's covered by
test_population.py + test_placement_ipw.py + test_exposure.py. These
are pure "the page rendered end-to-end and contains the expected
human-visible strings / JSON keys" checks.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime

import pytest


# Use a fresh per-run SQLite file for the test DB; override any prior
# env. Has to happen *before* config/settings is first imported — we
# clear any cached modules below to force a reload under the test URI.
_TEST_DB_FILE = tempfile.NamedTemporaryFile(
    prefix="basal-test-", suffix=".db", delete=False
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-do-not-use-in-prod")

# Evict any already-imported settings/db/app modules so they re-import
# against the test DATABASE_URL above.
import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app_client():
    """Build an app bound to a fresh in-memory SQLite, seed minimal
    FCCT portfolio, return (app, client, parcel_id).
    """
    # Import inside the fixture so os.environ above is honored.
    from web.app import create_app
    from db.models import (db, User, LenderClient, Property, Season, Camera,
                            DetectionSummary)

    app = create_app(demo=True, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        # create_app(demo=True, site="basal") already created the
        # schema AND seeded the owner@basal.eco user. Look it up
        # instead of re-inserting (email is UNIQUE).
        owner = User.query.filter_by(email="owner@basal.eco").first()
        assert owner is not None, "demo owner not seeded by create_app"
        if not owner.is_owner:
            owner.is_owner = True
            db.session.flush()

        lender = LenderClient(
            name="Farm Credit of Central Texas", slug="fcct",
            state="TX", contact_email="portfolio@fcct.example.com",
            plan_tier="per_parcel", per_parcel_rate_usd=1500.00,
            active=True,
        )
        db.session.add(lender)
        db.session.flush()

        boundary = {
            "type": "Feature",
            "properties": {"name": "Riverbend Farm"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-96.52, 30.57], [-96.52, 30.62],
                    [-96.46, 30.62], [-96.46, 30.57],
                    [-96.52, 30.57],
                ]],
            },
        }
        parcel = Property(
            user_id=owner.id, name="Riverbend Farm",
            county="Brazos", state="TX", acreage=650,
            boundary_geojson=json.dumps(boundary),
            lender_client_id=lender.id, crop_type="corn",
        )
        db.session.add(parcel)
        db.session.flush()
        parcel_id = parcel.id

        # Two seasons: Fall 2025 (prior) + Spring 2026 (current).
        season_prior = Season(
            property_id=parcel.id, name="Fall 2025",
            start_date=date(2025, 9, 1), end_date=date(2025, 11, 30),
        )
        season_current = Season(
            property_id=parcel.id, name="Spring 2026",
            start_date=date(2026, 2, 1), end_date=date(2026, 3, 31),
        )
        db.session.add_all([season_prior, season_current])
        db.session.flush()

        # Four cameras: 2 biased + 2 random-placement anchors.
        cams = [
            Camera(property_id=parcel.id, camera_label="CAM-RB-CORN-01",
                   name="Corn field north edge", lat=30.595, lon=-96.505,
                   placement_context="food_plot", is_active=True),
            Camera(property_id=parcel.id, camera_label="CAM-RB-CORN-02",
                   name="Corn field water crossing", lat=30.584, lon=-96.495,
                   placement_context="water", is_active=True),
            Camera(property_id=parcel.id, camera_label="CAM-RB-RAND-01",
                   name="Random sample SE", lat=30.591, lon=-96.474,
                   placement_context="random", is_active=True),
            Camera(property_id=parcel.id, camera_label="CAM-RB-RAND-02",
                   name="Random sample NW", lat=30.612, lon=-96.512,
                   placement_context="random", is_active=True),
        ]
        db.session.add_all(cams)
        db.session.flush()

        # Hourly distribution with a nocturnal peak so the temporal
        # sparkline fires.
        nocturnal = [0]*6 + [0]*14 + [5, 8, 6, 4]   # peaks 20-23
        hourly_json = json.dumps(nocturnal)

        # Spring 2026: 78 / 71 / 95 / 110 hog events per cam (matches
        # the live seed; density 13.47/km², Severe).
        hog_events = [78, 71, 95, 110]
        for cam, ev in zip(cams, hog_events):
            db.session.add(DetectionSummary(
                season_id=season_current.id, camera_id=cam.id,
                species_key="feral_hog",
                total_photos=ev * 4, independent_events=ev,
                avg_confidence=0.91,
                first_seen=datetime(2026, 2, 3, 22),
                last_seen=datetime(2026, 3, 30, 5),
                peak_hour=22, hourly_distribution=hourly_json,
            ))

        # Fall 2025 prior season — half the hog pressure, drives trend widget.
        prior_events = [50, 46, 62, 72]
        for cam, ev in zip(cams, prior_events):
            db.session.add(DetectionSummary(
                season_id=season_prior.id, camera_id=cam.id,
                species_key="feral_hog",
                total_photos=ev * 4, independent_events=ev,
                avg_confidence=0.89,
                first_seen=datetime(2025, 9, 5, 22),
                last_seen=datetime(2025, 11, 28, 5),
                peak_hour=22, hourly_distribution=hourly_json,
            ))

        # A secondary species so the "Other species detected" block renders.
        db.session.add(DetectionSummary(
            season_id=season_current.id, camera_id=cams[0].id,
            species_key="white_tailed_deer",
            total_photos=40, independent_events=12, avg_confidence=0.88,
            first_seen=datetime(2026, 2, 8, 7),
            last_seen=datetime(2026, 3, 22, 19),
            peak_hour=7, hourly_distribution=hourly_json,
        ))

        db.session.commit()

    client = app.test_client()
    yield app, client, parcel_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_portfolio_renders_with_tier_tally(app_client):
    _, client, _ = app_client
    resp = client.get("/lender/fcct/")
    assert resp.status_code == 200, resp.data[:400]
    body = resp.data.decode("utf-8", errors="replace")
    # Branded header + tier tally chips present.
    assert "Farm Credit of Central Texas" in body
    assert "SEVERE" in body.upper()
    assert "Riverbend Farm" in body


def test_parcel_report_contains_all_pdf_parity_markers(app_client):
    """Regression guard for the six additions made in the PDF-parity
    pass. If any helper crashes or any template block breaks, one of
    these markers disappears and the test fails."""
    _, client, pid = app_client
    resp = client.get(f"/lender/fcct/parcel/{pid}")
    assert resp.status_code == 200, resp.data[:400]
    body = resp.data.decode("utf-8", errors="replace")

    # (1) Executive summary banner
    assert "Executive summary" in body
    assert "Feral Hog Exposure:" in body

    # (2) Parcel map
    assert 'id="parcel-map"' in body
    assert "L.map('parcel-map'" in body
    assert "CAM-RB-RAND-01" in body

    # (3) Temporal activity — peak hour callout
    assert "Peak hour" in body
    assert "Temporal activity" in body

    # (4) Species inventory with raw + adjusted rate lines
    assert "Other species detected" in body
    assert "events/cam-day" in body
    assert "White Tailed Deer" in body

    # (5) Data-confidence grade block
    assert "Data confidence" in body
    # Grade must be one of A/B/C/D (Riverbend-shaped seed → B)
    import re
    grade_match = re.search(
        r'class="[^"]*text-5xl[^"]*"[^>]*>\s*([A-D])\s*<', body)
    assert grade_match is not None, "grade letter not found"
    assert grade_match.group(1) in {"A", "B", "C", "D"}

    # (6) Methodology appendix — collapsible <details> with full refs
    assert "<details" in body
    assert "Rowcliffe" in body     # in the refs list
    assert "Kolowski" in body      # in the IPW paragraph

    # Bonus: survey-trend widget from the prior-season seed
    assert "Survey trend" in body
    assert "Fall 2025" in body
    assert "Spring 2026" in body


def test_exposure_json_has_pipeline_and_history(app_client):
    """The JSON API is the compliance-ready import format for lender-
    side portfolio systems. Shape changes here silently break
    downstream importers — cover the contract."""
    _, client, pid = app_client
    resp = client.get(f"/lender/api/fcct/parcel/{pid}/exposure")
    assert resp.status_code == 200
    payload = resp.get_json()

    assert payload["lender"]["slug"] == "fcct"
    assert payload["season"]["name"] == "Spring 2026"

    hog = next((e for e in payload["exposures"]
                if e["species_key"] == "feral_hog"), None)
    assert hog is not None

    # Pipeline outputs
    p = hog["pipeline"]
    for key in ("tier", "score_0_100",
                "density_animals_per_km2",
                "detection_rate_per_camera_day",
                "detection_rate_adjusted_per_camera_day",
                "recommendation", "caveats", "method_notes",
                "history"):
        assert key in p, f"missing pipeline.{key}"

    # Bias-adjusted rate must be populated and below the raw rate for
    # a biased-mix deployment.
    assert p["detection_rate_per_camera_day"] is not None
    assert p["detection_rate_adjusted_per_camera_day"] is not None
    assert (p["detection_rate_adjusted_per_camera_day"]
            < p["detection_rate_per_camera_day"])

    # History array contains both seasons (oldest first).
    assert len(p["history"]) == 2
    assert p["history"][0]["season_name"] == "Fall 2025"
    assert p["history"][1]["season_name"] == "Spring 2026"
    assert p["history"][-1]["tier"] == "Severe"

    # Supplementary projection clearly labeled + structurally separated.
    sp = hog["supplementary_projection"]
    assert sp is not None
    assert sp["label"] == "MODELED PROJECTION"
    assert "Not a pipeline output" in sp["disclaimer"]


def test_unknown_parcel_returns_branded_404(app_client):
    """Error handler regression: a stale demo link should render the
    branded 404 template, not an unstyled Flask default."""
    _, client, _ = app_client
    resp = client.get("/lender/fcct/parcel/999999")
    assert resp.status_code == 404
    body = resp.data.decode("utf-8", errors="replace")
    assert "Not found" in body  # from the branded template


def test_health_endpoint_reports_db_ok(app_client):
    """Warm-DB health check — the key demo-day reliability signal.
    DO pings this every 30s per .do/app.yaml."""
    _, client, _ = app_client
    resp = client.get("/health")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["status"] == "ok"
    assert payload["db"] is True
