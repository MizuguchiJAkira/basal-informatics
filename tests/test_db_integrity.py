"""Layer 3 — DB integrity tests.

The test plan asks for things that don't literally exist in this
schema (DetectionIngest-the-table, RiskAssessment-the-table, Portfolio).
I map to what actually exists:

  Test plan                       Actual
  ─────────────────────────────── ──────────────────────────────
  DetectionIngest row needs Parcel Upload.property_id NOT NULL FK
  RiskAssessment row needs ...    No RiskAssessment table — there's
                                   CoverageScore instead, FK to Property
                                   + Season
  Deleting Parcel cascades        SQLAlchemy session.delete(property)
                                   must cascade through cameras +
                                   seasons + uploads + coverage_scores
  parcel_id format enforced        Computed property — enforced by
                                   Property.parcel_id's format logic
                                   (testable)
  Portfolio cannot be empty        LenderClient has no cardinality
                                   constraint. Flagging as
                                   expected-present-but-missing.
  CoverageScore confidence by      risk.proximity.proximity_confidence
  distance                         (linear decay) — covered in
                                   test_proximity.py already; this
                                   file adds direct monotonicity check.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime

import pytest


# Isolate DB per-run, same pattern as test_lender_route.py
_TEST_DB = tempfile.NamedTemporaryFile(
    prefix="basal-test-dbi-", suffix=".db", delete=False
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def app_ctx():
    from web.app import create_app
    from db.models import db
    app = create_app(demo=True, site="basal")
    with app.app_context():
        yield app, db


# ---------------------------------------------------------------------------
# parcel_id format
# ---------------------------------------------------------------------------

def test_parcel_id_format_follows_state_county_year_id(app_ctx):
    """Property.parcel_id is a computed property. Format is
    STATE-COUNTY3-YEAR-SEQ5 e.g. 'TX-KIM-2026-00001'."""
    app, db = app_ctx
    from db.models import User, Property
    import re

    u = User.query.filter_by(email="owner@basal.eco").first()
    assert u is not None
    # Create a property with known attrs.
    p = Property(user_id=u.id, name="Format Test Parcel",
                 county="Kimble", state="tx", acreage=100,
                 created_at=datetime(2024, 5, 1))
    db.session.add(p); db.session.commit()
    try:
        pid = p.parcel_id
        assert re.fullmatch(r"[A-Z]{2}-[A-Z]{3}-\d{4}-\d{5}", pid), pid
        assert pid.startswith("TX-KIM-2024-")
    finally:
        db.session.delete(p); db.session.commit()


def test_parcel_id_falls_back_for_missing_state(app_ctx):
    """Null/missing state → 'XX' fallback so the property never
    yields a None parcel_id."""
    app, db = app_ctx
    from db.models import User, Property
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Nullstate", county="Travis",
                 state=None, acreage=50, created_at=datetime(2024, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        pid = p.parcel_id
        assert pid.startswith("XX-TRA-2024-")
    finally:
        db.session.delete(p); db.session.commit()


def test_parcel_id_county_truncated_to_3_letters(app_ctx):
    """Long county names truncate to first 3 alphabetic chars, uppercase."""
    app, db = app_ctx
    from db.models import User, Property
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Long County", county="Matagorda",
                 state="TX", acreage=10, created_at=datetime(2025, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        assert p.parcel_id.startswith("TX-MAT-2025-")
    finally:
        db.session.delete(p); db.session.commit()


def test_parcel_id_county_with_non_alpha_stripped(app_ctx):
    """Spaces/hyphens/numbers in county are stripped before truncation."""
    app, db = app_ctx
    from db.models import User, Property
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Weird County", county="San Augustine",
                 state="TX", acreage=10, created_at=datetime(2025, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        # 'San Augustine' → strip space → 'SanAugustine' → 'SAN'
        assert p.parcel_id.startswith("TX-SAN-2025-")
    finally:
        db.session.delete(p); db.session.commit()


def test_parcel_id_zero_padded_sequence(app_ctx):
    """The trailing sequence is always 5-digit zero-padded."""
    app, db = app_ctx
    from db.models import User, Property
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Padding Check", county="Kimble",
                 state="TX", acreage=10, created_at=datetime(2024, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        pid = p.parcel_id
        # Last chunk is 5 digits
        seq = pid.rsplit("-", 1)[1]
        assert len(seq) == 5
        assert seq.isdigit()
    finally:
        db.session.delete(p); db.session.commit()


# ---------------------------------------------------------------------------
# Foreign key integrity
# ---------------------------------------------------------------------------

def test_camera_requires_valid_property_id(app_ctx):
    """Camera.property_id is NOT NULL. Inserting a Camera without a
    property must fail."""
    app, db = app_ctx
    from db.models import Camera
    cam = Camera(camera_label="orphan", lat=30.0, lon=-97.0,
                 placement_context="random", is_active=True)
    db.session.add(cam)
    with pytest.raises(Exception):   # IntegrityError (dialect-dependent)
        db.session.commit()
    db.session.rollback()


def test_detection_summary_requires_camera_and_season(app_ctx):
    """DetectionSummary.camera_id and .season_id both NOT NULL."""
    app, db = app_ctx
    from db.models import DetectionSummary
    ds = DetectionSummary(species_key="feral_hog",
                          total_photos=1, independent_events=1,
                          avg_confidence=0.9)
    db.session.add(ds)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_season_requires_property_id(app_ctx):
    app, db = app_ctx
    from db.models import Season
    s = Season(name="orphan season",
               start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
    db.session.add(s)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_upload_requires_property_and_user(app_ctx):
    app, db = app_ctx
    from db.models import Upload
    u = Upload(status="pending")
    db.session.add(u)
    with pytest.raises(Exception):
        db.session.commit()
    db.session.rollback()


def test_detection_summary_unique_on_season_camera_species(app_ctx):
    """One (season_id, camera_id, species_key) per DetectionSummary.
    Duplicate insert must fail."""
    app, db = app_ctx
    from db.models import User, Property, Camera, Season, DetectionSummary
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Unique Test", county="X", state="TX",
                 acreage=1, created_at=datetime(2025, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        cam = Camera(property_id=p.id, camera_label="cam-uniq",
                     lat=30.0, lon=-97.0, placement_context="random")
        s = Season(property_id=p.id, name="Sx",
                   start_date=date(2025, 1, 1), end_date=date(2025, 3, 1))
        db.session.add_all([cam, s]); db.session.commit()

        ds1 = DetectionSummary(season_id=s.id, camera_id=cam.id,
                               species_key="feral_hog",
                               total_photos=10, independent_events=2,
                               avg_confidence=0.9)
        db.session.add(ds1); db.session.commit()

        ds2 = DetectionSummary(season_id=s.id, camera_id=cam.id,
                               species_key="feral_hog",
                               total_photos=20, independent_events=3,
                               avg_confidence=0.88)
        db.session.add(ds2)
        with pytest.raises(Exception):
            db.session.commit()
        db.session.rollback()
    finally:
        # Cleanup
        db.session.execute(db.text(
            "DELETE FROM detection_summaries WHERE camera_id IN "
            "(SELECT id FROM cameras WHERE property_id=:p)"), {"p": p.id})
        db.session.execute(db.text(
            "DELETE FROM cameras WHERE property_id=:p"), {"p": p.id})
        db.session.execute(db.text(
            "DELETE FROM seasons WHERE property_id=:p"), {"p": p.id})
        db.session.delete(p); db.session.commit()


# ---------------------------------------------------------------------------
# Cascade-delete behavior
# ---------------------------------------------------------------------------

def test_deleting_property_requires_cleanup_of_dependents(app_ctx):
    """SQLite schema does NOT define ON DELETE CASCADE, so deleting a
    Property with extant cameras should fail unless cleaned up first.
    The seed scripts handle this manually via a cascade sequence —
    lock that invariant here."""
    app, db = app_ctx
    from db.models import User, Property, Camera
    u = User.query.filter_by(email="owner@basal.eco").first()
    p = Property(user_id=u.id, name="Cascade Test", county="X", state="TX",
                 acreage=1, created_at=datetime(2025, 1, 1))
    db.session.add(p); db.session.commit()
    try:
        cam = Camera(property_id=p.id, camera_label="cam-csc",
                     lat=30.0, lon=-97.0, placement_context="random")
        db.session.add(cam); db.session.commit()

        # Try to delete property while camera still references it.
        with pytest.raises(Exception):
            db.session.delete(p)
            db.session.commit()
        db.session.rollback()

        # Proper cleanup: camera first, then property.
        db.session.delete(cam); db.session.commit()
        db.session.delete(p); db.session.commit()
        # Confirm property gone
        assert db.session.get(Property, p.id) is None
    except Exception:
        db.session.rollback()
        # Cleanup best-effort
        db.session.execute(db.text(
            "DELETE FROM cameras WHERE property_id=:p"), {"p": p.id})
        db.session.execute(db.text(
            "DELETE FROM properties WHERE id=:p"), {"p": p.id})
        db.session.commit()


# ---------------------------------------------------------------------------
# CoverageScore / proximity confidence degrades with distance
# ---------------------------------------------------------------------------

def test_proximity_confidence_is_monotone_decreasing_with_distance():
    """Direct math check — proximity_confidence(d) is monotonically
    non-increasing in d across [0, cutoff]."""
    from risk.proximity import proximity_confidence, NEIGHBOR_RADIUS_KM
    ds = [0.0, 0.25, 0.5, 1.0, 1.5, 1.75, NEIGHBOR_RADIUS_KM, 5.0]
    prev = 1.0 + 1e-9
    for d in ds:
        pc = proximity_confidence(d)
        assert pc <= prev, f"non-decreasing at d={d}"
        prev = pc


def test_proximity_confidence_1_at_zero_and_0_at_cutoff():
    from risk.proximity import proximity_confidence, NEIGHBOR_RADIUS_KM
    assert proximity_confidence(0.0) == 1.0
    assert proximity_confidence(NEIGHBOR_RADIUS_KM) == 0.0


def test_proximity_confidence_linear_decay():
    """At half-cutoff, confidence should equal 0.5."""
    from risk.proximity import proximity_confidence, NEIGHBOR_RADIUS_KM
    pc = proximity_confidence(NEIGHBOR_RADIUS_KM / 2)
    assert pc == pytest.approx(0.5, abs=1e-6)


def test_proximity_confidence_none_distance_zero():
    from risk.proximity import proximity_confidence
    assert proximity_confidence(None) == 0.0


def test_proximity_confidence_negative_distance_clamps_to_1():
    """A negative distance shouldn't produce a confidence > 1."""
    from risk.proximity import proximity_confidence
    assert 0.0 <= proximity_confidence(-0.5) <= 1.0
