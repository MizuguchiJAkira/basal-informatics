"""Random Encounter Model (REM) density estimator with bootstrap CI.

Per Rowcliffe, Field, Turvey & Carbone 2008 (J. Appl. Ecol.):

    D = (y/t) * pi / (v * r * (2 + theta))

where
    D     = density (animals / km^2)
    y/t   = detections per camera-day (the camera-trap rate)
    v     = average daily travel distance (km / day) [species-specific]
    r     = camera detection radius (km)
    theta = camera detection angle (radians)

REM does not require individual identification, which is essential for
hogs (no reliable natural marks at population scale) and lets us produce
a defensible density estimate from any well-deployed camera-trap survey.

This module:
  - exposes ``estimate_density(...)`` for a single species at a single site
  - exposes ``estimate_for_property(...)`` for the full property dashboard
  - produces a recommendation flag (sufficient / recommend_survey /
    insufficient_data) per the thresholds in config/settings.py
  - emits a list of plain-language caveats describing assumption violations
    or sample-size concerns, suitable for direct UI display

Inputs are kept agnostic of the ORM so this module stays unit-testable
in isolation. Callers (the dashboard API) translate DetectionSummary rows
into the simple dataclasses below.

References:
  Rowcliffe et al. 2008. Estimating animal density using camera traps
    without the need for individual recognition. J. Appl. Ecol.
  Rowcliffe et al. 2012. Bias in estimating animal travel distance: the
    effect of sampling frequency. Methods in Ecology and Evolution.
  Kolowski & Forrester 2017. Camera trap placement and the potential for
    bias due to trails and other features. PLOS ONE.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from config import settings

# Recommendation enum (just strings for transport convenience).
RECOMMEND_SUFFICIENT = "sufficient_for_decision"
RECOMMEND_SURVEY = "recommend_supplementary_survey"
RECOMMEND_INSUFFICIENT = "insufficient_data"


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------

@dataclass
class CameraSurveyEffort:
    """Per-camera effort + detection counts for a single species/period.

    Kept ORM-agnostic so this can be unit-tested with synthetic data.
    """
    camera_id: int
    camera_days: float                 # # of days the camera was active in the period
    detections: int                    # # of independent events (or photos; caller decides)
    placement_context: Optional[str] = None  # for IPW caveat surfacing


@dataclass
class DensityEstimate:
    """Output of estimate_density(). All densities in animals/km^2."""
    species_key: str
    detection_rate: Optional[float]            # mean y/t across cameras (events / camera-day)
    detection_rate_adjusted: Optional[float]   # IPW-corrected (None until bias module wires in)
    density_mean: Optional[float]              # REM point estimate
    density_ci_low: Optional[float]            # bootstrap 2.5%
    density_ci_high: Optional[float]           # bootstrap 97.5%
    bootstrap_n: int
    n_cameras: int
    total_camera_days: float
    total_detections: int
    recommendation: str                        # one of the RECOMMEND_* constants
    caveats: List[str] = field(default_factory=list)
    method_notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core REM math
# ---------------------------------------------------------------------------

def _rem_density(detection_rate: float, v_km_day: float,
                 r_km: float, theta_rad: float) -> float:
    """REM point estimator. detection_rate in events/camera-day.

    Returns density in animals/km^2. Raises if any denominator term is
    non-positive (caller should ensure positive species params upstream).
    """
    if detection_rate < 0:
        raise ValueError(f"detection_rate must be >= 0 (got {detection_rate})")
    if v_km_day <= 0 or r_km <= 0 or theta_rad <= 0:
        raise ValueError("v, r, theta must all be positive")
    return (detection_rate * math.pi) / (v_km_day * r_km * (2.0 + theta_rad))


def _bootstrap_density(efforts: Sequence[CameraSurveyEffort],
                       v_km_day: float, v_sd: float,
                       r_km: float, theta_rad: float,
                       n: int = 1000,
                       rng: Optional[random.Random] = None
                       ) -> List[float]:
    """Nonparametric bootstrap over cameras, with parametric perturbation
    of v (truncated normal) to propagate movement-distance uncertainty.

    Per Rowcliffe 2012: bootstrapping cameras (the survey unit) is the
    primary uncertainty source; v_sd lets us also pass through the
    published inter-individual variability in daily travel distance.

    Returns a list of bootstrap density samples (animals/km^2).
    """
    if rng is None:
        rng = random.Random()
    if not efforts:
        return []

    samples: List[float] = []
    cams = list(efforts)
    for _ in range(n):
        # Resample cameras with replacement (the standard REM approach).
        boot = [cams[rng.randrange(len(cams))] for _ in range(len(cams))]
        boot_dets = sum(c.detections for c in boot)
        boot_days = sum(c.camera_days for c in boot)
        if boot_days <= 0:
            continue
        rate = boot_dets / boot_days
        # Perturb v parametrically; clamp to >= 0.1 km/day to avoid div-by-0.
        v_sample = max(0.1, rng.gauss(v_km_day, v_sd)) if v_sd > 0 else v_km_day
        try:
            samples.append(_rem_density(rate, v_sample, r_km, theta_rad))
        except ValueError:
            continue
    return samples


def _percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile (NumPy default behavior)."""
    if not values:
        raise ValueError("empty values")
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    rank = p / 100.0 * (len(s) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(s) - 1)
    frac = rank - lo
    return s[lo] * (1 - frac) + s[hi] * frac


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

def _classify_recommendation(total_camera_days: float,
                             total_detections: int,
                             ci_low: Optional[float],
                             ci_high: Optional[float]) -> str:
    """Map data sufficiency + CI width to a recommendation flag."""
    if (total_camera_days < settings.MIN_CAMERA_DAYS_FOR_DENSITY
            or total_detections < settings.MIN_DETECTIONS_FOR_DENSITY):
        return RECOMMEND_INSUFFICIENT

    if ci_low is None or ci_high is None or ci_low <= 0:
        # Can't compute a meaningful ratio.
        return RECOMMEND_SURVEY

    ratio = ci_high / ci_low
    if ratio > settings.DENSITY_CI_RATIO_THRESHOLD:
        return RECOMMEND_SURVEY
    return RECOMMEND_SUFFICIENT


def _caveats_from(efforts: Sequence[CameraSurveyEffort],
                  total_camera_days: float,
                  total_detections: int) -> List[str]:
    """Build the plain-language caveats list."""
    out: List[str] = []
    if total_camera_days < settings.MIN_CAMERA_DAYS_FOR_DENSITY:
        out.append(
            f"Sample size below density-estimate threshold: "
            f"{total_camera_days:.0f} camera-days "
            f"(min {settings.MIN_CAMERA_DAYS_FOR_DENSITY})."
        )
    if total_detections < settings.MIN_DETECTIONS_FOR_DENSITY:
        out.append(
            f"Detection count below threshold: {total_detections} "
            f"(min {settings.MIN_DETECTIONS_FOR_DENSITY})."
        )
    placements = {e.placement_context for e in efforts if e.placement_context}
    biased = placements & {"feeder", "trail", "water"}
    if biased:
        ctx = ", ".join(sorted(biased))
        out.append(
            f"Cameras at non-random placements ({ctx}) violate REM's "
            "movement-independence assumption. Inverse propensity weighting "
            "(Kolowski & Forrester 2017) corrects for residual bias but does "
            "not eliminate it."
        )
    if len(efforts) < 3:
        out.append(
            f"Only {len(efforts)} cameras contributed detections; bootstrap "
            "CI is correspondingly wide."
        )
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def estimate_density(species_key: str,
                     efforts: Sequence[CameraSurveyEffort],
                     r_km: Optional[float] = None,
                     theta_rad: Optional[float] = None,
                     bootstrap_n: Optional[int] = None,
                     rng: Optional[random.Random] = None
                     ) -> DensityEstimate:
    """REM density estimate for one species + bootstrap 95% CI.

    Returns a DensityEstimate with density_* set when species-specific
    movement parameters are available, or with density_* = None and a
    caveat explaining why otherwise.
    """
    r_km = r_km if r_km is not None else (settings.CAMERA_DETECTION_RADIUS_M / 1000.0)
    theta_rad = theta_rad if theta_rad is not None else settings.CAMERA_DETECTION_ANGLE_RAD
    bootstrap_n = bootstrap_n or settings.REM_BOOTSTRAP_N

    total_camera_days = sum(e.camera_days for e in efforts)
    total_detections = sum(e.detections for e in efforts)
    n_cameras = len(efforts)

    # Detection rate (events per camera-day). We don't IPW-adjust here;
    # bias/ipw.py will call us with adjusted rates once that lands.
    if total_camera_days > 0:
        detection_rate = total_detections / total_camera_days
    else:
        detection_rate = None

    movement = settings.SPECIES_MOVEMENT.get(species_key)
    method_notes: List[str] = []
    caveats = _caveats_from(efforts, total_camera_days, total_detections)

    # Species without a published v: detection-rate-only output.
    if movement is None:
        method_notes.append(
            f"No published daily-travel-distance value for {species_key}; "
            "density estimate omitted. Detection-rate index returned only."
        )
        return DensityEstimate(
            species_key=species_key,
            detection_rate=detection_rate,
            detection_rate_adjusted=None,
            density_mean=None,
            density_ci_low=None,
            density_ci_high=None,
            bootstrap_n=0,
            n_cameras=n_cameras,
            total_camera_days=total_camera_days,
            total_detections=total_detections,
            recommendation=RECOMMEND_INSUFFICIENT,
            caveats=caveats,
            method_notes=method_notes,
        )

    v_km_day = movement["v_km_day"]
    v_sd = movement.get("v_sd", 0.0)
    method_notes.append(
        f"Daily travel distance: v = {v_km_day} km/day (sd {v_sd}). "
        f"Source: {movement.get('source', 'literature')}."
    )

    if detection_rate is None or n_cameras == 0:
        return DensityEstimate(
            species_key=species_key,
            detection_rate=detection_rate,
            detection_rate_adjusted=None,
            density_mean=None,
            density_ci_low=None,
            density_ci_high=None,
            bootstrap_n=0,
            n_cameras=n_cameras,
            total_camera_days=total_camera_days,
            total_detections=total_detections,
            recommendation=RECOMMEND_INSUFFICIENT,
            caveats=caveats + ["No camera-days recorded for this period."],
            method_notes=method_notes,
        )

    # Point estimate.
    density_mean = _rem_density(detection_rate, v_km_day, r_km, theta_rad)

    # Bootstrap CI.
    samples = _bootstrap_density(
        efforts, v_km_day, v_sd, r_km, theta_rad,
        n=bootstrap_n, rng=rng,
    )
    if samples:
        ci_low = _percentile(samples, 2.5)
        ci_high = _percentile(samples, 97.5)
    else:
        ci_low = ci_high = None

    recommendation = _classify_recommendation(
        total_camera_days, total_detections, ci_low, ci_high)

    return DensityEstimate(
        species_key=species_key,
        detection_rate=detection_rate,
        detection_rate_adjusted=None,
        density_mean=density_mean,
        density_ci_low=ci_low,
        density_ci_high=ci_high,
        bootstrap_n=len(samples),
        n_cameras=n_cameras,
        total_camera_days=total_camera_days,
        total_detections=total_detections,
        recommendation=recommendation,
        caveats=caveats,
        method_notes=method_notes,
    )


def estimate_for_property(efforts_by_species: Dict[str, Sequence[CameraSurveyEffort]],
                          rng: Optional[random.Random] = None
                          ) -> List[DensityEstimate]:
    """Estimate density for every species in the survey, sorted by
    descending density_mean (None last)."""
    out = [estimate_density(sp, efforts, rng=rng)
           for sp, efforts in efforts_by_species.items()]
    out.sort(
        key=lambda e: (e.density_mean is None, -(e.density_mean or 0.0))
    )
    return out
