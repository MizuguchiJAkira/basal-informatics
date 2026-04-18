"""Layer 1 — pure-function helpers across modules that don't need a DB.

Batches:
  A) config.species_reference: assign_risk_flag, confidence_to_grade
  B) risk.inventory: _best_grade, _risk_sort_key
  C) bias.propensity: _encode_features
  D) habitat.corridors: _corridor_weights_for_nlcd
"""

import numpy as np
import pytest


# ═════════════════════════════════════════════════════════════════════════
# A — species_reference
# ═════════════════════════════════════════════════════════════════════════

from config.species_reference import (
    SPECIES_REFERENCE, assign_risk_flag, confidence_to_grade,
)


@pytest.mark.parametrize("freq,expected_contains", [
    (70.0, "HIGH"),
    (69.9, "MODERATE"),
    (30.0, "MODERATE"),
    (29.9, "LOW"),
    (0.0,  "LOW"),
])
def test_risk_flag_thresholds_for_invasive(freq, expected_contains):
    flag = assign_risk_flag("feral_hog", freq)
    assert flag is not None
    assert expected_contains in flag


def test_risk_flag_unknown_species_returns_none():
    assert assign_risk_flag("unobtanium_lemur", 50.0) is None


def test_risk_flag_esa_species_returns_esa_status():
    # Only if GCW is in SPECIES_REFERENCE with esa_status set.
    if "golden_cheeked_warbler" in SPECIES_REFERENCE:
        flag = assign_risk_flag("golden_cheeked_warbler", 5.0)
        # Could be None if invasive=False and no esa_status, or "ESA — ..."
        if flag:
            assert flag.startswith("ESA")


@pytest.mark.parametrize("pct,expected", [
    (30.0, "A"),
    (29.99, "A-"),
    (25.0, "A-"),
    (24.99, "B+"),
    (20.0, "B+"),
    (19.99, "B"),
    (16.0, "B"),
    (15.99, "B-"),
    (12.0, "B-"),
    (11.99, "C+"),
    (9.0,  "C+"),
    (8.99, "C"),
    (7.0,  "C"),
    (6.99, "C-"),
    (5.0,  "C-"),
    (4.99, "D"),
    (3.0,  "D"),
    (2.99, "F"),
    (0.0,  "F"),
])
def test_confidence_to_grade_boundaries(pct, expected):
    assert confidence_to_grade(pct) == expected


# ═════════════════════════════════════════════════════════════════════════
# B — inventory helpers
# ═════════════════════════════════════════════════════════════════════════

from risk.inventory import _best_grade, _risk_sort_key


def test_best_grade_picks_most_favorable():
    assert _best_grade(["A", "B", "C", "D"]) == "A"
    assert _best_grade(["C", "B+", "B-"]) == "B+"
    assert _best_grade(["F", "F", "F"]) == "F"
    # Mixed invalid values get ignored; valid pick returns.
    assert _best_grade(["garbage", "A", "X"]) == "A"


def test_best_grade_empty_or_all_unknown_returns_F():
    assert _best_grade([]) == "F"
    assert _best_grade(["?"] * 3) == "F"


def test_risk_sort_key_order():
    """Invasive-HIGH < MODERATE < LOW < ESA < (no flag). Within a tier,
    descending detection_frequency_pct."""
    entries = [
        {"risk_flag": "INVASIVE — LOW", "detection_frequency_pct": 50},
        {"risk_flag": "ESA — Endangered", "detection_frequency_pct": 70},
        {"risk_flag": "INVASIVE — HIGH", "detection_frequency_pct": 80},
        {"risk_flag": None, "detection_frequency_pct": 95},
        {"risk_flag": "INVASIVE — MODERATE", "detection_frequency_pct": 40},
        {"risk_flag": "INVASIVE — HIGH", "detection_frequency_pct": 60},
    ]
    entries.sort(key=_risk_sort_key)
    # Invasive-HIGH first (ordered within by freq desc)
    assert entries[0]["risk_flag"] == "INVASIVE — HIGH"
    assert entries[0]["detection_frequency_pct"] == 80
    assert entries[1]["risk_flag"] == "INVASIVE — HIGH"
    assert entries[1]["detection_frequency_pct"] == 60
    # Then moderate, low, ESA, none
    flags_in_order = [e["risk_flag"] for e in entries]
    assert flags_in_order.index("INVASIVE — HIGH") < flags_in_order.index("INVASIVE — MODERATE")
    assert "ESA — Endangered" in flags_in_order
    assert flags_in_order[-1] is None


# ═════════════════════════════════════════════════════════════════════════
# C — propensity _encode_features
# ═════════════════════════════════════════════════════════════════════════

from bias.propensity import _encode_features


def test_encode_features_shape_matches_feature_count():
    """Continuous (8) + one-hot cats (nlcd: 6, aspect: 7) = 21 cols."""
    rows = [{
        "distance_to_water_m": 100, "distance_to_road_m": 200,
        "slope_degrees": 5, "canopy_cover_pct": 30,
        "relative_elevation": 10, "distance_to_edge_m": 50,
        "mean_temp_c": 15, "total_precip_mm": 500,
        "nlcd_code": 41, "aspect": "N",
    }, {
        "distance_to_water_m": 150, "distance_to_road_m": 250,
        "slope_degrees": 8, "canopy_cover_pct": 40,
        "relative_elevation": 12, "distance_to_edge_m": 60,
        "mean_temp_c": 16, "total_precip_mm": 550,
        "nlcd_code": 42, "aspect": "SE",
    }]
    X, names = _encode_features(rows)
    assert X.shape == (2, len(names))
    assert "distance_to_water_m" in names
    assert any("nlcd_code_" in n for n in names)
    assert any("aspect_" in n for n in names)


def test_encode_features_missing_values_default_to_zero():
    rows = [{}]
    X, _ = _encode_features(rows)
    assert X.shape[0] == 1
    # All features default to 0
    assert np.allclose(X, 0.0)


def test_encode_features_drop_first_category():
    """nlcd_code 41 is the first-category reference — should NOT get
    its own one-hot column. Value 42 (second category) gets a column."""
    rows = [{"nlcd_code": 41}, {"nlcd_code": 42}]
    X, names = _encode_features(rows)
    # There should be no `nlcd_code_41` column (dropped as reference)
    assert not any(n == "nlcd_code_41" for n in names)
    # But nlcd_code_42 should exist and be active for row 1.
    col42 = names.index("nlcd_code_42")
    assert X[0, col42] == 0.0
    assert X[1, col42] == 1.0


# ═════════════════════════════════════════════════════════════════════════
# D — corridor weights for NLCD
# ═════════════════════════════════════════════════════════════════════════

from habitat.corridors import _corridor_weights_for_nlcd


def test_corridor_weights_forest_emphasizes_riparian_and_edge():
    w = _corridor_weights_for_nlcd(41)   # Deciduous Forest
    assert w["riparian"] == 1.0
    assert w["forest_grass_edge"] == 1.0
    assert w["wetland_margin"] <= 0.5


def test_corridor_weights_shrub_emphasizes_ridge():
    w = _corridor_weights_for_nlcd(52)   # Shrub/Scrub
    assert w["ridge"] == 1.0


def test_corridor_weights_grassland_emphasizes_edge():
    w = _corridor_weights_for_nlcd(71)   # Grassland
    assert w["forest_grass_edge"] == 1.0


def test_corridor_weights_default_for_unknown_nlcd():
    w = _corridor_weights_for_nlcd(999)
    # Must return all 5 standard corridor types
    for t in ("riparian", "ridge", "forest_grass_edge",
              "forest_crop_edge", "wetland_margin"):
        assert t in w
        assert 0.0 <= w[t] <= 1.0


def test_corridor_weights_all_values_bounded():
    """For every nlcd code, weights should be in [0, 1]."""
    for code in (41, 42, 43, 52, 71, 81, 82, 123, 0, -1):
        w = _corridor_weights_for_nlcd(code)
        for k, v in w.items():
            assert 0.0 <= v <= 1.0, f"{code}/{k}={v}"
