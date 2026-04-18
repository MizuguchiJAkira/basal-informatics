"""Layer 2 — full-pipeline integration tests.

Two pipelines coexist in this codebase:

  (A) Lender-side (production): DetectionSummary (SQL) →
      estimate_density (REM + IPW) → exposure_for_species →
      HTML/JSON lender report.
      Already covered in test_lender_route.py; this file extends with
      the edge cases specified in the test plan (zero detections,
      single camera, 100% detection frequency, identical placement).

  (B) Old-path orchestration (demo-mode): ingest → classify →
      fingerprint → delineate → corridors → confidence → gaps → bias →
      inventory → damage → regulatory → synthesis.
      Exercised via risk.synthesis.run_risk_assessment(demo=True).
      Verified runs end-to-end and all documented output fields are
      present + correctly typed.
"""

from __future__ import annotations

import random

import pytest

from risk.population import CameraSurveyEffort, estimate_density
from risk.exposure import exposure_for_species


# ═══════════════════════════════════════════════════════════════════════════
# (A) Lender-side pipeline edge cases
# ═══════════════════════════════════════════════════════════════════════════

def _run_parcel(efforts, species="feral_hog", acreage=650, crop="corn"):
    """Helper: run estimate_density → exposure_for_species."""
    de = estimate_density(species, efforts, rng=random.Random(42),
                           bootstrap_n=200)
    e = exposure_for_species(
        species_key=species,
        density_mean=de.density_mean,
        density_ci_low=de.density_ci_low,
        density_ci_high=de.density_ci_high,
        parcel_acreage=acreage, crop_type=crop,
        recommendation=de.recommendation,
        detection_rate_per_camera_day=de.detection_rate,
        detection_rate_adjusted_per_camera_day=de.detection_rate_adjusted,
    )
    return de, e


def test_lender_zero_detections_graceful():
    """A parcel with cameras but zero hog events should return
    tier Low (or Unknown), no density, recommendation=insufficient."""
    efforts = [
        CameraSurveyEffort(camera_id=i, camera_days=58,
                           detections=0, placement_context="random")
        for i in range(3)
    ]
    de, e = _run_parcel(efforts)
    assert de.detection_rate == 0.0
    # Density is computable at rate 0 (D=0) but the recommendation should flag
    # insufficient data below the 20-event minimum.
    assert de.total_detections == 0
    assert de.recommendation == "insufficient_data"
    # Exposure: zero density → tier Low, score 0
    assert e.tier == "Low"
    assert (e.score_0_100 or 0) == 0


def test_lender_single_camera_does_not_crash():
    """Single-camera deployments are below decision-grade but must
    still produce a finite density + an explanatory caveat."""
    efforts = [CameraSurveyEffort(camera_id=1, camera_days=58,
                                  detections=30, placement_context="random")]
    de, e = _run_parcel(efforts)
    assert de.density_mean is not None
    assert de.density_mean > 0
    # The <3-camera caveat must fire.
    assert any("Only 1 cameras" in c for c in de.caveats)


def test_lender_hundred_percent_biased_cameras_adjusted_below_raw():
    """All cameras at feeder (10× inflation factor for hog). Adjusted
    rate must be substantially below raw."""
    efforts = [
        CameraSurveyEffort(camera_id=i, camera_days=58,
                           detections=60, placement_context="feeder")
        for i in range(4)
    ]
    de, e = _run_parcel(efforts)
    assert de.detection_rate > 0
    assert de.detection_rate_adjusted is not None
    # feeder factor is 10× → adjusted should be ~1/10 of raw.
    assert de.detection_rate_adjusted < de.detection_rate / 5
    # And the no-random-placement caveat must fire.
    assert any("no random-placement" in c for c in de.caveats)


def test_lender_all_random_placement_raw_equals_adjusted():
    """All cameras at 'random' context. With feral_hog random factor
    = 1.0, literature-prior adjustment is a no-op → raw == adjusted."""
    efforts = [
        CameraSurveyEffort(camera_id=i, camera_days=58,
                           detections=40, placement_context="random")
        for i in range(4)
    ]
    de, e = _run_parcel(efforts)
    assert de.detection_rate == pytest.approx(
        de.detection_rate_adjusted, rel=1e-9)


def test_lender_mixed_placement_adjusted_between_raw_and_random_only():
    """Mixed biased + random cams. Adjusted rate should sit between
    the all-biased (deflated) rate and the all-random (unchanged) rate."""
    mixed = [
        CameraSurveyEffort(camera_id=0, camera_days=58,
                           detections=60, placement_context="feeder"),
        CameraSurveyEffort(camera_id=1, camera_days=58,
                           detections=60, placement_context="random"),
    ]
    all_random = [
        CameraSurveyEffort(camera_id=0, camera_days=58,
                           detections=60, placement_context="random"),
        CameraSurveyEffort(camera_id=1, camera_days=58,
                           detections=60, placement_context="random"),
    ]
    de_mixed, _ = _run_parcel(mixed)
    de_random, _ = _run_parcel(all_random)
    # Mixed adjusted < random (because half was deflated).
    assert de_mixed.detection_rate_adjusted < de_random.detection_rate_adjusted
    # Mixed adjusted > raw/10 (wouldn't be THIS low).
    assert de_mixed.detection_rate_adjusted > de_mixed.detection_rate / 10


def test_lender_density_ci_bounds_sensible():
    """CI low ≤ mean ≤ CI high; low ≥ 0."""
    efforts = [
        CameraSurveyEffort(camera_id=i, camera_days=58,
                           detections=30 + i * 5, placement_context="random")
        for i in range(4)
    ]
    de, _ = _run_parcel(efforts)
    assert de.density_ci_low is not None
    assert de.density_ci_low >= 0
    assert de.density_ci_low <= de.density_mean
    assert de.density_mean <= de.density_ci_high


def test_lender_tier_matches_density_bin_end_to_end():
    """For each target density, confirm tier + score land in the
    right bands after the full estimate_density → exposure chain."""
    # Hog events calibrated so raw rate ≈ target adjusted rate
    # (all-random so raw = adjusted), and density is approximately
    # rate × 12.93 (v=6, r=0.015, θ=0.7).
    targets = [
        (0.05, "Low"),       # rate → density ~ 0.65
        (0.20, "Moderate"),  # density ~ 2.6
        (0.50, "Elevated"),  # density ~ 6.5
        (1.00, "Severe"),    # density ~ 12.9
    ]
    for target_rate, expected_tier in targets:
        events = int(target_rate * 58 * 4)  # 4 cams × 58 days
        efforts = [
            CameraSurveyEffort(camera_id=i, camera_days=58,
                               detections=events // 4,
                               placement_context="random")
            for i in range(4)
        ]
        de, e = _run_parcel(efforts)
        assert e.tier == expected_tier, (
            f"rate {target_rate}: got tier {e.tier}, expected {expected_tier}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# (B) Old-path orchestration (demo mode)
# ═══════════════════════════════════════════════════════════════════════════

def test_old_path_demo_mode_produces_complete_assessment():
    """Full old-path orchestration runs end-to-end on demo data.
    Verifies every documented field in ParcelRiskAssessment is present
    with the right type and within expected range."""
    from risk.synthesis import run_risk_assessment
    result = run_risk_assessment(demo=True)

    # Top-level structure
    required = {
        "parcel_id", "property_name", "acreage", "county", "state",
        "ecoregion", "n_camera_stations", "assessment_date",
        "species_inventory", "damage_projections",
        "feral_hog_exposure_score", "regulatory_risk",
        "overall_risk_rating", "data_confidence",
        "methodology_version", "bias_correction_applied",
        "prepared_for",
    }
    missing = required - set(result.keys())
    assert not missing, f"missing fields: {missing}"

    # Type contracts
    assert isinstance(result["species_inventory"], list)
    assert len(result["species_inventory"]) > 0
    assert isinstance(result["damage_projections"], dict)
    assert isinstance(result["regulatory_risk"], dict)
    assert isinstance(result["bias_correction_applied"], bool)

    # Feral hog exposure score: present, 0-100 bounded
    fh = result["feral_hog_exposure_score"]
    assert fh is not None
    assert 0 <= fh["score"] <= 100

    # Overall risk rating is a letter/level string, not empty
    assert isinstance(result["overall_risk_rating"], str)
    assert result["overall_risk_rating"]

    # Data confidence has a grade
    assert "grade" in result["data_confidence"] or \
           "overall_grade" in result["data_confidence"]


def test_old_path_species_inventory_sorted_by_risk():
    """Inventory must be sorted invasive-first, descending detection
    frequency within tier."""
    from risk.synthesis import run_risk_assessment
    result = run_risk_assessment(demo=True)
    inv = result["species_inventory"]
    assert len(inv) >= 2

    # First entry must be an invasive (if any present) or ESA.
    flags = [sp.get("risk_flag") for sp in inv]
    if any(f and "INVASIVE" in f for f in flags):
        assert inv[0]["risk_flag"] is not None
        assert "INVASIVE" in inv[0]["risk_flag"]


def test_old_path_damage_projection_positive_for_detected_invasive():
    """If an invasive species with nonzero detection frequency is in
    the inventory, its damage projection must be > 0."""
    from risk.synthesis import run_risk_assessment
    result = run_risk_assessment(demo=True)
    projections = result["damage_projections"]
    for sp_key, proj in projections.items():
        if proj["detection_frequency_pct"] > 5:
            assert proj["estimated_annual_loss"] > 0
            assert proj["ten_year_npv"] > proj["estimated_annual_loss"]
            assert (proj["confidence_interval_low"]
                    <= proj["estimated_annual_loss"]
                    <= proj["confidence_interval_high"])


def test_old_path_bias_correction_fields_populated():
    """When bias correction ran, each species in inventory has both
    raw and adjusted detection frequencies."""
    from risk.synthesis import run_risk_assessment
    result = run_risk_assessment(demo=True)
    if not result["bias_correction_applied"]:
        pytest.skip("Bias correction didn't apply on this demo run")
    for sp in result["species_inventory"]:
        assert "detection_frequency_pct" in sp
        assert "raw_detection_frequency_pct" in sp


def test_old_path_idempotent_two_runs_same_result():
    """Running the orchestration twice on demo data produces the same
    key headline numbers (regression sentinel)."""
    from risk.synthesis import run_risk_assessment
    r1 = run_risk_assessment(demo=True)
    r2 = run_risk_assessment(demo=True)
    assert r1["feral_hog_exposure_score"]["score"] == \
           r2["feral_hog_exposure_score"]["score"]
    assert r1["overall_risk_rating"] == r2["overall_risk_rating"]
