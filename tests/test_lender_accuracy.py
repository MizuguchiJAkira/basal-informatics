"""Tests for the Classifier Accuracy block on the lender parcel report.

Seeds a parcel with two ProcessingJob rows carrying hunter-filename
accuracy telemetry (one with species overlap, one without) and asserts
that /lender/<slug>/parcel/<id> renders the aggregated section with
the expected matched/missed/confused markers. Also asserts that a
sibling parcel with zero labeled uploads does NOT render the section.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime

import pytest


_TEST_DB_FILE = tempfile.NamedTemporaryFile(
    prefix="basal-acc-test-", suffix=".db", delete=False
).name
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_FILE}"
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-do-not-use-in-prod")

import sys as _sys
for _mod in list(_sys.modules):
    if (_mod == "config" or _mod.startswith("config.")
            or _mod == "db" or _mod.startswith("db.")
            or _mod.startswith("web.")):
        _sys.modules.pop(_mod, None)


@pytest.fixture(scope="module")
def app_client():
    from web.app import create_app
    from db.models import (db, User, LenderClient, Property, Season, Camera,
                           DetectionSummary, ProcessingJob)

    app = create_app(demo=True, site="basal")
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        owner = User.query.filter_by(email="owner@basal.eco").first()
        assert owner is not None
        if not owner.is_owner:
            owner.is_owner = True
            db.session.flush()

        lender = LenderClient(
            name="Farm Credit of Central Texas", slug="fcct-acc",
            state="TX", contact_email="portfolio@fcct.example.com",
            plan_tier="per_parcel", per_parcel_rate_usd=1500.00,
            active=True,
        )
        db.session.add(lender)
        db.session.flush()

        boundary = {
            "type": "Feature", "properties": {"name": "Labeled Ranch"},
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
            user_id=owner.id, name="Labeled Ranch",
            county="Brazos", state="TX", acreage=650,
            boundary_geojson=json.dumps(boundary),
            lender_client_id=lender.id, crop_type="corn",
        )
        bare_parcel = Property(
            user_id=owner.id, name="Unlabeled Ranch",
            county="Brazos", state="TX", acreage=400,
            lender_client_id=lender.id, crop_type="corn",
        )
        db.session.add_all([parcel, bare_parcel])
        db.session.flush()

        season = Season(
            property_id=parcel.id, name="Spring 2026",
            start_date=date(2026, 2, 1), end_date=date(2026, 3, 31),
        )
        bare_season = Season(
            property_id=bare_parcel.id, name="Spring 2026",
            start_date=date(2026, 2, 1), end_date=date(2026, 3, 31),
        )
        db.session.add_all([season, bare_season])
        db.session.flush()

        cam = Camera(property_id=parcel.id, camera_label="CAM-LR-01",
                     name="South fence", lat=30.595, lon=-96.505,
                     placement_context="random", is_active=True)
        bare_cam = Camera(property_id=bare_parcel.id,
                          camera_label="CAM-UR-01", name="North fence",
                          lat=30.60, lon=-96.50,
                          placement_context="random", is_active=True)
        db.session.add_all([cam, bare_cam])
        db.session.flush()

        db.session.add(DetectionSummary(
            season_id=season.id, camera_id=cam.id,
            species_key="feral_hog",
            total_photos=80, independent_events=20, avg_confidence=0.9,
            first_seen=datetime(2026, 2, 3, 22),
            last_seen=datetime(2026, 3, 30, 5),
            peak_hour=22,
            hourly_distribution=json.dumps([0]*20 + [5, 8, 6, 4]),
        ))

        # Two ProcessingJobs with accuracy reports — overlapping
        # species so the aggregation branch is exercised.
        job1_report = {
            "n_total": 72, "n_labeled": 60, "n_matched": 52,
            "n_missed": 4, "n_confused": 4,
            "per_species": {
                "feral_hog": {"labeled": 40, "matched": 36, "missed": 2,
                              "confused_as": {"white_tailed_deer": 2}},
                "white_tailed_deer": {"labeled": 20, "matched": 16,
                                      "missed": 2,
                                      "confused_as": {"feral_hog": 2}},
            },
        }
        job2_report = {
            "n_total": 50, "n_labeled": 47, "n_matched": 42,
            "n_missed": 4, "n_confused": 1,
            "per_species": {
                "feral_hog": {"labeled": 30, "matched": 27, "missed": 2,
                              "confused_as": {"white_tailed_deer": 1}},
                "white_tailed_deer": {"labeled": 17, "matched": 15,
                                      "missed": 2, "confused_as": {}},
            },
        }
        db.session.add_all([
            ProcessingJob(
                job_id="acc00001", property_id=parcel.id,
                property_name=parcel.name, status="complete",
                accuracy_report_json=json.dumps(job1_report),
                submitted_at=datetime(2026, 4, 1, 10, 0),
                completed_at=datetime(2026, 4, 1, 10, 30),
            ),
            ProcessingJob(
                job_id="acc00002", property_id=parcel.id,
                property_name=parcel.name, status="complete",
                accuracy_report_json=json.dumps(job2_report),
                submitted_at=datetime(2026, 4, 10, 10, 0),
                completed_at=datetime(2026, 4, 10, 10, 30),
            ),
            # Unrelated non-labeled job — should be ignored.
            ProcessingJob(
                job_id="acc00003", property_id=parcel.id,
                property_name=parcel.name, status="complete",
                accuracy_report_json=None,
                submitted_at=datetime(2026, 4, 12, 10, 0),
                completed_at=datetime(2026, 4, 12, 10, 30),
            ),
        ])

        db.session.commit()
        parcel_id = parcel.id
        bare_parcel_id = bare_parcel.id

    client = app.test_client()
    yield app, client, parcel_id, bare_parcel_id


def test_accuracy_section_aggregates_across_jobs(app_client):
    _, client, pid, _ = app_client
    resp = client.get(f"/lender/fcct-acc/parcel/{pid}")
    assert resp.status_code == 200, resp.data[:400]
    body = resp.data.decode("utf-8", errors="replace")

    # Headline markers
    assert "Classifier accuracy" in body
    # 52 + 42 = 94 matched, 60 + 47 = 107 labeled, 94/107 = 87.85%
    assert "94 of 107" in body
    # Percentage rounds to 88.
    assert "88%" in body

    # Per-row markers
    assert "Matched" in body
    assert "Missed" in body
    assert "Confused" in body
    # Species rows: summed labeled counts (hog 70, deer 37)
    assert "Feral Hog" in body
    assert "White Tailed Deer" in body
    # confused_as merging: hog labeled, deer predicted, total 3
    assert "white tailed deer" in body  # in the confused-as cell
    assert "\u00d73" in body or "×3" in body

    # Aggregation-across-jobs note fires when n_jobs > 1.
    assert "Aggregated across 2 labeled uploads" in body


def test_accuracy_section_omitted_when_no_labeled_jobs(app_client):
    _, client, _, bare_pid = app_client
    resp = client.get(f"/lender/fcct-acc/parcel/{bare_pid}")
    assert resp.status_code == 200, resp.data[:400]
    body = resp.data.decode("utf-8", errors="replace")
    assert "Classifier accuracy" not in body
