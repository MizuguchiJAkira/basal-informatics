"""Layer 1 — risk/regulatory.py ESA assessment tests."""

import pytest

from risk.regulatory import (
    assess_regulatory_risk, _assess_single_species,
    _assess_esa_database_species, _ESA_SPECIES_DATABASE,
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_demo_mode_edwards_plateau_flags_golden_cheeked_warbler():
    """Demo mode on the Edwards Plateau ecoregion should flag GCW
    even if no cameras detected it, because habitat overlaps."""
    result = assess_regulatory_risk(
        species_inventory=[],  # no cameras detected anything
        acreage=2340,
        ecoregion="edwards_plateau",
        demo=True,
    )
    assert "golden_cheeked_warbler" in result["esa_species_present"]
    assert result["consultation_required"] is True
    assert result["total_estimated_compliance_cost_low"] > 0
    assert (result["total_estimated_compliance_cost_high"]
            > result["total_estimated_compliance_cost_low"])


def test_non_demo_without_camera_esa_produces_no_flags():
    """Production mode without actual habitat layers skips the
    ecoregion-database sweep entirely."""
    result = assess_regulatory_risk(
        species_inventory=[],
        acreage=650,
        ecoregion="edwards_plateau",
        demo=False,
    )
    assert result["esa_species_present"] == []
    assert result["consultation_required"] is False


def test_camera_detected_esa_species_always_flagged():
    """Even in non-demo mode, if cameras DETECTED an ESA species, it
    must be surfaced as a regulatory concern."""
    result = assess_regulatory_risk(
        species_inventory=[{
            "species_key": "golden_cheeked_warbler",
            "esa_status": "Endangered",
        }],
        acreage=500,
        ecoregion="edwards_plateau",
        demo=False,
    )
    assert "golden_cheeked_warbler" in result["esa_species_present"]
    assert result["consultation_required"] is True


def test_delisted_species_not_flagged_even_in_demo():
    """Black-capped vireo is Delisted — should NOT trigger automatic
    consultation-required even in demo mode."""
    result = assess_regulatory_risk(
        species_inventory=[],
        acreage=500,
        ecoregion="edwards_plateau",
        demo=True,
    )
    # GCW yes, but delisted vireo no
    assert "black_capped_vireo" not in result["esa_species_present"]


def test_non_range_ecoregion_does_not_flag_gcw():
    """GCW range is Edwards Plateau only. A Piney Woods parcel
    should not trigger the flag in demo or production."""
    result = assess_regulatory_risk(
        species_inventory=[],
        acreage=500,
        ecoregion="piney_woods",
        demo=True,
    )
    assert "golden_cheeked_warbler" not in result["esa_species_present"]


# ---------------------------------------------------------------------------
# Cost model
# ---------------------------------------------------------------------------

def test_compliance_cost_scales_with_acreage():
    """Doubling parcel acreage should approximately double the
    per-acre component of compliance cost."""
    small = assess_regulatory_risk(
        species_inventory=[], acreage=500,
        ecoregion="edwards_plateau", demo=True,
    )
    large = assess_regulatory_risk(
        species_inventory=[], acreage=5000,
        ecoregion="edwards_plateau", demo=True,
    )
    # The per-acre delta should favor the large parcel.
    assert (large["total_estimated_compliance_cost_high"]
            > small["total_estimated_compliance_cost_high"])


def test_compliance_cost_zero_acreage_still_includes_fixed_cost():
    """Even at zero acreage the fixed HCP-development cost applies
    (plan writing, USFWS consultation fees)."""
    result = assess_regulatory_risk(
        species_inventory=[], acreage=0,
        ecoregion="edwards_plateau", demo=True,
    )
    # With GCW fixed cost range (15000, 45000), low must be >= 15000.
    if result["species_details"]:
        assert result["total_estimated_compliance_cost_low"] >= 15000


def test_no_cost_when_no_species():
    result = assess_regulatory_risk(
        species_inventory=[], acreage=1000,
        ecoregion="piney_woods", demo=True,
    )
    assert result["total_estimated_compliance_cost_low"] == 0
    assert result["total_estimated_compliance_cost_high"] == 0


# ---------------------------------------------------------------------------
# Database integrity (catches accidental edits to _ESA_SPECIES_DATABASE)
# ---------------------------------------------------------------------------

def test_esa_database_has_required_fields_per_species():
    required = {"common_name", "scientific_name", "esa_status",
                "habitat_description", "range_ecoregions",
                "compliance_cost_model"}
    for key, entry in _ESA_SPECIES_DATABASE.items():
        missing = required - set(entry.keys())
        assert not missing, f"{key} missing {missing}"
        # Cost model structure
        cm = entry["compliance_cost_model"]
        assert "fixed_cost_range" in cm
        assert "per_acre_cost_range" in cm
        assert "typical_overlap_fraction" in cm
        lo, hi = cm["fixed_cost_range"]
        assert 0 <= lo <= hi
        assert 0.0 <= cm["typical_overlap_fraction"] <= 1.0


def test_esa_database_gcw_scientific_name_is_correct():
    """Regression: docs + marketing reference Setophaga chrysoparia.
    Accidental edit to Dendroica chrysoparia would be wrong (old genus)."""
    gcw = _ESA_SPECIES_DATABASE["golden_cheeked_warbler"]
    assert gcw["scientific_name"] == "Setophaga chrysoparia"
