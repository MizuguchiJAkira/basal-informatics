"""Stage 7 dollar exposure — what the lender stands to lose if 1-d-1
or 1-d-1(w) appraisal is removed.

Method: assessed-to-market reset. The collateral value delta equals
``(assessed - market) * acreage`` — a negative number, since assessed
under productivity is the lower of the two and reverting to market
moves it up. We surface the absolute magnitude in the report; the sign
is preserved in the schema for consistency with credit-memo
conventions ("change in collateral value").

Confidence band:
  high     — both assessed and market values present, acreage > 0,
             classification is one of the productivity-appraisal codes
             that actually faces the reset risk.
  medium   — values present but classification is unclear or acreage
             estimate inflated.
  low      — values missing, or computation falls back to a generic
             per-acre delta from regional comparables (not implemented
             in v1; documented for the v1.1 fallback path).

This is collateral exposure, not tax liability or remediation cost. It
also is not the back-tax rollback that some §23.55 conversion-from-ag
events trigger; the rollback computation lives in v1.1 alongside
real CAD ownership-history pulls.
"""

from __future__ import annotations

from dataclasses import dataclass

from valuation.adapters.cad import CADRecord


@dataclass(frozen=True)
class ExposureResult:
    # Negative number: collateral value drops when special-use
    # appraisal is lost and assessed value resets toward market.
    collateral_value_delta_dollars: float | None
    method: str
    confidence: str   # low | medium | high
    # Texas Tax Code §23.55 rollback tax estimate. Triggered when a
    # parcel loses its open-space ag (or wildlife) valuation through
    # a change in use. Estimated separately from the collateral delta:
    # the delta is the *asset* impact, this is the *cash* impact at
    # the moment of conversion.
    rollback_tax_estimated_dollars: float | None = None
    rollback_tax_years: int | None = None
    rollback_tax_assumed_rate: float | None = None


# Texas §23.55 rollback parameters (2020+ regime).
#
#   Recapture window: 3 prior tax years (was 5 before HB 1743/2019).
#   Interest:         5% simple annual (was 7%).
#   Effective rate:   combined school+county+city. Texas 2024-25
#                     average ≈ 2.0%; use as a default that's
#                     conservatively transparent rather than parcel-
#                     specific (which would require live tax-rate
#                     pulls per CAD).
#
# These constants are deliberately exposed at module scope so an
# auditor can confirm what rate set was in effect when a particular
# rollback estimate was computed.

ROLLBACK_TAX_YEARS = 3
ROLLBACK_INTEREST_RATE = 0.05
DEFAULT_EFFECTIVE_TAX_RATE = 0.02


def estimate_rollback_tax(
    cad: CADRecord,
    parcel_acreage: float | None,
    *,
    effective_tax_rate: float = DEFAULT_EFFECTIVE_TAX_RATE,
) -> tuple[float | None, int, float]:
    """Estimate Texas Tax Code §23.55 rollback tax liability.

    The rollback tax is levied when an open-space ag (or wildlife)
    parcel converts to a non-qualifying use. It equals the difference
    between productivity-based and market-based property tax assessed
    over the past three tax years, plus 5% simple annual interest.

    Returns ``(estimate, years, rate)``. The first component is the
    dollar liability or None when inputs are insufficient; ``years``
    and ``rate`` echo the assumptions back so the report can show
    "3 years at 5% interest, 2.0% effective rate" alongside the
    number.

    Caveats this v1 estimate does NOT capture:
      * Per-CAD effective rate variance — uses Texas average.
      * §23.55(g) farm-loss exemption windows.
      * Wildlife-specific §23.522 sub-conditions.
      * The "change in use" event determining the rollback start
        year, which a real CAD calculation reads from deed records.
    """
    a = cad.assessed_value_per_acre
    m = cad.market_value_per_acre
    if a is None or m is None or not parcel_acreage:
        return None, ROLLBACK_TAX_YEARS, effective_tax_rate
    per_year_tax_difference = (
        (float(m) - float(a)) * float(parcel_acreage) * effective_tax_rate
    )
    if per_year_tax_difference <= 0:
        return 0.0, ROLLBACK_TAX_YEARS, effective_tax_rate

    # Simple-interest rollup over the recapture window:
    # year 1 has accumulated 2y of interest, year 2 has 1y, year 3 has 0y.
    total = 0.0
    for years_held in range(ROLLBACK_TAX_YEARS):
        total += per_year_tax_difference * (
            1 + ROLLBACK_INTEREST_RATE * (ROLLBACK_TAX_YEARS - 1 - years_held)
        )
    return total, ROLLBACK_TAX_YEARS, effective_tax_rate


def assessed_to_market_reset(
    cad: CADRecord, parcel_acreage: float | None,
    *,
    effective_tax_rate: float = DEFAULT_EFFECTIVE_TAX_RATE,
) -> ExposureResult:
    """Compute the collateral exposure if 1-d-1 status is lost.

    Collateral delta = (assessed_per_ac - market_per_ac) * acres.

    Returns a low-confidence None-valued result when any input is
    missing rather than guessing — the report will say "not estimable
    from available CAD record" rather than show a fabricated number.
    """
    a = cad.assessed_value_per_acre
    m = cad.market_value_per_acre
    if a is None or m is None or not parcel_acreage:
        return ExposureResult(
            collateral_value_delta_dollars=None,
            method="assessed_to_market_reset",
            confidence="low",
        )

    delta = (float(a) - float(m)) * float(parcel_acreage)

    # Confidence — high when classification is in the set of
    # productivity-appraisal codes that this method directly speaks
    # to (ag and wildlife open-space). Other classifications take a
    # confidence step down because the reset mechanic differs.
    if cad.classification in ("ag_open_space", "wildlife_open_space"):
        confidence = "high"
    elif cad.classification == "timber":
        confidence = "medium"
    else:
        confidence = "low"

    rollback_tax, rb_years, rb_rate = estimate_rollback_tax(
        cad, parcel_acreage, effective_tax_rate=effective_tax_rate,
    )

    return ExposureResult(
        collateral_value_delta_dollars=delta,
        method="assessed_to_market_reset",
        confidence=confidence,
        rollback_tax_estimated_dollars=rollback_tax,
        rollback_tax_years=rb_years,
        rollback_tax_assumed_rate=rb_rate,
    )
