"""API tests for the underwriter override endpoint.

Covers: auth, validation, audit-log writes, rate limiting.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date

import pytest


_TEST_DB_FILE = tempfile.NamedTemporaryFile(
    prefix="basal-test-vapi-", suffix=".db", delete=False,
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-do-not-use-in-prod")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")
            or _mod.startswith("valuation")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def app_client():
    # Re-set env + evict modules INSIDE the fixture so that running
    # alongside other valuation test modules (which set their own
    # tempfile DATABASE_URL at import time) doesn't bleed across.
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"
    for _mod in list(_sys.modules):
        if (_mod == "config" or _mod.startswith("config.")
                or _mod == "db" or _mod.startswith("db.")
                or _mod.startswith("web.")
                or _mod.startswith("valuation")):
            _sys.modules.pop(_mod, None)

    from web.app import create_app
    from db.models import (
        db, User, LenderClient, Property, Season, Camera, DetectionSummary,
    )
    from valuation.compute import for_parcel

    app = create_app(demo=True, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        # Clear demo-seeded property so the fixture can pin id=1.
        from db.models import (
            Camera as _Cam, DetectionSummary as _DS, Season as _S,
            Upload as _U,
        )
        _U.query.delete()
        _Cam.query.delete()
        _DS.query.delete()
        _S.query.delete()
        Property.query.delete()
        db.session.commit()

        owner = User.query.filter_by(email="owner@basal.eco").first()

        lender = LenderClient(
            name="Acme Agricultural Credit", slug="acme",
            state="TX", contact_email="x@x", plan_tier="per_parcel",
            per_parcel_rate_usd=1500.00, active=True,
        )
        db.session.add(lender)
        db.session.flush()

        # id=1 so parcel_id derives to TX-KIM-...-00001, matching the
        # hand-curated Kimble CAD adapter snapshot.
        parcel = Property(
            id=1,
            user_id=owner.id, name="Edwards Plateau Ranch",
            county="Kimble", state="TX", acreage=2340,
            crop_type="sorghum",
            boundary_geojson=json.dumps({
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-99.57, 30.64], [-99.53, 30.64],
                    [-99.53, 30.67], [-99.57, 30.67], [-99.57, 30.64],
                ]]},
            }),
            lender_client_id=lender.id,
        )
        db.session.add(parcel)
        db.session.flush()

        s = Season(
            property_id=parcel.id, name="Fall 2025",
            start_date=date(2025, 9, 1), end_date=date(2026, 2, 28),
        )
        db.session.add(s)
        db.session.flush()
        for i, ctx in enumerate(("feeder", "water", "trail", "food_plot")):
            cam = Camera(
                property_id=parcel.id, camera_label=f"CAM-{i:02d}",
                name=f"c{i}", lat=30.65, lon=-99.55,
                placement_context=ctx, is_active=True,
            )
            db.session.add(cam)
            db.session.flush()
            db.session.add(DetectionSummary(
                season_id=s.id, camera_id=cam.id,
                species_key="white_tailed_deer",
                total_photos=200, independent_events=50,
                avg_confidence=0.92,
            ))
        db.session.commit()
        parcel_id = parcel.id

        # Pre-compute so the override endpoint has a status row to update.
        for_parcel(parcel, today=date(2026, 5, 5),
                   as_of_date=date(2025, 10, 1))

    return app, app.test_client(), parcel_id


def _override_url(parcel_id):
    return f"/lender/api/acme/parcel/{parcel_id}/valuation/override"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

# NOTE: an "unauth'd POST is rejected" test is omitted intentionally.
# In demo=True mode (which the fixture uses, because the basal app's
# auto-login depends on it), the ``before_request`` hook logs the
# demo owner in on every request — there is no unauth path to exercise
# in this fixture. The production behavior is the standard
# Flask-Login redirect from ``@login_required`` and is exercised by
# tests/test_lender_route.py (which spins up demo=False elsewhere).


def test_owner_can_set_override(app_client):
    app, client, parcel_id = app_client
    r = client.post(
        _override_url(parcel_id),
        json={"band": "low", "notes": "site visit ok"},
    )
    assert r.status_code == 200, r.data
    body = r.get_json()
    assert body["underwriter_override"] == "low"
    # cleanup
    client.post(_override_url(parcel_id), json={"clear": True})


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_invalid_band_rejected(app_client):
    _, client, parcel_id = app_client
    r = client.post(_override_url(parcel_id), json={"band": "extreme"})
    assert r.status_code == 400
    assert "band" in r.get_json()["error"]


def test_unknown_lender_returns_404(app_client):
    _, client, parcel_id = app_client
    r = client.post(
        f"/lender/api/no-such-lender/parcel/{parcel_id}/valuation/override",
        json={"band": "low"},
    )
    assert r.status_code == 404


def test_unknown_parcel_returns_404(app_client):
    _, client, _ = app_client
    r = client.post(
        "/lender/api/acme/parcel/999999/valuation/override",
        json={"band": "low"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Audit-log writes
# ---------------------------------------------------------------------------

def test_each_override_action_writes_audit_row(app_client):
    app, client, parcel_id = app_client
    from db.models import (
        ParcelValuationStatus, ValuationOverrideHistory, db,
    )

    with app.app_context():
        status = ParcelValuationStatus.query.filter_by(
            parcel_id=parcel_id,
        ).first()
        status_id = status.id
        # Wipe any audit rows from earlier tests in this module.
        ValuationOverrideHistory.query.filter_by(
            parcel_valuation_status_id=status_id,
        ).delete()
        db.session.commit()

    # Three actions: set, change, clear → expect 3 history rows.
    client.post(_override_url(parcel_id), json={"band": "moderate"})
    client.post(_override_url(parcel_id), json={"band": "elevated"})
    client.post(_override_url(parcel_id), json={"clear": True})

    with app.app_context():
        rows = (
            ValuationOverrideHistory.query
            .filter_by(parcel_valuation_status_id=status_id)
            .order_by(ValuationOverrideHistory.id.asc())
            .all()
        )
        assert len(rows) == 3
        # Sequence: None→moderate, moderate→elevated, elevated→None
        assert (rows[0].prev_band, rows[0].new_band) == (None, "moderate")
        assert (rows[1].prev_band, rows[1].new_band) == ("moderate", "elevated")
        assert (rows[2].prev_band, rows[2].new_band) == ("elevated", None)
        # set_by_user_id captured (demo auto-login user is is_owner).
        assert rows[-1].set_by_user_id is not None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_rate_limit_kicks_in_after_threshold(app_client):
    """The in-process limiter caps at 12 requests / 60s / user.
    Reset the per-user counter then issue 13 requests; the 13th
    should 429.
    """
    app, client, parcel_id = app_client
    # Reset the limiter counter directly so this test isn't dependent
    # on the previous tests' calls.
    from web.routes import lender as lender_mod
    with lender_mod._override_rate_lock:
        lender_mod._override_rate_log.clear()

    last_status = None
    statuses = []
    for _ in range(13):
        r = client.post(_override_url(parcel_id), json={"clear": True})
        statuses.append(r.status_code)
        last_status = r.status_code
    assert 429 in statuses, (
        f"expected at least one 429 in 13 requests, got {statuses}"
    )
    assert last_status == 429
