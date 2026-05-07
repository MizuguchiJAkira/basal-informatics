"""Integration tests for valuation/compute.py.

Verifies the orchestrator threads CAD adapter → scoring → exposure →
remediation → DB persistence correctly, and that the JSON contract
shape is stable. Uses a fresh in-memory SQLite so the live demo DB
isn't touched.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date

import pytest


# Fresh per-run SQLite. Same pattern as test_lender_route.py.
_TEST_DB_FILE = tempfile.NamedTemporaryFile(
    prefix="basal-test-compute-", suffix=".db", delete=False,
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
def app_ctx():
    """Build an app and seed the three demo parcels we have CAD
    adapters for. Yields the app within an active app context."""
    # Re-set env + evict modules so this test runs in isolation even
    # when pytest collects test_valuation_api.py (or any other test
    # that fights for DATABASE_URL) in the same session.
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

    app = create_app(demo=True, site="basal")
    with app.app_context():
        # ``create_app(demo=True)`` auto-seeds the Strecker demo
        # parcel at id=1; clear it so the test fixture can pin IDs
        # to match the hand-curated CAD adapters' production keys.
        from db.models import (
            Camera as _Cam, DetectionSummary as _DS, Season as _S,
        )
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

        # IDs pinned to the production-demo values so the
        # hand-curated CAD adapters' parcel_id keys match. The
        # adapters look up by the @property-derived
        # ``TX-{state}-{county3}-{year}-{id:05d}``, so id 1, 2, 6
        # produce TX-KIM-...-00001, TX-BRA-...-00002, TX-LLA-...-00006.
        ep = Property(
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
        db.session.add(ep)

        # Riverbend (Brazos)
        rb = Property(
            id=2,
            user_id=owner.id, name="Riverbend Farm",
            county="Brazos", state="TX", acreage=650,
            crop_type="corn",
            boundary_geojson=json.dumps({
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-96.52, 30.57], [-96.46, 30.57],
                    [-96.46, 30.62], [-96.52, 30.62], [-96.52, 30.57],
                ]]},
            }),
            lender_client_id=lender.id,
        )
        db.session.add(rb)

        # Llano Highlands (Llano) — id=6 matches the live demo.
        lh = Property(
            id=6,
            user_id=owner.id, name="Llano Highlands",
            county="Llano", state="TX", acreage=1850,
            crop_type="wildlife",
            boundary_geojson=json.dumps({
                "type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[
                    [-98.77, 30.77], [-98.72, 30.77],
                    [-98.72, 30.81], [-98.77, 30.81], [-98.77, 30.77],
                ]]},
            }),
            lender_client_id=lender.id,
        )
        db.session.add(lh)
        db.session.flush()

        # Each parcel needs at least one season + cameras + events for
        # the remediation evaluator to read.
        for parcel, contexts in [
            (ep, ["feeder", "trail", "water", "food_plot", "feeder", "trail"]),
            (rb, ["trail", "trail", "water", "feeder", "trail"]),
            (lh, ["water", "feeder", "trail", "trail", "food_plot"]),
        ]:
            s = Season(
                property_id=parcel.id, name="Fall 2025",
                start_date=date(2025, 9, 1), end_date=date(2026, 2, 28),
            )
            db.session.add(s)
            db.session.flush()
            for i, ctx in enumerate(contexts):
                cam = Camera(
                    property_id=parcel.id,
                    camera_label=f"CAM-{parcel.id}-{i:02d}",
                    name=f"Cam {i}", lat=30.5, lon=-99.0,
                    placement_context=ctx, is_active=True,
                    installed_date=date(2025, 9, 1),
                )
                db.session.add(cam)
                db.session.flush()
                # Generous events to clear the census threshold.
                db.session.add(DetectionSummary(
                    season_id=s.id, camera_id=cam.id,
                    species_key="white_tailed_deer",
                    total_photos=200, independent_events=50,
                    avg_confidence=0.92,
                ))

        db.session.commit()
        yield app


# ---------------------------------------------------------------------------
# Adapter mapping
# ---------------------------------------------------------------------------

def test_adapter_resolves_for_known_counties(app_ctx):
    from db.models import Property
    from valuation.compute import _county_to_adapter_slug
    with app_ctx.app_context():
        ep = Property.query.filter_by(name="Edwards Plateau Ranch").first()
        rb = Property.query.filter_by(name="Riverbend Farm").first()
        lh = Property.query.filter_by(name="Llano Highlands").first()
        assert _county_to_adapter_slug(ep.county) == "kimble_tx"
        assert _county_to_adapter_slug(rb.county) == "brazos_tx"
        assert _county_to_adapter_slug(lh.county) == "llano_tx"


def test_adapter_returns_none_for_no_county(app_ctx):
    from valuation.compute import _county_to_adapter_slug
    assert _county_to_adapter_slug(None) is None
    assert _county_to_adapter_slug("") is None


# ---------------------------------------------------------------------------
# End-to-end orchestrator
# ---------------------------------------------------------------------------

def test_compute_returns_none_for_unmapped_county(app_ctx):
    """Legacy parcel guarantee: parcels without a registered CAD
    adapter return None, the report skips Stage 7 cleanly."""
    from db.models import Property, User, db
    from valuation.compute import for_parcel

    with app_ctx.app_context():
        owner = User.query.filter_by(email="owner@basal.eco").first()
        # County we deliberately don't have an adapter for.
        unmapped = Property(
            user_id=owner.id, name="Unmapped County Parcel",
            county="Hudspeth", state="TX", acreage=500,
        )
        db.session.add(unmapped)
        db.session.flush()
        result = for_parcel(unmapped, today=date(2026, 5, 5),
                            as_of_date=date(2025, 10, 1))
        assert result is None


def test_compute_persists_and_returns_contract(app_ctx):
    from db.models import (
        Property, ParcelValuationStatus, ValuationRiskFactor,
    )
    from valuation.compute import for_parcel

    with app_ctx.app_context():
        ep = Property.query.filter_by(name="Edwards Plateau Ranch").first()
        result = for_parcel(ep, today=date(2026, 5, 5),
                            as_of_date=date(2025, 10, 1))

        # Contract shape — every key the report layer reads.
        assert set(result.keys()) >= {
            "parcel_id", "current_valuation", "risk_score",
            "exposure_if_lost", "remediation", "human_feedback",
        }
        assert result["risk_score"]["band"] in (
            "low", "moderate", "elevated", "high"
        )
        # Drivers are present and decomposable.
        assert len(result["risk_score"]["drivers"]) >= 1
        for d in result["risk_score"]["drivers"]:
            assert {"factor", "weight", "triggered", "evidence"} <= set(d.keys())

        # Persisted: status row + driver rows.
        status = ParcelValuationStatus.query.filter_by(
            parcel_id=ep.id,
        ).first()
        assert status is not None
        assert status.risk_band == result["risk_score"]["band"]
        n_factors = ValuationRiskFactor.query.filter_by(
            parcel_valuation_status_id=status.id,
        ).count()
        assert n_factors >= 1


def test_compute_idempotent_on_repeat(app_ctx):
    """Calling for_parcel twice on the same parcel does NOT create
    duplicate cad_snapshot or status rows."""
    from db.models import (
        Property, ParcelValuationStatus, CADSnapshot, ValuationRiskFactor,
    )
    from valuation.compute import for_parcel

    with app_ctx.app_context():
        rb = Property.query.filter_by(name="Riverbend Farm").first()
        for_parcel(rb, today=date(2026, 5, 5), as_of_date=date(2025, 10, 1))
        statuses_before = ParcelValuationStatus.query.filter_by(
            parcel_id=rb.id).count()
        snapshots_before = CADSnapshot.query.filter_by(
            parcel_id=rb.id, as_of_date=date(2025, 10, 1)).count()

        for_parcel(rb, today=date(2026, 5, 5), as_of_date=date(2025, 10, 1))
        for_parcel(rb, today=date(2026, 5, 5), as_of_date=date(2025, 10, 1))

        statuses_after = ParcelValuationStatus.query.filter_by(
            parcel_id=rb.id).count()
        snapshots_after = CADSnapshot.query.filter_by(
            parcel_id=rb.id, as_of_date=date(2025, 10, 1)).count()
        assert statuses_after == statuses_before == 1
        assert snapshots_after == snapshots_before == 1

        # Driver rows are replaced wholesale — count stable.
        status = ParcelValuationStatus.query.filter_by(parcel_id=rb.id).first()
        n = ValuationRiskFactor.query.filter_by(
            parcel_valuation_status_id=status.id).count()
        assert n == 5  # the rubric has 5 factors


def test_three_demo_parcels_yield_distinct_bands(app_ctx):
    """Acceptance criterion: at least three distinct bands across the
    demo portfolio under the v1 rubric + drought snapshot."""
    from db.models import Property
    from valuation.compute import for_parcel
    today = date(2026, 5, 5)

    with app_ctx.app_context():
        bands = set()
        for name in ("Edwards Plateau Ranch", "Riverbend Farm",
                     "Llano Highlands"):
            p = Property.query.filter_by(name=name).first()
            r = for_parcel(p, today=today, as_of_date=date(2025, 10, 1))
            assert r is not None
            bands.add(r["risk_score"]["band"])
        assert len(bands) == 3, f"expected 3 distinct bands, got {bands}"


def test_underwriter_override_surfaces_in_contract(app_ctx):
    """A status row's underwriter_override should surface as
    risk_score.effective_band when present, otherwise risk_score.band."""
    from db.models import db, Property, ParcelValuationStatus
    from valuation.compute import for_parcel

    with app_ctx.app_context():
        ep = Property.query.filter_by(name="Edwards Plateau Ranch").first()
        for_parcel(ep, today=date(2026, 5, 5), as_of_date=date(2025, 10, 1))

        status = ParcelValuationStatus.query.filter_by(parcel_id=ep.id).first()
        status.underwriter_override = "low"
        db.session.commit()

        r = for_parcel(ep, today=date(2026, 5, 5),
                       as_of_date=date(2025, 10, 1))
        assert r["risk_score"]["effective_band"] == "low"
        # The computed band remains visible — both for transparency on
        # the report AND so an audit reproduces "what the rubric said
        # before the override."
        assert r["risk_score"]["band"] != "low"
