"""Invasive species damage quantification.

DCF model converting IPW-corrected detection frequencies into
estimated annual crop and property damage using USDA-APHIS base
rates, scaled on a logistic curve and calibrated by ecoregion.

The logistic scaling is critical: damage doesn't increase linearly
with hog density, it saturates. At low densities, animals avoid
each other and damage is sporadic. At high densities, the landscape
is already heavily impacted and marginal damage per animal decreases.

Confidence intervals widen with lower data confidence grades — the
report must be honest about uncertainty.

Caveat from Broadley et al. 2020: density-dependent movement means
cameras can underestimate population declines by up to 30%. Detection
frequency is a relative activity index, not an absolute population
measure.
"""

import math
from typing import Dict, List, Optional

from config import settings
from config.species_reference import SPECIES_REFERENCE


# Confidence interval width by grade — wider = more uncertain
_CI_WIDTH_BY_GRADE = {
    "A":  0.15,   # ±15%
    "A-": 0.20,
    "B+": 0.25,   # ±25%
    "B":  0.30,
    "B-": 0.35,
    "C+": 0.40,   # ±40%
    "C":  0.45,
    "C-": 0.50,
    "D":  0.60,   # ±60%
    "F":  0.75,
}

# Default damage models for invasive species without explicit models
# in SPECIES_REFERENCE. These are conservative estimates.
_DEFAULT_DAMAGE_MODELS = {
    "axis_deer": {
        "source": "Texas Parks & Wildlife estimate",
        "base_cost_per_acre_per_year": 12.50,
        "frequency_multiplier_curve": "logistic",
        "ecoregion_calibration": {
            "edwards_plateau": 1.10,
            "cross_timbers": 0.90,
            "east_central_texas_plains": 0.85,
            "western_gulf_coastal_plain": 0.95,
        },
    },
    "nilgai": {
        "source": "USDA-APHIS South Texas estimate",
        "base_cost_per_acre_per_year": 8.25,
        "frequency_multiplier_curve": "logistic",
        "ecoregion_calibration": {
            "edwards_plateau": 0.70,
            "cross_timbers": 0.50,
            "east_central_texas_plains": 0.60,
            "western_gulf_coastal_plain": 1.20,
        },
    },
}


def logistic_frequency_scale(freq_pct: float) -> float:
    """Logistic damage scaling from detection frequency.

    f(freq) = 1 / (1 + exp(-0.08 * (freq - 50)))

    This maps:
      freq < 30% → ~20% of max damage
      freq = 50% → 50% of max damage
      freq > 70% → ~80% of max damage

    The curve reflects ecological reality: damage doesn't scale
    linearly with animal density. It saturates because:
    1. At low density, damage is patchy and intermittent
    2. At high density, landscape is already degraded
    3. Marginal damage per animal decreases at both extremes
    """
    return 1.0 / (1.0 + math.exp(-0.08 * (freq_pct - 50.0)))


def compute_annual_loss(
    base_cost: float,
    ecoregion_factor: float,
    freq_scale: float,
    acreage: float,
) -> float:
    """Annual estimated loss = base × ecoregion × frequency_scale × acreage."""
    return base_cost * ecoregion_factor * freq_scale * acreage


def compute_npv(annual_loss: float, years: int = 10,
                discount_rate: float = None) -> float:
    """10-year NPV of annual losses at discount rate.

    NPV = sum(annual_loss / (1 + r)^t for t in 1..years)
    """
    # `or` would coerce a legitimate 0.0 discount_rate (= no discount)
    # to the default. Use explicit None-check so callers can request
    # an undiscounted NPV.
    r = settings.DISCOUNT_RATE if discount_rate is None else discount_rate
    return sum(annual_loss / (1 + r) ** t for t in range(1, years + 1))


def compute_fh_exposure_score(
    detection_freq_pct: float,
    days_since_last: int,
    cameras_detecting_fraction: float,
) -> Dict:
    """Feral Hog Exposure Score (0-100).

    Composite of three components:
    - Detection frequency (0.4 weight): higher freq → higher score
    - Recency (0.3 weight): more recent → higher score
    - Spatial extent (0.3 weight): more cameras detecting → higher score

    Each component is normalized to 0-100 before weighting.
    """
    # Detection frequency: linear scale (0-100% → 0-100)
    freq_component = min(100.0, detection_freq_pct)

    # Recency: exponential decay — 0 days = 100, 30 days = ~61, 180 days = ~17
    recency_component = 100.0 * math.exp(-0.008 * days_since_last)

    # Spatial extent: fraction of cameras → 0-100
    spatial_component = min(100.0, cameras_detecting_fraction * 100.0)

    score = (
        0.4 * freq_component
        + 0.3 * recency_component
        + 0.3 * spatial_component
    )
    score = max(0, min(100, round(score)))

    # Interpretation
    if score >= 80:
        interpretation = ("CRITICAL: Very high feral hog activity. "
                          "Significant ongoing property and crop damage likely.")
    elif score >= 60:
        interpretation = ("ELEVATED: Substantial feral hog presence. "
                          "Active damage expected, management recommended.")
    elif score >= 40:
        interpretation = ("MODERATE: Regular feral hog activity detected. "
                          "Periodic damage likely without management.")
    elif score >= 20:
        interpretation = ("LOW: Occasional feral hog activity. "
                          "Minor damage risk, monitoring recommended.")
    else:
        interpretation = ("MINIMAL: Little to no feral hog activity detected. "
                          "Low damage risk at current levels.")

    return {
        "score": score,
        "detection_frequency_component": round(freq_component, 1),
        "recency_component": round(recency_component, 1),
        "spatial_extent_component": round(spatial_component, 1),
        "interpretation": interpretation,
    }


def quantify_damage(
    species_inventory: List[Dict],
    acreage: float,
    ecoregion: str = "edwards_plateau",
    days_since_last_hog: int = 14,
) -> Dict:
    """Compute damage projections for all invasive species in inventory.

    Args:
        species_inventory: From assemble_inventory().
        acreage: Parcel acreage.
        ecoregion: Level III ecoregion key for calibration.
        days_since_last_hog: Days since last feral hog detection
            (for exposure score recency component).

    Returns:
        Dict with:
          - projections: {species_key: DamageProjection dict}
          - fh_exposure_score: FHExposureScore dict (if hogs present)
    """
    projections = {}
    fh_exposure = None

    for sp in species_inventory:
        if not sp["invasive"]:
            continue

        sp_key = sp["species_key"]
        ref = SPECIES_REFERENCE.get(sp_key, {})
        dmg_model = ref.get("damage_model",
                            _DEFAULT_DAMAGE_MODELS.get(sp_key))

        if not dmg_model:
            continue

        base_cost = dmg_model["base_cost_per_acre_per_year"]
        eco_cal = dmg_model.get("ecoregion_calibration", {})
        eco_factor = eco_cal.get(ecoregion, 1.0)

        det_freq = sp["detection_frequency_pct"]
        freq_scale = logistic_frequency_scale(det_freq)

        annual_loss = compute_annual_loss(
            base_cost, eco_factor, freq_scale, acreage)
        npv = compute_npv(annual_loss)

        # Confidence interval
        grade = sp["confidence_grade"]
        ci_pct = _CI_WIDTH_BY_GRADE.get(grade, 0.50)
        ci_low = annual_loss * (1.0 - ci_pct)
        ci_high = annual_loss * (1.0 + ci_pct)

        methodology = (
            f"USDA-APHIS base rates ({dmg_model['source']})"
            f" calibrated to {ecoregion.replace('_', ' ').title()},"
            f" IPW-corrected detection frequency,"
            f" logistic damage scaling"
        )

        projections[sp_key] = {
            "species_key": sp_key,
            "common_name": ref.get("common_name", sp_key),
            "base_cost_per_acre": base_cost,
            "ecoregion_calibration_factor": eco_factor,
            "frequency_scale": round(freq_scale, 4),
            "detection_frequency_pct": det_freq,
            "acreage": acreage,
            "estimated_annual_loss": round(annual_loss, 0),
            "ten_year_npv": round(npv, 0),
            "confidence_grade": grade,
            "confidence_interval_pct": round(ci_pct * 100, 0),
            "confidence_interval_low": round(ci_low, 0),
            "confidence_interval_high": round(ci_high, 0),
            "methodology": methodology,
            "broadley_caveat": (
                "Detection frequency is a relative activity index, "
                "not absolute density. Broadley et al. 2020 showed "
                "density-dependent movement can cause cameras to "
                "underestimate population declines by up to 30%."),
        }

        # Feral hog exposure score
        if sp_key == "feral_hog":
            cameras_frac = (sp["cameras_detected"]
                            / sp["cameras_total"]
                            if sp["cameras_total"] > 0 else 0)
            fh_exposure = compute_fh_exposure_score(
                det_freq, days_since_last_hog, cameras_frac)

    return {
        "projections": projections,
        "fh_exposure_score": fh_exposure,
    }
