"""Tests for risk.exposure — tier classifier + damage projection."""

import pytest

from risk.exposure import (
    CROP_DAMAGE_MODIFIER,
    DEFAULT_PER_HOG_ANNUAL_USD,
    TIER_INFO_ONLY,
    TIER_ORDER,
    TIER_SEVERE,
    TIER_UNKNOWN,
    dollar_projection_annual,
    exposure_for_species,
    score_for_hog_density,
    tier_for_hog_density,
)


# -------------------------------------------------------------------------
# Tier cutoffs
# -------------------------------------------------------------------------

class TestTierForHogDensity:

    def test_cutoffs(self):
        assert tier_for_hog_density(0.0) == "Low"
        assert tier_for_hog_density(1.9) == "Low"
        assert tier_for_hog_density(2.0) == "Moderate"
        assert tier_for_hog_density(4.9) == "Moderate"
        assert tier_for_hog_density(5.0) == "Elevated"
        assert tier_for_hog_density(9.9) == "Elevated"
        assert tier_for_hog_density(10.0) == TIER_SEVERE
        assert tier_for_hog_density(50.0) == TIER_SEVERE

    def test_unknown_on_bad_input(self):
        assert tier_for_hog_density(None) == TIER_UNKNOWN
        assert tier_for_hog_density(-0.01) == TIER_UNKNOWN

    def test_seeded_edwards_plateau_ranch_hog_is_elevated(self):
        # Our seed has hog density 5.13/km² - sits at the Elevated boundary.
        # Demo-narrative-critical: this MUST land in Elevated, not Severe.
        assert tier_for_hog_density(5.13) == "Elevated"

    def test_tier_order_is_dense_ascending(self):
        # Sanity that the tier order list matches cutoff ordering.
        assert TIER_ORDER == ["Low", "Moderate", "Elevated", "Severe"]


# -------------------------------------------------------------------------
# Score
# -------------------------------------------------------------------------

class TestScoreForHogDensity:

    def test_anchor_points(self):
        # Score anchors: 0->0, 2->25, 5->50, 10->75, 20+->100
        assert score_for_hog_density(0) == 0
        assert score_for_hog_density(2) == pytest.approx(25)
        assert score_for_hog_density(5) == pytest.approx(50)
        assert score_for_hog_density(10) == pytest.approx(75)
        assert score_for_hog_density(20) == 100
        assert score_for_hog_density(50) == 100   # clamp

    def test_interpolation_within_tier(self):
        # Between 2 and 5 (Moderate tier) score lerps from 25 to 50.
        mid = score_for_hog_density(3.5)
        assert 25 < mid < 50
        # Halfway through Moderate band -> ~37.5
        assert mid == pytest.approx(37.5, abs=0.1)

    def test_zero_or_negative_is_zero(self):
        assert score_for_hog_density(0) == 0
        assert score_for_hog_density(-1) == 0
        assert score_for_hog_density(None) == 0


# -------------------------------------------------------------------------
# Dollar projection
# -------------------------------------------------------------------------

class TestDollarProjection:

    def test_basic_math(self):
        # 5 hogs/km², 10 km² parcel, no crop -> 50 hogs × $405 × 1.0
        expected = 50 * DEFAULT_PER_HOG_ANNUAL_USD
        assert dollar_projection_annual(5.0, 10.0, None) == pytest.approx(expected, abs=1)

    def test_crop_modifier_applies(self):
        # Same density + area, corn vs pasture
        corn = dollar_projection_annual(5.0, 10.0, "corn")
        pasture = dollar_projection_annual(5.0, 10.0, "pasture")
        assert corn is not None and pasture is not None
        assert corn == pytest.approx(pasture * (1.6 / 0.5), rel=1e-3)

    def test_unknown_crop_uses_1x(self):
        generic = dollar_projection_annual(5.0, 10.0, "sunflower_of_death")
        known = dollar_projection_annual(5.0, 10.0, "mixed")
        assert generic == known  # both fall back to 1.0 modifier

    def test_missing_inputs_return_none(self):
        assert dollar_projection_annual(None, 10.0) is None
        assert dollar_projection_annual(5.0, None) is None
        assert dollar_projection_annual(5.0, 0.0) is None

    def test_custom_per_hog_rate(self):
        # For sensitivity analysis callers can pass a different rate.
        tight = dollar_projection_annual(
            5.0, 10.0, None, per_hog_annual_usd=200.0)
        loose = dollar_projection_annual(
            5.0, 10.0, None, per_hog_annual_usd=600.0)
        assert loose == pytest.approx(tight * 3.0, rel=1e-3)


# -------------------------------------------------------------------------
# Integrated exposure_for_species
# -------------------------------------------------------------------------

class TestExposureForSpecies:

    def test_hog_elevated_with_crop(self):
        e = exposure_for_species(
            species_key="feral_hog",
            density_mean=5.13,
            density_ci_low=1.29,
            density_ci_high=16.64,
            parcel_acreage=2340.0,  # ~9.47 km²
            crop_type="sorghum",
            recommendation="recommend_supplementary_survey",
        )
        assert e.species_key == "feral_hog"
        assert e.tier == "Elevated"
        assert 45 < e.score_0_100 < 55   # near 50
        assert e.dollar_projection_annual_usd is not None
        # CI ordering preserved.
        assert (e.dollar_projection_ci_low_usd
                < e.dollar_projection_annual_usd
                < e.dollar_projection_ci_high_usd)
        assert e.crop_modifier == pytest.approx(1.3)
        assert e.parcel_area_km2 == pytest.approx(9.4695, abs=0.01)
        # Method note makes the MODELED ESTIMATE label explicit.
        assert any("MODELED ESTIMATE" in n for n in e.method_notes)

    def test_non_hog_species_informational_only(self):
        e = exposure_for_species(
            species_key="white_tailed_deer",
            density_mean=21.4,
            density_ci_low=4.95,
            density_ci_high=67.17,
            parcel_acreage=2340.0,
            crop_type="sorghum",
            recommendation="recommend_supplementary_survey",
        )
        assert e.tier == TIER_INFO_ONLY
        assert e.score_0_100 is None
        assert e.dollar_projection_annual_usd is None
        assert any("Tier classification defined for feral hog only" in c
                   for c in e.caveats)

    def test_hog_with_no_density_is_unknown_tier(self):
        e = exposure_for_species(
            species_key="feral_hog",
            density_mean=None,
            density_ci_low=None,
            density_ci_high=None,
            parcel_acreage=2340.0,
            crop_type="corn",
            recommendation="insufficient_data",
        )
        assert e.tier == TIER_UNKNOWN
        assert e.score_0_100 is None
        assert e.dollar_projection_annual_usd is None

    def test_missing_parcel_acreage(self):
        e = exposure_for_species(
            species_key="feral_hog",
            density_mean=5.0,
            density_ci_low=3.0,
            density_ci_high=8.0,
            parcel_acreage=None,
            crop_type=None,
            recommendation="sufficient_for_decision",
        )
        # Tier/score still computed (density alone drives those).
        assert e.tier == "Elevated"
        assert e.score_0_100 is not None
        # But dollar figures are None without area.
        assert e.dollar_projection_annual_usd is None

    def test_all_crops_have_modifiers(self):
        # Every documented crop_type value should have a modifier so the UI
        # never shows an implicit 1.0x silently.
        for crop in ["corn", "sorghum", "rice", "cotton", "peanut", "wheat",
                     "soybean", "hay", "pasture", "rangeland", "mixed", "other"]:
            assert crop in CROP_DAMAGE_MODIFIER, f"Missing modifier for {crop!r}"
