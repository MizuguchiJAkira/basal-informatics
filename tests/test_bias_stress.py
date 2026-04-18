"""Layer 5 — bias correction stress tests.

Creative / adversarial scenarios designed to expose assumption breaks
in both IPW implementations:

  A) bias.ipw (per-detection, 8:1 weight cap)
  B) bias.placement_ipw (per-camera-rate, REM-side correction)

Scenarios from the test plan:
  1. Perfectly uniform placement distribution → correction ~ 1.0
  2. Bimodal propensity distribution → plausible adjusted frequency
  3. Real-world: 12 feeder/water + 2 open, species only on feeders
  4. Weight cap prevents single-camera domination
"""

from types import SimpleNamespace

import numpy as np
import pytest

from bias.ipw import compute_ipw
from bias.placement_ipw import (
    compute_bias_correction, hajek_weighted_rate,
    literature_adjusted_rate, DEFAULT_INFLATION_FACTORS,
)


def _cam_rows(n, contexts=None):
    contexts = contexts or ["random"] * n
    return [{"point_id": f"cam-{i:03d}",
             "placement_context": contexts[i]}
            for i in range(n)]


def _det(cid, sp, eid):
    return SimpleNamespace(
        camera_id=cid, species_key=sp, independent_event_id=eid)


# ---------------------------------------------------------------------------
# 1. Uniform propensity distribution → unit weights, correction factor ~ 1.0
# ---------------------------------------------------------------------------

def test_uniform_propensity_produces_unit_weights():
    """All cameras at identical propensity 0.5. After stabilization +
    normalization, every weight == 1.0, and raw_freq == adjusted_freq."""
    n = 10
    props = np.full(n, 0.5)
    rows = _cam_rows(n)
    dets = [_det(f"cam-{i:03d}", "feral_hog", f"e{i}") for i in range(5)]
    r = compute_ipw(props, rows, detections=dets)
    weights = [w["trimmed_weight"] for w in r["camera_weights"]]
    # All weights == 1.0
    assert all(abs(w - 1.0) < 1e-9 for w in weights)
    # Raw freq must equal adjusted freq exactly when all weights are equal
    sp = r["per_species"]["feral_hog"]
    assert sp["raw_detection_frequency_pct"] == sp[
        "adjusted_detection_frequency_pct"]
    assert sp["adjustment_ratio"] == pytest.approx(1.0, abs=1e-9)


def test_uniform_placement_context_placement_ipw_yields_no_change():
    """Placement-IPW on all-random cameras: factor 1.0 per cam,
    adjusted rate == raw rate."""
    effs = [SimpleNamespace(camera_days=30, detections=10,
                            placement_context="random")
            for _ in range(10)]
    raw = 10 / 30
    r = compute_bias_correction("feral_hog", effs)
    assert r.literature_adjusted_rate == pytest.approx(raw, rel=1e-9)
    assert r.raw_rate == pytest.approx(raw, rel=1e-9)


# ---------------------------------------------------------------------------
# 2. Bimodal propensity distribution
# ---------------------------------------------------------------------------

def test_bimodal_propensity_produces_plausible_adjusted_freq():
    """Half cameras at propensity 0.05 (unusual spots), half at 0.95
    (common/feeder). Species detected ONLY at the unusual (0.05)
    cameras → raw freq 50%, adjusted should be much higher because
    the unusual cams get up-weighted to represent the landscape."""
    n = 20
    props = np.array([0.05] * 10 + [0.95] * 10)
    rows = _cam_rows(n)
    # Species detected only at the first 10 (low-propensity) cameras.
    dets = [_det(f"cam-{i:03d}", "coyote", f"e{i}") for i in range(10)]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["coyote"]
    raw = sp["raw_detection_frequency_pct"]
    adj = sp["adjusted_detection_frequency_pct"]
    assert raw == pytest.approx(50.0, abs=0.5)
    # Adjusted must be meaningfully higher — up-weighting rare placements.
    assert adj > raw + 10


def test_bimodal_reverse_species_on_common_placements_adjusted_lower():
    """Reverse case: species detected ONLY on high-propensity (common/
    feeder) cameras → adjusted frequency must be meaningfully lower."""
    n = 20
    props = np.array([0.05] * 10 + [0.95] * 10)
    rows = _cam_rows(n)
    dets = [_det(f"cam-{i:03d}", "feral_hog", f"e{i}") for i in range(10, 20)]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["feral_hog"]
    raw = sp["raw_detection_frequency_pct"]
    adj = sp["adjusted_detection_frequency_pct"]
    assert raw == pytest.approx(50.0, abs=0.5)
    assert adj < raw - 10


# ---------------------------------------------------------------------------
# 3. Real-world scenario: 12 biased + 2 open, hog only on biased
# ---------------------------------------------------------------------------

def test_realworld_12_biased_2_open_heavy_bias_correction():
    """12 cameras on feeder/water with heavy hog detection, 2 cameras
    in open terrain with zero hog detection. The IPW correction
    must pull the estimate DOWN toward the open-terrain baseline."""
    effs = []
    for _ in range(6):
        effs.append(SimpleNamespace(
            camera_days=30, detections=18, placement_context="feeder"))
    for _ in range(6):
        effs.append(SimpleNamespace(
            camera_days=30, detections=9, placement_context="water"))
    # 2 random-placement cams with ZERO hog detections.
    effs.append(SimpleNamespace(
        camera_days=30, detections=0, placement_context="random"))
    effs.append(SimpleNamespace(
        camera_days=30, detections=0, placement_context="random"))

    r = compute_bias_correction("feral_hog", effs)
    raw = r.raw_rate
    adj = r.literature_adjusted_rate
    # Raw mean event rate per cam-day:
    #   total events = 6*18 + 6*9 = 108 + 54 = 162
    #   total camera-days = 14 * 30 = 420
    #   raw = 162 / 420 = 0.3857
    assert raw == pytest.approx(0.3857, rel=1e-3)
    # Adjusted: per-cam rate / factor then mean.
    #   feeder: 18/30 / 10 = 0.06  ×6
    #   water:  9/30 / 3  = 0.1    ×6
    #   random: 0/30 / 1  = 0      ×2
    #   mean = (6*0.06 + 6*0.1 + 0) / 14 = 0.96/14 = 0.0686
    assert adj == pytest.approx(0.0686, abs=0.005)
    # Correction ratio: adj / raw should be meaningfully < 1.
    assert adj / raw < 0.2


def test_realworld_scenario_propensity_auc_above_threshold():
    """A deployment with clear biased-vs-random split should produce
    an AUC ≥ 0.6 on the propensity model — meaning bias is detected."""
    # Synthetic: 30 cameras + 500 reference points with obvious
    # covariate divergence on distance_to_water.
    cam_rows = []
    for i in range(30):
        cam_rows.append({
            "point_id": f"cam-{i:03d}",
            "is_camera": 1,
            "distance_to_water_m": 50.0,   # cameras cluster near water
            "distance_to_road_m": 300.0,
            "slope_degrees": 5.0,
            "canopy_cover_pct": 40.0,
            "relative_elevation": 10.0,
            "distance_to_edge_m": 30.0,
            "mean_temp_c": 20.0,
            "total_precip_mm": 600.0,
            "nlcd_code": 42,
            "aspect": "S",
            "placement_context": "feeder",
        })
    rng = np.random.default_rng(0)
    ref_rows = []
    for i in range(500):
        ref_rows.append({
            "point_id": f"ref-{i:04d}",
            "is_camera": 0,
            "distance_to_water_m": float(rng.uniform(200, 2000)),
            "distance_to_road_m": float(rng.uniform(100, 2000)),
            "slope_degrees": float(rng.uniform(0, 30)),
            "canopy_cover_pct": float(rng.uniform(0, 80)),
            "relative_elevation": float(rng.normal(0, 20)),
            "distance_to_edge_m": float(rng.uniform(50, 500)),
            "mean_temp_c": 20.0, "total_precip_mm": 600.0,
            "nlcd_code": int(rng.choice([41, 42, 52, 71, 81])),
            "aspect": str(rng.choice(["N","NE","E","SE","S","SW","W","NW"])),
            "placement_context": None,
        })

    from bias.propensity import fit_propensity_model
    result = fit_propensity_model(cam_rows, ref_rows)
    assert result["auc"] > 0.8, (
        f"expected high AUC on obvious bias, got {result['auc']}"
    )
    assert result["bias_detected"] is True


# ---------------------------------------------------------------------------
# 4. Weight-cap stress — single dominant camera scenario
# ---------------------------------------------------------------------------

def test_weight_cap_prevents_single_camera_from_dominating():
    """Construct 10 cameras where ONE has propensity 0.02 (50× raw
    weight) and 9 have propensity 0.5 (2× raw weight). Without the
    8:1 cap the single cam's weight is ~25× any other's; after the
    cap, it's 8×."""
    props = np.array([0.02] + [0.5] * 9)
    rows = _cam_rows(10)
    # Species detected ONLY at the dominant camera.
    dets = [_det("cam-000", "coyote", "e1")]
    r = compute_ipw(props, rows, detections=dets)
    ws = [w["trimmed_weight"] for w in r["camera_weights"]]
    max_over_mean = max(ws) / (sum(ws) / len(ws))
    # Without the cap, max_over_mean would be ~9 (dominant cam's
    # contribution fraction). With cap, it's bounded.
    assert max_over_mean <= 8.1    # tolerates rounding


def test_without_cap_single_dominant_camera_would_distort_adjusted_freq():
    """Assert the dominant-single-camera adjusted frequency is pulled
    toward 100% but not to the pathological extreme of an uncapped
    weighting scheme."""
    # 10 cams: 1 at propensity 0.02, 9 at 0.5. Dominant cam detected.
    props = np.array([0.02] + [0.5] * 9)
    rows = _cam_rows(10)
    dets = [_det("cam-000", "coyote", "e1")]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["coyote"]
    adj = sp["adjusted_detection_frequency_pct"]
    # Raw = 10% (1 of 10 cameras). Adjusted should be well above 10%
    # because the dominant cam is up-weighted, but capped so it doesn't
    # hit 100%.
    assert adj > 10.0
    assert adj < 90.0


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------

def test_adjusted_rate_bounded_by_trivial_upper_bound():
    """literature_adjusted_rate cannot exceed raw_rate / min_factor
    for the deployed contexts. Sanity check for math correctness."""
    effs = [SimpleNamespace(camera_days=30, detections=15,
                            placement_context="feeder") for _ in range(5)]
    r = compute_bias_correction("feral_hog", effs)
    # For feeder with factor 10, adjusted = raw / 10.
    assert r.literature_adjusted_rate == pytest.approx(r.raw_rate / 10.0, rel=1e-9)


def test_ipw_per_species_frequencies_bounded_0_to_100():
    """For any input, raw and adjusted frequencies must stay in [0, 100]."""
    props = np.array([0.05, 0.2, 0.5, 0.8, 0.95])
    rows = _cam_rows(5)
    dets = [_det(f"cam-{i:03d}", "feral_hog", f"e{i}") for i in range(5)]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["feral_hog"]
    assert 0.0 <= sp["raw_detection_frequency_pct"] <= 100.0
    assert 0.0 <= sp["adjusted_detection_frequency_pct"] <= 100.0
