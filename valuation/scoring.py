"""Stage 7 risk scoring — rule-based, reproducible, decomposable.

Constraints (non-negotiable, see specification):

    1. Rule-based. No ML, no opaque heuristics.
    2. Every score decomposes into named drivers with evidence strings.
       The factors enumerated in ``FACTORS`` are recorded for every
       parcel — both triggered and non-triggered — so the report can
       say "considered, did not contribute" rather than implying the
       rubric is shorter than it is.
    3. Reproducibility. ``score(...)`` is a pure function of its inputs.
       No ``datetime.now()`` is read inside the scoring path; ``today``
       is passed in by the caller. Same arguments → same output.
    4. "Indicative risk band," never a probability or percentage. The
       band is the surface ; the underlying float is for ranking.

Output shape (matches the JSON contract documented at the top of
``valuation/__init__.py``)::

    RiskScore(
        value=0.55,                         # 0.000 - 1.000
        band="elevated",                    # low | moderate | elevated | high
        drivers=[
            DriverResult(
                key="ownership_change_recent",
                weight=Decimal("0.400"),
                triggered=True,
                evidence="Deed transfer 2025-11-22 (5 mo. before as-of).",
            ),
            ...
        ],
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable

from valuation.adapters.cad import CADRecord
from valuation.reference import ECOREGION_INTENSITY


# -- Factor rubric ---------------------------------------------------------
#
# Weights MUST sum to Decimal("1.000"). This invariant is asserted at
# import time so a future edit can't silently produce a rubric that
# scales scores past 1.0.
#
# Each factor is described once here; the evaluator function takes the
# bundled scoring input and returns (triggered: bool, evidence: str).

@dataclass(frozen=True)
class FactorSpec:
    key: str
    weight: Decimal
    label: str           # human-readable name for the report
    description: str     # one-sentence rationale ("why this matters")


FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec(
        key="ownership_change_recent",
        weight=Decimal("0.400"),
        label="Recent ownership change",
        description=(
            "A deed transfer in the past 12 months commonly precedes "
            "a 1-d-1 valuation challenge. New owners who don't continue "
            "qualifying ag use can lose the special-use appraisal at "
            "the next reapplication window."
        ),
    ),
    FactorSpec(
        key="classification_vulnerable",
        weight=Decimal("0.200"),
        label="Classification vulnerability",
        description=(
            "1-d-1 (open-space agricultural) parcels are subject to "
            "annual reapplication and intensity-of-use review. "
            "1-d-1(w) (wildlife) parcels carry the same exposure but "
            "the qualifying activity is decoupled from market ag."
        ),
    ),
    FactorSpec(
        key="assessed_market_spread_extreme",
        weight=Decimal("0.150"),
        label="Extreme assessed/market spread",
        description=(
            "When market value runs more than 100× the productivity-"
            "based assessed value, loss of special-use appraisal would "
            "reset the assessed value sharply upward — concentrating "
            "the dollar exposure on this parcel."
        ),
    ),
    FactorSpec(
        key="drought_pdsi_24mo",
        weight=Decimal("0.150"),
        label="Multi-year drought",
        description=(
            "Sustained drought (PDSI ≤ -3 across two-thirds of the "
            "rolling 24-month window) erodes the stocking rates and "
            "yields that the productivity appraisal is built on. "
            "Persistent drought is a leading indicator of "
            "intensity-of-use challenges."
        ),
    ),
    FactorSpec(
        key="intensity_below_ecoregion_standard",
        weight=Decimal("0.100"),
        label="Intensity below ecoregion standard",
        description=(
            "Texas Comptroller intensity-of-use guidelines vary by "
            "ecoregion. A parcel operating below the ecoregion-"
            "specific minimum (stocking rate, harvested acres, etc.) "
            "is at heightened risk of CAD challenge."
        ),
    ),
)


def _validate_rubric_weights() -> None:
    total = sum((f.weight for f in FACTORS), Decimal("0"))
    if total != Decimal("1.000"):
        raise AssertionError(
            f"FACTORS weights must sum to 1.000 (got {total}). "
            f"Adjust valuation/scoring.py before shipping."
        )


_validate_rubric_weights()


# -- Scoring inputs / outputs ----------------------------------------------

@dataclass(frozen=True)
class ScoringInput:
    """Frozen input bundle passed to ``score()``.

    Frozen + dataclass so the caller can't mutate it between hash and
    score, and so two calls with structurally equal inputs are easy to
    confirm equal at the call site (helps the reproducibility audit).
    """
    cad: CADRecord
    ecoregion: str
    parcel_acreage: float | None
    today: date
    # External signals not on the CAD record. Optional so a parcel that
    # hasn't been scored against drought / intensity datasets yet still
    # gets a defensible (pessimistic-on-evidence) score.
    drought_level: str = "neutral"     # neutral | mild | moderate | severe
    operating_intensity_below_standard: bool | None = None


@dataclass(frozen=True)
class DriverResult:
    key: str
    weight: Decimal
    triggered: bool
    evidence: str


@dataclass(frozen=True)
class RiskScore:
    value: float
    band: str
    drivers: tuple[DriverResult, ...]


# -- Factor evaluators -----------------------------------------------------
#
# Each returns (triggered: bool, evidence: str). Evidence is the human-
# readable string the report shows under the driver row. Texas-only
# language and "1-d-1(w)" / "1-d-1" are used verbatim, never the
# generic "wildlife valuation."

def _eval_ownership_change_recent(inp: ScoringInput) -> tuple[bool, str]:
    cad_date = inp.cad.ownership_change_date
    if not cad_date:
        return False, "No ownership change recorded in CAD snapshot."
    months = _months_between(cad_date, inp.today)
    if months <= 12:
        return True, (
            f"Deed transfer {cad_date.isoformat()} "
            f"({months} months before as-of {inp.today.isoformat()})."
        )
    return False, (
        f"Last transfer {cad_date.isoformat()} "
        f"({months} months ago) — outside the 12-month window."
    )


def _eval_classification_vulnerable(inp: ScoringInput) -> tuple[bool, str]:
    cls = inp.cad.classification
    if cls == "ag_open_space":
        return True, (
            "Currently 1-d-1 (open-space agricultural). Subject to "
            "annual reapplication and CAD intensity review."
        )
    if cls == "wildlife_open_space":
        return False, (
            "Currently 1-d-1(w). Qualifying activity is decoupled from "
            "market ag intensity, reducing exposure to drought- or "
            "stocking-rate driven challenges."
        )
    if cls in ("market", "timber", "unknown"):
        return False, (
            f"Current classification {cls!r}; ag-vulnerability factor "
            f"does not apply."
        )
    return False, f"Unrecognized classification {cls!r}."


def _eval_assessed_market_spread_extreme(
    inp: ScoringInput,
) -> tuple[bool, str]:
    a = inp.cad.assessed_value_per_acre
    m = inp.cad.market_value_per_acre
    if not a or not m:
        return False, "CAD snapshot lacks assessed and/or market value."
    if a <= 0:
        return False, "Assessed value not positive; spread undefined."
    ratio = m / a
    if ratio > 100:
        return True, (
            f"Market ${m:,.0f}/ac is {ratio:.0f}× assessed ${a:,.2f}/ac. "
            f"Loss of 1-d-1 would reset assessed sharply upward."
        )
    return False, (
        f"Market ${m:,.0f}/ac is {ratio:.0f}× assessed ${a:,.2f}/ac — "
        f"below the 100× threshold."
    )


def _eval_drought_pdsi_24mo(inp: ScoringInput) -> tuple[bool, str]:
    level = (inp.drought_level or "neutral").lower()
    if level in ("severe", "moderate"):
        return True, (
            f"Drought level {level!r} over rolling 24-month window."
        )
    if level in ("neutral", "mild"):
        return False, (
            f"Drought level {level!r} — does not meet the moderate-or-"
            f"severe threshold."
        )
    return False, f"Unrecognized drought level {level!r}."


def _eval_intensity_below_ecoregion_standard(
    inp: ScoringInput,
) -> tuple[bool, str]:
    flag = inp.operating_intensity_below_standard
    if flag is None:
        return False, (
            "Intensity-of-use evaluation not run on this parcel "
            "(input not provided)."
        )
    if flag:
        eco = ECOREGION_INTENSITY.get(inp.ecoregion, {})
        eco_name = eco.get("name", inp.ecoregion)
        return True, (
            f"Operating intensity below the {eco_name} ecoregion "
            f"standard published in the Comptroller manual."
        )
    return False, (
        "Operating intensity meets or exceeds the ecoregion standard."
    )


_EVALUATORS = {
    "ownership_change_recent": _eval_ownership_change_recent,
    "classification_vulnerable": _eval_classification_vulnerable,
    "assessed_market_spread_extreme": _eval_assessed_market_spread_extreme,
    "drought_pdsi_24mo": _eval_drought_pdsi_24mo,
    "intensity_below_ecoregion_standard":
        _eval_intensity_below_ecoregion_standard,
}


# -- Band assignment -------------------------------------------------------
#
# Bands are presentation, not math. Boundaries chosen so:
#   * a parcel firing only the assessed-spread factor (0.15) reads "low"
#   * adding classification_vulnerable (+0.20) → "moderate"
#   * adding any third moderate-weight factor → "elevated"
#   * adding ownership_change_recent on top of the above → "high"

def _band_for(value: float) -> str:
    if value < 0.25:
        return "low"
    if value < 0.50:
        return "moderate"
    if value < 0.75:
        return "elevated"
    return "high"


# -- Public API ------------------------------------------------------------

def score(inp: ScoringInput) -> RiskScore:
    """Compute the risk score and named driver rows for one parcel.

    Pure function: same ``inp`` always yields the same RiskScore.
    """
    drivers: list[DriverResult] = []
    total = Decimal("0.000")
    for factor in FACTORS:
        evaluator = _EVALUATORS[factor.key]
        triggered, evidence = evaluator(inp)
        if triggered:
            total += factor.weight
        drivers.append(
            DriverResult(
                key=factor.key,
                weight=factor.weight,
                triggered=triggered,
                evidence=evidence,
            )
        )
    value = float(total)
    return RiskScore(
        value=value,
        band=_band_for(value),
        drivers=tuple(drivers),
    )


# -- Helpers ---------------------------------------------------------------

def _months_between(start: date, end: date) -> int:
    """Whole months from ``start`` to ``end``. Negative if start > end."""
    return (end.year - start.year) * 12 + (end.month - start.month) - (
        1 if end.day < start.day else 0
    )


def factor_keys() -> Iterable[str]:
    """Stable iteration of the rubric's factor keys, in declared order."""
    return tuple(f.key for f in FACTORS)
