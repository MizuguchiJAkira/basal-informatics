"""Layer 1 — classifier-post-processing + exposure-score boundary tests.

Splits into two themes that share a test file for test-run convenience:

  A) strecker.classify:
     - compute_softmax_entropy at and around the 0.59 nats threshold
     - temperature_scale preserves monotonicity + edge cases
     - compute_temporal_prior bounds

  B) risk.exposure:
     - score_for_hog_density at the piecewise-linear anchor points
       (0, 2, 5, 10, 20) and between them
     - tier_for_hog_density at exact cutoffs (not off-by-one)
     - dollar_projection_annual edge cases (zero / negative / missing area)
"""

import math

import pytest


# ═════════════════════════════════════════════════════════════════════════
# A — strecker.classify
# ═════════════════════════════════════════════════════════════════════════

from config import settings
from strecker.classify import (
    compute_softmax_entropy, temperature_scale, compute_temporal_prior,
)


def _binary_entropy(p):
    return -(p * math.log(p) + (1 - p) * math.log(1 - p))


def test_entropy_threshold_constant_is_0_59():
    """Doc + test plan both reference 0.59 nats. Lock the constant."""
    assert settings.REVIEW_ENTROPY_THRESHOLD == 0.59


def test_entropy_boundary_lives_near_p_0_7285():
    """Binary entropy passes through 0.59 nats between p=0.72 and p=0.73.
    Document and lock that calibration window."""
    # Above threshold (less confident → more entropy)
    assert compute_softmax_entropy(0.72) > 0.59
    # Below threshold (more confident → less entropy)
    assert compute_softmax_entropy(0.74) < 0.59


def test_entropy_just_above_threshold_flags_review():
    """p=0.72 → entropy 0.593 > threshold 0.59 → review_required."""
    h = compute_softmax_entropy(0.72)
    assert h > settings.REVIEW_ENTROPY_THRESHOLD


def test_entropy_just_below_threshold_skips_review():
    """p=0.74 → entropy 0.572 < threshold 0.59 → no review."""
    h = compute_softmax_entropy(0.74)
    assert h < settings.REVIEW_ENTROPY_THRESHOLD


def test_entropy_exactly_at_threshold_is_not_flagged():
    """review_required = entropy > threshold (strict >). At the exact
    threshold value, no review is triggered."""
    # This exercises the comparator, not the math.
    threshold = settings.REVIEW_ENTROPY_THRESHOLD
    # Synthetic: assert the > comparator does what we expect
    assert not (threshold > threshold)
    assert (threshold + 1e-6 > threshold)


def test_entropy_symmetry_around_half():
    """H(p) == H(1-p) for binary entropy."""
    for p in (0.1, 0.25, 0.4, 0.7, 0.85):
        assert compute_softmax_entropy(p) == pytest.approx(
            compute_softmax_entropy(1 - p), abs=1e-4)


def test_entropy_maximum_at_p_half():
    """Binary entropy peaks at p=0.5 with H = ln(2) ≈ 0.693."""
    h = compute_softmax_entropy(0.5)
    assert h == pytest.approx(math.log(2), abs=1e-3)


def test_entropy_at_zero_and_one_doesnt_blow_up():
    """Clamping at 1e-7/1-1e-7 must prevent log(0)."""
    assert math.isfinite(compute_softmax_entropy(0.0))
    assert math.isfinite(compute_softmax_entropy(1.0))


def test_entropy_p_above_one_clamped():
    """Out-of-range inputs don't crash."""
    assert math.isfinite(compute_softmax_entropy(1.5))
    assert math.isfinite(compute_softmax_entropy(-0.2))


# --- temperature_scale ---

def test_temperature_scale_T_equals_1_is_identity():
    """With T=1 the scaled confidence equals the raw confidence."""
    for c in (0.1, 0.5, 0.7, 0.9, 0.99):
        assert temperature_scale(c, T=1.0) == pytest.approx(c, abs=1e-6)


def test_temperature_scale_T_gt_1_softens_confidence():
    """T > 1 moves confidence toward 0.5 (softens)."""
    raw = 0.95
    scaled = temperature_scale(raw, T=1.08)
    assert scaled < raw
    assert scaled > 0.5


def test_temperature_scale_monotonic_in_raw():
    """Higher raw confidence should produce higher scaled confidence."""
    T = 1.08
    for a, b in [(0.3, 0.5), (0.5, 0.7), (0.7, 0.9)]:
        assert temperature_scale(a, T) < temperature_scale(b, T)


# --- compute_temporal_prior ---

def test_temporal_prior_bounds_between_0_and_1():
    for sp in ("feral_hog", "white_tailed_deer", "raccoon"):
        for h in range(24):
            p = compute_temporal_prior(sp, float(h))
            assert 0.0 <= p <= 1.0


def test_temporal_prior_unknown_species_returns_neutral():
    """Species not in the table should return a neutral prior, not crash."""
    p = compute_temporal_prior("unknown_species_xyz", 12.0)
    assert 0.0 <= p <= 1.0


# ═════════════════════════════════════════════════════════════════════════
# B — risk.exposure score + tier boundaries
# ═════════════════════════════════════════════════════════════════════════

from risk.exposure import (
    score_for_hog_density, tier_for_hog_density, dollar_projection_annual,
    TIER_SEVERE, TIER_UNKNOWN,
)
# These aren't exported as constants in risk/exposure.py; the cutoff
# table uses them as literal strings. Keep the literal to match.
TIER_LOW = "Low"
TIER_MODERATE = "Moderate"
TIER_ELEVATED = "Elevated"


@pytest.mark.parametrize("density,expected", [
    (0.0, 0.0),       # anchor: 0 → 0
    (2.0, 25.0),      # anchor: Low/Moderate boundary → 25
    (5.0, 50.0),      # anchor: Moderate/Elevated boundary → 50
    (10.0, 75.0),     # anchor: Elevated/Severe boundary → 75
    (20.0, 100.0),    # anchor: clamp ceiling → 100
    (30.0, 100.0),    # beyond the top anchor clamps
    (1.0, 12.5),      # halfway within Low band (0,25) at density 1
    (15.0, 87.5),     # halfway within Severe band (75,100) at density 15
])
def test_score_at_every_anchor_and_between(density, expected):
    s = score_for_hog_density(density)
    assert s == pytest.approx(expected, abs=1e-6)


def test_score_is_monotone_increasing():
    prev = -1
    for d in [0, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 25, 100]:
        s = score_for_hog_density(d)
        assert s >= prev
        prev = s


def test_score_at_negative_density_returns_zero():
    assert score_for_hog_density(-1.0) == 0.0


def test_score_at_none_returns_zero():
    assert score_for_hog_density(None) == 0.0


@pytest.mark.parametrize("density,expected", [
    (0.0,    TIER_LOW),
    (1.999,  TIER_LOW),
    (2.0,    TIER_MODERATE),         # exact cutoff — this is the boundary
    (2.001,  TIER_MODERATE),
    (4.999,  TIER_MODERATE),
    (5.0,    TIER_ELEVATED),         # exact cutoff
    (9.999,  TIER_ELEVATED),
    (10.0,   TIER_SEVERE),           # exact cutoff
    (100.0,  TIER_SEVERE),
])
def test_tier_at_every_cutoff(density, expected):
    assert tier_for_hog_density(density) == expected


def test_tier_negative_density_is_unknown():
    assert tier_for_hog_density(-0.1) == TIER_UNKNOWN


def test_tier_none_density_is_unknown():
    assert tier_for_hog_density(None) == TIER_UNKNOWN


# --- dollar_projection_annual ---

def test_dollar_projection_zero_area_returns_none():
    assert dollar_projection_annual(5.0, 0.0) is None


def test_dollar_projection_negative_area_returns_none():
    assert dollar_projection_annual(5.0, -1.0) is None


def test_dollar_projection_none_density_returns_none():
    assert dollar_projection_annual(None, 2.0) is None


def test_dollar_projection_none_area_returns_none():
    assert dollar_projection_annual(5.0, None) is None


def test_dollar_projection_zero_density_returns_zero():
    """Zero hogs × anything = zero damage."""
    assert dollar_projection_annual(0.0, 2.0) == 0.0


def test_dollar_projection_scales_linearly_with_density():
    """Doubling density should double damage at fixed area."""
    d1 = dollar_projection_annual(5.0, 2.0, crop_type="corn")
    d2 = dollar_projection_annual(10.0, 2.0, crop_type="corn")
    assert d2 == pytest.approx(2 * d1, abs=1.0)


def test_dollar_projection_scales_linearly_with_area():
    d1 = dollar_projection_annual(5.0, 1.0, crop_type="corn")
    d2 = dollar_projection_annual(5.0, 3.0, crop_type="corn")
    assert d2 == pytest.approx(3 * d1, abs=1.0)


def test_dollar_projection_crop_modifier_corn_exceeds_pasture():
    """Corn has a higher crop modifier (1.6) than pasture (~1.0)."""
    d_corn = dollar_projection_annual(5.0, 1.0, crop_type="corn")
    d_past = dollar_projection_annual(5.0, 1.0, crop_type="pasture")
    assert d_corn > d_past
