"""Unit tests for bias/ipw.py — the per-detection-event IPW pipeline.

Distinct from bias/placement_ipw.py (REM-side per-camera-rate
correction, already tested in test_placement_ipw.py). This module
handles the Strecker detection-frequency correction — takes
propensity scores + camera rows + Detection objects, returns
per-species adjusted detection frequencies with the 8:1 weight cap
(Lee et al. 2011 small-sample trimming).

Covers Layer 1 of the exhaustive test plan:
  - 8:1 weight cap activation / non-activation
  - Single camera degenerate case
  - Identical propensity scores (no trimming needed)
  - Zero detections (all species at 0%)
  - Extreme propensity scores (0.001, 0.999 — hit the 0.01/0.99 floor/ceil)
  - Percentile trimming kicks in at n >= 30
  - Weights normalize to n_cameras
"""

from types import SimpleNamespace

import numpy as np
import pytest

from bias.ipw import compute_ipw, _build_camera_species_map


def _cam_rows(n, contexts=None):
    contexts = contexts or ["random"] * n
    return [{"point_id": f"cam-{i:03d}",
             "placement_context": contexts[i]}
            for i in range(n)]


def _detection(camera_id, species_key, event_id):
    return SimpleNamespace(
        camera_id=camera_id,
        species_key=species_key,
        independent_event_id=event_id,
    )


# ---------------------------------------------------------------------------
# 8:1 weight cap
# ---------------------------------------------------------------------------

def test_weight_cap_activates_when_ratio_exceeds_8():
    """With 0.1 vs 0.9 propensity the raw stabilized weight ratio is
    0.9/0.1 = 9. The 8:1 cap trims it to 8:1."""
    props = np.array([0.1, 0.9, 0.5, 0.5])
    rows = _cam_rows(4)
    r = compute_ipw(props, rows, detections=[])
    weights = [w["trimmed_weight"] for w in r["camera_weights"]]
    w_ratio = max(weights) / min(weights)
    assert w_ratio <= 8.0 + 1e-6, f"weight ratio {w_ratio} exceeds 8:1 cap"


def test_weight_cap_noop_when_ratio_already_below_8():
    """Propensity 0.2 vs 0.7 → ratio 0.7/0.2 = 3.5, cap should not
    trigger (trimmed weight ratio stays ≈ 3.5, within rounding)."""
    props = np.array([0.2, 0.3, 0.5, 0.7])
    rows = _cam_rows(4)
    r = compute_ipw(props, rows, detections=[])
    ws = [w["trimmed_weight"] for w in r["camera_weights"]]
    trimmed_ratio = max(ws) / min(ws)
    # Rounding on the per-weight .round(4) introduces up to ~1% drift.
    assert trimmed_ratio == pytest.approx(3.5, rel=0.02)
    assert trimmed_ratio < 8.0


def test_weight_cap_with_extreme_scenario():
    """Construct a single dominant camera: 1 camera at propensity 0.02,
    19 at propensity 0.5. Without the cap the first camera's weight is
    25× any other's. With cap, it's 8×."""
    props = np.array([0.02] + [0.5] * 19)
    rows = _cam_rows(20)
    r = compute_ipw(props, rows, detections=[])
    ws = sorted(w["trimmed_weight"] for w in r["camera_weights"])
    ratio = ws[-1] / ws[0]
    # Rounding of per-weight round(..., 4) allows the reconstructed ratio
    # to drift above 8.0 by ~0.05. The invariant is that the uncapped
    # ratio (≥25:1 here) has been dramatically compressed.
    assert ratio <= 8.1
    assert ratio >= 7.9    # confirm the cap did something


# ---------------------------------------------------------------------------
# Degenerate camera-count cases
# ---------------------------------------------------------------------------

def test_single_camera_does_not_divide_by_zero():
    """One camera, one species — raw_freq should be 100% if detected."""
    props = np.array([0.5])
    rows = _cam_rows(1)
    dets = [_detection("cam-000", "feral_hog", "e1")]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["feral_hog"]
    assert sp["raw_detection_frequency_pct"] == 100.0
    assert sp["adjusted_detection_frequency_pct"] == 100.0


def test_identical_propensity_scores_yield_unit_weights():
    """When every camera has the same propensity, stabilized weights
    are all equal and (after normalization) == 1.0 for every camera."""
    props = np.full(10, 0.4)
    rows = _cam_rows(10)
    r = compute_ipw(props, rows, detections=[])
    weights = [w["trimmed_weight"] for w in r["camera_weights"]]
    assert all(abs(w - 1.0) < 1e-9 for w in weights)


def test_zero_detections_produces_empty_per_species():
    props = np.array([0.5] * 5)
    rows = _cam_rows(5)
    r = compute_ipw(props, rows, detections=[])
    assert r["per_species"] == {}


def test_every_camera_detects_yields_100pct():
    """All cameras see the species → raw = adjusted = 100%."""
    props = np.array([0.3, 0.5, 0.7, 0.9])
    rows = _cam_rows(4)
    dets = [_detection(f"cam-{i:03d}", "feral_hog", f"e{i}")
            for i in range(4)]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["feral_hog"]
    assert sp["raw_detection_frequency_pct"] == 100.0
    assert sp["adjusted_detection_frequency_pct"] == 100.0


# ---------------------------------------------------------------------------
# Propensity floor / ceiling
# ---------------------------------------------------------------------------

def test_extreme_low_propensity_is_floored_to_001():
    """A camera with propensity 0.0005 should be treated as if its
    propensity is 0.01 (the floor)."""
    props = np.array([0.0005, 0.5, 0.5, 0.5])
    rows = _cam_rows(4)
    r = compute_ipw(props, rows, detections=[])
    # The floored camera's raw weight is 1/0.01 = 100.
    w0 = r["camera_weights"][0]["raw_weight"]
    assert w0 == pytest.approx(100.0, rel=1e-3)


def test_extreme_high_propensity_is_capped_to_099():
    props = np.array([0.9995, 0.5, 0.5, 0.5])
    rows = _cam_rows(4)
    r = compute_ipw(props, rows, detections=[])
    # 1/0.99 ≈ 1.0101
    w0 = r["camera_weights"][0]["raw_weight"]
    assert w0 == pytest.approx(1.0101, rel=1e-3)


# ---------------------------------------------------------------------------
# Normalization: trimmed weights sum to n_cameras
# ---------------------------------------------------------------------------

def test_trimmed_weights_sum_to_n_cameras():
    """The normalization step multiplies by n/sum so the weights sum to
    n. The per-weight round(., 4) can drift the sum by up to ~5e-5 × n
    which is irrelevant statistically."""
    props = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    rows = _cam_rows(5)
    r = compute_ipw(props, rows, detections=[])
    total = sum(w["trimmed_weight"] for w in r["camera_weights"])
    assert total == pytest.approx(len(rows), abs=1e-3)


# ---------------------------------------------------------------------------
# n >= 30 triggers percentile trimming
# ---------------------------------------------------------------------------

def test_percentile_trimming_kicks_in_at_30_cameras():
    """n >= 30 applies 5th/95th percentile trimming. Construct 30
    propensities with a single outlier and verify the outlier is trimmed."""
    props = np.concatenate([np.array([0.02]), np.full(29, 0.5)])
    rows = _cam_rows(30)
    r = compute_ipw(props, rows, detections=[])
    stats = r["weight_stats"]
    # The outlier's raw weight would be 1/0.02 = 50, but percentile trim
    # pulls it in. Max trimmed weight should be far below 50.
    assert stats["max_weight"] < 20.0


# ---------------------------------------------------------------------------
# Adjustment direction for biased placements
# ---------------------------------------------------------------------------

def test_high_freq_on_low_propensity_cameras_increases_adjusted_freq():
    """A species detected ONLY at low-propensity (unusual) cameras
    should have adjusted freq HIGHER than raw, because IPW upweights
    those rare placements."""
    # 10 cameras: 2 at low propensity (0.1), 8 at high (0.9).
    props = np.array([0.1, 0.1, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9])
    rows = _cam_rows(10)
    # Species detected ONLY at the 2 low-propensity cams.
    dets = [_detection("cam-000", "coyote", "e1"),
            _detection("cam-001", "coyote", "e2")]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["coyote"]
    # Raw: 2/10 = 20%. Adjusted should be higher (upweighting rare cams).
    assert sp["raw_detection_frequency_pct"] == 20.0
    assert sp["adjusted_detection_frequency_pct"] > 20.0


def test_high_freq_on_high_propensity_cameras_decreases_adjusted_freq():
    """Species detected only at high-propensity (typical/feeder)
    cameras should have adjusted freq LOWER than raw."""
    props = np.array([0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
    rows = _cam_rows(10)
    dets = [_detection("cam-000", "feral_hog", "e1"),
            _detection("cam-001", "feral_hog", "e2")]
    r = compute_ipw(props, rows, detections=dets)
    sp = r["per_species"]["feral_hog"]
    assert sp["raw_detection_frequency_pct"] == 20.0
    assert sp["adjusted_detection_frequency_pct"] < 20.0


# ---------------------------------------------------------------------------
# Event deduplication
# ---------------------------------------------------------------------------

def test_duplicate_event_ids_counted_once():
    """Two Detection rows with the same independent_event_id must not
    double-count the camera as a detector."""
    props = np.array([0.5, 0.5])
    rows = _cam_rows(2)
    dets = [
        _detection("cam-000", "feral_hog", "e1"),
        _detection("cam-000", "feral_hog", "e1"),   # duplicate event
    ]
    cam_map = _build_camera_species_map(["cam-000", "cam-001"], dets)
    assert cam_map["cam-000"]["feral_hog"] == 1


def test_empty_event_id_skipped():
    """Detection with empty independent_event_id must be skipped."""
    dets = [
        _detection("cam-000", "feral_hog", ""),
        _detection("cam-000", "feral_hog", None),
    ]
    cam_map = _build_camera_species_map(["cam-000"], dets)
    assert cam_map == {}
