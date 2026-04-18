"""Layer 1 — risk/damage.py (logistic frequency scaling, FH Exposure
Score composite, annual-loss calculus, NPV).

Note: this is the older damage model that predates the population-
pivot decision to defer damage dollars as supplementary. The code
still exists and is exercised; test it against its documented spec.
"""

import math

import pytest

from risk.damage import (
    logistic_frequency_scale, compute_annual_loss, compute_npv,
    compute_fh_exposure_score, quantify_damage,
    _DEFAULT_DAMAGE_MODELS,
)


# ---------------------------------------------------------------------------
# logistic_frequency_scale
# ---------------------------------------------------------------------------

def test_logistic_scale_at_50pct_equals_half():
    """The logistic is centered at 50% — exact midpoint."""
    assert logistic_frequency_scale(50.0) == pytest.approx(0.5, abs=1e-6)


def test_logistic_scale_monotone_increasing():
    prev = -1
    for f in [0, 10, 25, 40, 50, 60, 75, 90, 100]:
        v = logistic_frequency_scale(f)
        assert v > prev
        prev = v


def test_logistic_scale_bounded_0_to_1():
    for f in [-100, 0, 50, 100, 200, 1000]:
        v = logistic_frequency_scale(f)
        assert 0.0 < v <= 1.0   # saturates to 1.0 at extreme f


def test_logistic_scale_at_30pct_is_about_0_2():
    """Doc claims freq=30% → ~20% of max damage."""
    v = logistic_frequency_scale(30.0)
    assert 0.15 < v < 0.25


def test_logistic_scale_at_70pct_is_about_0_8():
    v = logistic_frequency_scale(70.0)
    assert 0.75 < v < 0.85


# ---------------------------------------------------------------------------
# compute_annual_loss
# ---------------------------------------------------------------------------

def test_annual_loss_multiplicative():
    """L = base × eco × freq × acreage."""
    result = compute_annual_loss(
        base_cost=10.0, ecoregion_factor=2.0, freq_scale=0.5, acreage=100)
    assert result == pytest.approx(1000.0)


def test_annual_loss_zero_acreage():
    assert compute_annual_loss(10, 1, 0.5, 0) == 0.0


def test_annual_loss_zero_freq():
    assert compute_annual_loss(10, 1, 0.0, 100) == 0.0


# ---------------------------------------------------------------------------
# compute_npv
# ---------------------------------------------------------------------------

def test_npv_zero_annual_loss_is_zero():
    assert compute_npv(0.0) == 0.0


def test_npv_with_zero_discount_equals_years_times_loss():
    """At r=0, NPV = annual × years."""
    npv = compute_npv(100.0, years=10, discount_rate=0.0)
    assert npv == pytest.approx(1000.0)


def test_npv_with_positive_discount_is_less_than_undiscounted():
    """With r > 0, the present value should be less than annual × years."""
    npv = compute_npv(100.0, years=10, discount_rate=0.05)
    assert npv < 1000.0
    assert npv > 700.0    # 10-year 5% discount factor ≈ 7.72


def test_npv_higher_discount_reduces_value():
    a = compute_npv(100.0, years=10, discount_rate=0.03)
    b = compute_npv(100.0, years=10, discount_rate=0.10)
    assert a > b


# ---------------------------------------------------------------------------
# compute_fh_exposure_score
# ---------------------------------------------------------------------------

def test_exposure_score_zero_when_no_detections_far_past():
    r = compute_fh_exposure_score(0.0, 1000, 0.0)
    assert r["score"] < 5


def test_exposure_score_maxes_near_100_for_active_recent_widespread():
    r = compute_fh_exposure_score(100.0, 0, 1.0)
    # Components: 100 × 0.4 + 100 × 0.3 + 100 × 0.3 = 100
    assert r["score"] == 100


def test_exposure_score_bounded_0_to_100():
    """Even extreme inputs stay in range."""
    for freq in [-10, 0, 50, 150, 200]:
        for days in [-5, 0, 30, 365, 10_000]:
            for frac in [-0.5, 0, 0.5, 1.5]:
                r = compute_fh_exposure_score(freq, days, frac)
                assert 0 <= r["score"] <= 100


def test_exposure_score_recency_decays_exponentially():
    r0 = compute_fh_exposure_score(50, 0, 0.5)
    r30 = compute_fh_exposure_score(50, 30, 0.5)
    r180 = compute_fh_exposure_score(50, 180, 0.5)
    assert r0["score"] >= r30["score"] >= r180["score"]


def test_exposure_score_interpretation_at_each_band():
    """The interpretation string transitions at 20/40/60/80."""
    r19 = compute_fh_exposure_score(0, 365, 0.1)  # low
    r50 = compute_fh_exposure_score(50, 30, 0.5)  # moderate-elevated
    r99 = compute_fh_exposure_score(100, 0, 1.0)  # critical
    assert "MINIMAL" in r19["interpretation"] or "LOW" in r19["interpretation"]
    assert r99["score"] >= 80
    assert "CRITICAL" in r99["interpretation"]


# ---------------------------------------------------------------------------
# quantify_damage end-to-end
# ---------------------------------------------------------------------------

def test_quantify_damage_with_no_invasives_empty_result():
    result = quantify_damage(
        species_inventory=[{
            "species_key": "white_tailed_deer",
            "invasive": False, "esa_status": None,
            "detection_frequency_pct": 90.0,
            "cameras_detected": 10, "cameras_total": 10,
            "confidence_grade": "A",
        }],
        acreage=500,
    )
    assert result["projections"] == {}
    assert result["fh_exposure_score"] is None


def test_quantify_damage_axis_deer_uses_default_model():
    """Axis deer isn't in SPECIES_REFERENCE by default but has an entry
    in _DEFAULT_DAMAGE_MODELS; must still produce a projection."""
    result = quantify_damage(
        species_inventory=[{
            "species_key": "axis_deer",
            "invasive": True, "esa_status": None,
            "detection_frequency_pct": 50.0,
            "cameras_detected": 5, "cameras_total": 10,
            "confidence_grade": "B",
        }],
        acreage=1000,
        ecoregion="edwards_plateau",
    )
    assert "axis_deer" in result["projections"]
    p = result["projections"]["axis_deer"]
    assert p["estimated_annual_loss"] > 0
    assert p["ten_year_npv"] > p["estimated_annual_loss"]


def test_quantify_damage_ci_widens_for_worse_grades():
    """Grade D should give a wider CI than Grade A at same loss."""
    bad = quantify_damage(
        species_inventory=[{
            "species_key": "axis_deer",
            "invasive": True, "esa_status": None,
            "detection_frequency_pct": 50.0,
            "cameras_detected": 1, "cameras_total": 10,
            "confidence_grade": "D",
        }], acreage=1000)
    good = quantify_damage(
        species_inventory=[{
            "species_key": "axis_deer",
            "invasive": True, "esa_status": None,
            "detection_frequency_pct": 50.0,
            "cameras_detected": 10, "cameras_total": 10,
            "confidence_grade": "A",
        }], acreage=1000)
    assert (bad["projections"]["axis_deer"]["confidence_interval_pct"]
            > good["projections"]["axis_deer"]["confidence_interval_pct"])
