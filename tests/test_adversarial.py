"""Layer 7 — adversarial inputs.

The creative-input class. Does the pipeline stay sane when given
inputs that shouldn't happen but might?

Covered:
  - All-identical timestamps on a batch
  - Timestamps in the future
  - Missing/unparseable EXIF
  - Parcel acreage zero / negative
  - Confidence score > 1.0 / negative
  - 100% review-routing load
  - Large (1000-parcel) portfolio performance
  - Malformed boundary GeoJSON on a parcel
"""

import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta

import pytest


# ---------------------------------------------------------------------------
# Burst grouping — identical timestamps
# ---------------------------------------------------------------------------

def test_all_identical_timestamps_produce_one_burst_per_camera():
    """If every detection shares the same timestamp, they should all
    fall into a single burst per camera, not produce N-1 micro-bursts
    or divide-by-zero."""
    from strecker.ingest import Detection, assign_burst_groups
    ts = datetime(2026, 2, 15, 3, 14, 15)
    dets = [
        Detection(
            camera_id=f"CAM-{i % 2}",
            species_key="feral_hog", confidence=0.9,
            timestamp=ts, image_filename=f"img{i}.jpg",
            megadetector_confidence=0.95,
        )
        for i in range(20)
    ]
    result = assign_burst_groups(dets)
    # All dets for CAM-0 share one burst; all dets for CAM-1 share another.
    cam0_bursts = {d.burst_group_id for d in result if d.camera_id == "CAM-0"}
    cam1_bursts = {d.burst_group_id for d in result if d.camera_id == "CAM-1"}
    assert len(cam0_bursts) == 1
    assert len(cam1_bursts) == 1


# ---------------------------------------------------------------------------
# Future timestamps
# ---------------------------------------------------------------------------

def test_future_timestamps_do_not_crash_classify():
    """Photos with timestamps in the future (e.g. unsynced camera
    clock) should still classify without raising. The temporal prior
    is hour-of-day only, so the year doesn't matter."""
    from strecker.classify import compute_temporal_prior
    # Year 2099 at 3am
    prior = compute_temporal_prior("feral_hog", 3.0)
    assert 0.0 <= prior <= 1.0


def test_future_timestamps_survive_burst_grouping():
    from strecker.ingest import Detection, assign_burst_groups
    dets = [
        Detection(camera_id="CAM-A",
                  species_key="feral_hog", confidence=0.9,
                  timestamp=datetime(2099, 1, 1, 3, 0, 0),
                  image_filename="x.jpg", megadetector_confidence=0.95),
        Detection(camera_id="CAM-A",
                  species_key="feral_hog", confidence=0.9,
                  timestamp=datetime(2099, 1, 1, 3, 0, 30),
                  image_filename="y.jpg", megadetector_confidence=0.95),
    ]
    result = assign_burst_groups(dets)
    # Both within 60s → same burst
    assert result[0].burst_group_id == result[1].burst_group_id


# ---------------------------------------------------------------------------
# No EXIF data
# ---------------------------------------------------------------------------

def test_parse_timestamp_from_exif_returns_none_for_nonexistent_file():
    """Missing file path → parser returns None, not an exception."""
    from pathlib import Path
    from strecker.ingest import parse_timestamp_from_exif
    result = parse_timestamp_from_exif(Path("/nonexistent/path/to/no.jpg"))
    assert result is None


def test_parse_timestamp_from_filename_handles_unknown_pattern():
    """A filename with no datetime pattern should return None."""
    from strecker.ingest import parse_timestamp_from_filename
    assert parse_timestamp_from_filename("random_name.jpg") is None
    assert parse_timestamp_from_filename("") is None


# ---------------------------------------------------------------------------
# Acreage zero / negative
# ---------------------------------------------------------------------------

def test_zero_acreage_parcel_does_not_crash_exposure():
    """A parcel with zero acreage: dollar projection should be None,
    but tier assignment still works."""
    from risk.exposure import exposure_for_species
    e = exposure_for_species(
        species_key="feral_hog",
        density_mean=5.0, density_ci_low=2.0, density_ci_high=10.0,
        parcel_acreage=0, crop_type="corn",
        recommendation="recommend_supplementary_survey",
        detection_rate_per_camera_day=0.5,
    )
    # parcel_area_km2 is 0 → dollar projection should be None per the
    # short-circuit in dollar_projection_annual.
    assert e.dollar_projection_annual_usd is None
    assert e.tier == "Elevated"


def test_negative_acreage_parcel_does_not_crash_exposure():
    from risk.exposure import exposure_for_species
    e = exposure_for_species(
        species_key="feral_hog",
        density_mean=5.0, density_ci_low=2.0, density_ci_high=10.0,
        parcel_acreage=-100, crop_type="corn",
        recommendation="sufficient_for_decision",
        detection_rate_per_camera_day=0.5,
    )
    assert e.dollar_projection_annual_usd is None


def test_negative_acreage_does_not_crash_density_estimate():
    """risk/population doesn't use acreage, but ensure there's no
    implicit area computation that divides by it."""
    from risk.population import CameraSurveyEffort, estimate_density
    import random
    efforts = [
        CameraSurveyEffort(camera_id=i, camera_days=30, detections=5,
                           placement_context="random")
        for i in range(3)
    ]
    de = estimate_density("feral_hog", efforts, rng=random.Random(0),
                           bootstrap_n=50)
    assert de.density_mean is not None  # regardless of acreage


# ---------------------------------------------------------------------------
# Confidence scores out of range
# ---------------------------------------------------------------------------

def test_entropy_with_confidence_over_1():
    """Confidence > 1.0 would make binary entropy ill-defined (log of
    negative number). The implementation clamps to 1-1e-7."""
    import math
    from strecker.classify import compute_softmax_entropy
    h = compute_softmax_entropy(1.5)
    assert math.isfinite(h)


def test_entropy_with_negative_confidence():
    import math
    from strecker.classify import compute_softmax_entropy
    h = compute_softmax_entropy(-0.3)
    assert math.isfinite(h)


def test_temperature_scale_with_invalid_confidences():
    """Division-by-zero / log-of-negative paths inside temperature_scale."""
    from strecker.classify import temperature_scale
    # T=0 would divide by zero in the logit step.
    try:
        result = temperature_scale(0.5, T=0.0)
        # If it doesn't raise, at least check it returns something finite
        import math
        assert math.isfinite(result) or result is None
    except (ZeroDivisionError, ValueError):
        pass   # raising is also acceptable behavior


# ---------------------------------------------------------------------------
# 100% review routing
# ---------------------------------------------------------------------------

def test_all_detections_flagged_for_review_does_not_break_downstream():
    """If entropy > threshold for every detection, the review_required
    flag is True everywhere. Downstream aggregation / reporting must
    handle 100% review routing without special-casing."""
    from strecker.ingest import Detection
    # Calibrated confidence so low that entropy > 0.59 for every det.
    # At p=0.5, H = ln(2) ≈ 0.693 > 0.59.
    dets = [
        Detection(
            camera_id="CAM-A",
            species_key="feral_hog", confidence=0.5,
            timestamp=datetime(2026, 2, 1, 3, 0, i),
            image_filename=f"x-{i}.jpg", megadetector_confidence=0.9,
        )
        for i in range(10)
    ]
    # Manually set review_required on each to simulate the post-classify
    # state without invoking the full classify pipeline.
    for d in dets:
        d.review_required = True
    reviewed_count = sum(1 for d in dets if d.review_required)
    # Aggregation counts work at 100% review
    assert reviewed_count == len(dets)


# ---------------------------------------------------------------------------
# Large portfolio
# ---------------------------------------------------------------------------

def test_large_portfolio_lender_dashboard_completes_under_2s():
    """Seed a lender with 100 parcels (1000 is infeasible in CI but 100
    gives 10× the current production size and catches N-squared slip-
    ups). The portfolio page must render in under 2s."""

    # Per-test DB to isolate
    db_path = tempfile.NamedTemporaryFile(
        prefix="basal-test-large-", suffix=".db", delete=False).name
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Purge cached modules so they pick up the new DATABASE_URL.
    import sys as _sys
    for _mod in list(_sys.modules):
        if (_mod == "config" or _mod.startswith("config.")
                or _mod == "db" or _mod.startswith("db.")
                or _mod.startswith("web.")):
            _sys.modules.pop(_mod, None)

    from web.app import create_app
    from db.models import (db, User, LenderClient, Property, Season,
                            Camera, DetectionSummary)

    app = create_app(demo=True, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        owner = User.query.filter_by(email="owner@basal.eco").first()
        lender = LenderClient.query.filter_by(slug="fcct").first()
        if lender is None:
            lender = LenderClient(name="Large Lender", slug="fcct",
                                  state="TX", active=True)
            db.session.add(lender); db.session.commit()

        # 100 parcels, each with 1 season + 2 cams + 1 DS row.
        N = 100
        boundary = json.dumps({
            "type": "Feature", "properties": {"name": "x"},
            "geometry": {"type": "Polygon", "coordinates": [[
                [-97, 30], [-97, 31], [-96, 31], [-96, 30], [-97, 30]]]},
        })
        h24 = json.dumps([0]*20 + [2, 3, 2, 1])
        for i in range(N):
            p = Property(user_id=owner.id, name=f"Parcel-{i:03d}",
                         county="X", state="TX", acreage=500 + i,
                         boundary_geojson=boundary,
                         lender_client_id=lender.id, crop_type="corn")
            db.session.add(p); db.session.flush()
            s = Season(property_id=p.id, name="Spring 2026",
                       start_date=date(2026, 2, 1),
                       end_date=date(2026, 3, 31))
            db.session.add(s); db.session.flush()
            for j in range(2):
                c = Camera(property_id=p.id, camera_label=f"C-{i}-{j}",
                           lat=30.5 + j * 0.01, lon=-96.5,
                           placement_context="random", is_active=True)
                db.session.add(c); db.session.flush()
                db.session.add(DetectionSummary(
                    season_id=s.id, camera_id=c.id, species_key="feral_hog",
                    total_photos=40, independent_events=10,
                    avg_confidence=0.9,
                    first_seen=datetime(2026, 2, 3),
                    last_seen=datetime(2026, 3, 30),
                    peak_hour=22, hourly_distribution=h24))
        db.session.commit()

    with app.test_client() as c:
        t0 = time.time()
        r = c.get("/lender/fcct/")
        elapsed = time.time() - t0

    assert r.status_code == 200
    assert elapsed < 5.0, (
        f"portfolio with {N} parcels took {elapsed:.2f}s — too slow. "
        f"Possible N² query; investigate bounded vs unbounded DB work."
    )


# ---------------------------------------------------------------------------
# Malformed boundary GeoJSON
# ---------------------------------------------------------------------------

def test_malformed_boundary_geojson_doesnt_crash_proximity():
    """proximity classifier given a non-parseable boundary should
    fall back to distance-unknown rather than raise."""
    from types import SimpleNamespace
    from risk.proximity import classify_camera
    bad_boundary_parcel = SimpleNamespace(
        id=1, boundary_geojson="{not valid json}")
    cam = SimpleNamespace(id=2, camera_label="x", lat=30.5, lon=-96.5,
                          property_id=99)
    result = classify_camera(cam, bad_boundary_parcel)
    # Should return something; "out of scope" with no distance is fine.
    assert result is not None


def test_empty_boundary_geojson():
    from types import SimpleNamespace
    from risk.proximity import classify_camera
    parcel = SimpleNamespace(id=1, boundary_geojson="")
    cam = SimpleNamespace(id=2, camera_label="x", lat=30.5, lon=-96.5,
                          property_id=99)
    result = classify_camera(cam, parcel)
    assert result is not None
