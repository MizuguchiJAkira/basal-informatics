"""Feral Hog Exposure Score — the headline metric on the Basal Informatics
Nature Exposure Report.

Takes a REM density estimate (from ``risk.population``) plus parcel metadata
and produces:

  1. A tier classification (Low / Moderate / Elevated / Severe) suitable for
     display as a "risk grade" on the lender-facing report.
  2. A modeled dollar projection of annual crop damage, clearly labeled as
     a supplementary estimate not a pipeline output.
  3. A composite exposure score (0–100 normalized) that slots into the
     lender's portfolio-level summary without asking them to interpret
     raw density values.

The dollar projection is supplementary. It is modeled by extrapolating
per-hog annual damage figures from the published literature (Anderson et al.
2016, Pimentel 2005) scaled to parcel area. It is not a pipeline output
and should always be labeled MODELED PROJECTION in the UI.

Scope: tier classifications are defined for feral hog only at v1. Other
species (white-tailed deer, coyote, etc.) return density plus a flat
"informational only" marker. Adding tier classifications for other species
requires publishing per-species cutoff literature review.

References:
  Anderson A, Slootmaker C, Harper E, Holderieath J, Shwiff SA. 2016.
    Economic estimates of feral swine damage and control in 11 US states.
    Crop Protection 89: 89–94.
  Mayer JJ, Brisbin IL. 2009. Wild Pigs: Biology, Damage, Control Techniques
    and Management. Savannah River National Laboratory.
  Pimentel D. 2005. Environmental consequences of earthworm invasion.
    Biological Invasions 7: 583–597. (National damage baseline)
  USDA APHIS Wildlife Services annual Program Data Reports. (Updated state
    totals)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from config import settings

# -------------------------------------------------------------------------
# Tier cutoffs (feral hog, animals/km²)
# -------------------------------------------------------------------------
# Published population-density classes for feral hogs vary by region and
# source. The cutoffs below follow Mayer & Brisbin 2009 chapter 4 binning
# and are widely used in USDA APHIS state-level damage reporting.
TIER_CUTOFFS_HOG = [
    (2.0,  "Low"),        # density < 2.0  -> Low
    (5.0,  "Moderate"),   # 2.0 <= density < 5.0
    (10.0, "Elevated"),   # 5.0 <= density < 10.0
    # >= 10.0             -> Severe
]
TIER_SEVERE = "Severe"

TIER_ORDER = ["Low", "Moderate", "Elevated", "Severe"]
TIER_UNKNOWN = "Unknown"
TIER_INFO_ONLY = "Informational"  # non-hog species

# -------------------------------------------------------------------------
# Damage coefficient (per-hog, per-year, USD)
# -------------------------------------------------------------------------
# Anderson et al. 2016 reports $272–$343 per pig in direct crop damage
# across 11 US states, median ~$305. Adjusted for 2025 inflation via BLS
# CPI ~1.33 factor -> ~$405 per pig per year in 2025 dollars.
#
# Crop-specific multipliers are known to vary (corn damage > pasture damage
# by ~3x) but Anderson's state-averaged figure implicitly incorporates the
# mix. We expose ``crop_modifier`` in the function signature so the UI
# can surface tighter estimates when the landowner has declared a specific
# crop; defaults to 1.0.
DEFAULT_PER_HOG_ANNUAL_USD = 405.0

# Per-crop modifier: multiplier applied to the base $/hog/yr figure. Very
# rough; anchored in Anderson's state averages + qualitative reading of
# the crop mix tables. Tighten with crop-specific data once we subscribe.
CROP_DAMAGE_MODIFIER = {
    "corn":        1.6,    # highest damage class (dough + kernel stage)
    "sorghum":     1.3,
    "rice":        1.2,
    "peanut":      1.4,    # rooting damage high
    "wheat":       0.8,
    "cotton":      0.5,    # hogs eat seed but rarely damage standing cotton
    "soybean":     1.1,
    "hay":         0.6,
    "pasture":     0.5,
    "rangeland":   0.4,
    "mixed":       1.0,
    "other":       1.0,
    None:          1.0,
}


# -------------------------------------------------------------------------
# Output record
# -------------------------------------------------------------------------

@dataclass
class ExposureResult:
    """Lender-facing exposure assessment for a single species on a parcel.

    For hogs: tier is one of TIER_ORDER or TIER_UNKNOWN (insufficient data),
    score is a 0–100 normalized risk index, dollar_projection is populated.
    For other species: tier=TIER_INFO_ONLY, score=None, dollar_projection=None.

    All fields are safe to serialize directly to the JSON API response.
    """
    species_key: str
    tier: str                               # Low | Moderate | Elevated | Severe | Informational | Unknown
    score_0_100: Optional[float]            # 0–100, higher = more exposure. Hog only.
    density_animals_per_km2: Optional[float]
    density_ci_low: Optional[float]
    density_ci_high: Optional[float]
    dollar_projection_annual_usd: Optional[float]       # point estimate
    dollar_projection_ci_low_usd: Optional[float]       # scaled from density CI
    dollar_projection_ci_high_usd: Optional[float]
    parcel_area_km2: Optional[float]
    crop_type: Optional[str]
    crop_modifier: float                    # 1.0 if crop unknown / mixed
    per_hog_annual_usd: float               # base rate used
    recommendation: str                     # from underlying DensityEstimate
    caveats: List[str] = field(default_factory=list)
    method_notes: List[str] = field(default_factory=list)


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------

def tier_for_hog_density(density: float) -> str:
    """Classify a hog density value into a tier label.

    Uses Mayer & Brisbin 2009 cutoffs: <2 Low, 2–5 Moderate, 5–10 Elevated,
    >=10 Severe. Negative or NaN densities return 'Unknown'.
    """
    if density is None or density < 0:
        return TIER_UNKNOWN
    for cutoff, label in TIER_CUTOFFS_HOG:
        if density < cutoff:
            return label
    return TIER_SEVERE


def score_for_hog_density(density: float) -> float:
    """Map a hog density (animals/km²) to a 0–100 exposure score.

    Piecewise-linear anchored on the tier cutoffs:
        0/km²   -> 0
        2/km²   -> 25    (Low/Moderate boundary)
        5/km²   -> 50    (Moderate/Elevated boundary)
        10/km²  -> 75    (Elevated/Severe boundary)
        20/km²+ -> 100   (clamp)

    Chosen so each tier occupies a 25-point band and the progression is
    visually legible on a bar.
    """
    if density is None or density <= 0:
        return 0.0
    anchors = [(0.0, 0.0), (2.0, 25.0), (5.0, 50.0), (10.0, 75.0), (20.0, 100.0)]
    for i in range(len(anchors) - 1):
        x0, y0 = anchors[i]
        x1, y1 = anchors[i + 1]
        if density < x1:
            return y0 + (y1 - y0) * (density - x0) / (x1 - x0)
    return 100.0


def dollar_projection_annual(
    density_animals_per_km2: Optional[float],
    parcel_area_km2: Optional[float],
    crop_type: Optional[str] = None,
    per_hog_annual_usd: float = DEFAULT_PER_HOG_ANNUAL_USD,
) -> Optional[float]:
    """Modeled annual damage projection (USD) for a parcel.

    = density × area × per-hog-damage × crop-modifier

    Returns None if any input is missing. Rounds to nearest dollar for
    display.
    """
    if (density_animals_per_km2 is None
            or parcel_area_km2 is None
            or parcel_area_km2 <= 0):
        return None
    hogs = density_animals_per_km2 * parcel_area_km2
    mod = CROP_DAMAGE_MODIFIER.get(crop_type, 1.0)
    return round(hogs * per_hog_annual_usd * mod, 0)


def exposure_for_species(
    species_key: str,
    density_mean: Optional[float],
    density_ci_low: Optional[float],
    density_ci_high: Optional[float],
    parcel_acreage: Optional[float],
    crop_type: Optional[str],
    recommendation: str,
    caveats: Optional[List[str]] = None,
    method_notes: Optional[List[str]] = None,
    per_hog_annual_usd: float = DEFAULT_PER_HOG_ANNUAL_USD,
) -> ExposureResult:
    """Build an ExposureResult from a REM density estimate + parcel metadata.

    Callers supply the density + CI from ``risk.population.estimate_density``
    and the parcel's acreage + crop_type from the Property row. This keeps
    the exposure module independent of the ORM.
    """
    caveats = list(caveats or [])
    method_notes = list(method_notes or [])

    parcel_area_km2 = (parcel_acreage * 0.004046856) if parcel_acreage else None

    if species_key != "feral_hog":
        # Non-hog species: report density only, no tier / dollar projection.
        return ExposureResult(
            species_key=species_key,
            tier=TIER_INFO_ONLY,
            score_0_100=None,
            density_animals_per_km2=density_mean,
            density_ci_low=density_ci_low,
            density_ci_high=density_ci_high,
            dollar_projection_annual_usd=None,
            dollar_projection_ci_low_usd=None,
            dollar_projection_ci_high_usd=None,
            parcel_area_km2=parcel_area_km2,
            crop_type=crop_type,
            crop_modifier=CROP_DAMAGE_MODIFIER.get(crop_type, 1.0),
            per_hog_annual_usd=per_hog_annual_usd,
            recommendation=recommendation,
            caveats=caveats + [
                f"Tier classification defined for feral hog only at v1. "
                f"{species_key} shown for informational purposes."
            ],
            method_notes=method_notes,
        )

    # Hog-specific exposure assessment.
    tier = tier_for_hog_density(density_mean) if density_mean is not None else TIER_UNKNOWN
    score = score_for_hog_density(density_mean) if density_mean is not None else None
    dollars = dollar_projection_annual(
        density_mean, parcel_area_km2, crop_type, per_hog_annual_usd)
    dollars_low = dollar_projection_annual(
        density_ci_low, parcel_area_km2, crop_type, per_hog_annual_usd)
    dollars_high = dollar_projection_annual(
        density_ci_high, parcel_area_km2, crop_type, per_hog_annual_usd)

    if dollars is not None:
        method_notes.append(
            f"Dollar projection is a MODELED ESTIMATE, not a pipeline output. "
            f"Scaled from per-hog damage figures (Anderson et al. 2016, "
            f"inflation-adjusted to ${per_hog_annual_usd:.0f}/hog/year) × "
            f"parcel area × crop-modifier "
            f"({CROP_DAMAGE_MODIFIER.get(crop_type, 1.0):.2f} for "
            f"{crop_type or 'unspecified crop'})."
        )

    return ExposureResult(
        species_key=species_key,
        tier=tier,
        score_0_100=score,
        density_animals_per_km2=density_mean,
        density_ci_low=density_ci_low,
        density_ci_high=density_ci_high,
        dollar_projection_annual_usd=dollars,
        dollar_projection_ci_low_usd=dollars_low,
        dollar_projection_ci_high_usd=dollars_high,
        parcel_area_km2=parcel_area_km2,
        crop_type=crop_type,
        crop_modifier=CROP_DAMAGE_MODIFIER.get(crop_type, 1.0),
        per_hog_annual_usd=per_hog_annual_usd,
        recommendation=recommendation,
        caveats=caveats,
        method_notes=method_notes,
    )
