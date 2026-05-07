"""Pure-function tests for valuation/exposure.py.

Both the assessed-to-market reset and the §23.55 rollback estimate
land in the report verbatim. These tests pin the math so a numeric
regression is caught at CI rather than by a loan officer.
"""

from __future__ import annotations

from datetime import date

import pytest

from valuation.adapters.cad.base import CADRecord
from valuation.exposure import (
    DEFAULT_EFFECTIVE_TAX_RATE,
    ROLLBACK_INTEREST_RATE,
    ROLLBACK_TAX_YEARS,
    assessed_to_market_reset,
    estimate_rollback_tax,
)


def _cad(**kw) -> CADRecord:
    base = dict(
        parcel_id="TEST-00001",
        county_slug="kimble_tx",
        classification="ag_open_space",
        assessed_value_per_acre=12.40,
        market_value_per_acre=4_800.00,
        ownership_change_date=date(2024, 6, 15),
        as_of_date=date(2025, 10, 1),
    )
    base.update(kw)
    return CADRecord(**base)


# ---------------------------------------------------------------------------
# Assessed-to-market reset
# ---------------------------------------------------------------------------

def test_collateral_delta_is_negative():
    """The reset moves assessed UP toward market, so the *change in
    assessed* is positive but the *change in collateral value* is
    negative (assessed - market) * acres. Sign matters in the report."""
    out = assessed_to_market_reset(_cad(), parcel_acreage=2340)
    assert out.collateral_value_delta_dollars is not None
    assert out.collateral_value_delta_dollars < 0


def test_collateral_delta_known_value():
    """Pin the math for the Edwards Plateau demo parcel."""
    out = assessed_to_market_reset(_cad(), parcel_acreage=2340)
    # (12.40 - 4800.00) * 2340 = -11,202,984.0
    assert out.collateral_value_delta_dollars == pytest.approx(
        -11_202_984.0, abs=0.01,
    )


def test_collateral_delta_high_confidence_for_ag():
    out = assessed_to_market_reset(_cad(), parcel_acreage=2340)
    assert out.confidence == "high"
    assert out.method == "assessed_to_market_reset"


def test_collateral_delta_high_confidence_for_wildlife():
    out = assessed_to_market_reset(
        _cad(classification="wildlife_open_space"), parcel_acreage=2340,
    )
    assert out.confidence == "high"


def test_collateral_delta_medium_for_timber():
    out = assessed_to_market_reset(
        _cad(classification="timber"), parcel_acreage=2340,
    )
    assert out.confidence == "medium"


def test_collateral_delta_low_for_unknown():
    out = assessed_to_market_reset(
        _cad(classification="market"), parcel_acreage=2340,
    )
    assert out.confidence == "low"


def test_collateral_delta_none_when_acreage_missing():
    out = assessed_to_market_reset(_cad(), parcel_acreage=None)
    assert out.collateral_value_delta_dollars is None
    assert out.confidence == "low"


def test_collateral_delta_none_when_assessed_missing():
    out = assessed_to_market_reset(
        _cad(assessed_value_per_acre=None), parcel_acreage=2340,
    )
    assert out.collateral_value_delta_dollars is None


# ---------------------------------------------------------------------------
# §23.55 rollback estimate
# ---------------------------------------------------------------------------

def test_rollback_constants_match_2020_regime():
    """Pin the constants so a future edit can't quietly switch back to
    the pre-2020 5-year/7% regime without an explicit code review."""
    assert ROLLBACK_TAX_YEARS == 3
    assert ROLLBACK_INTEREST_RATE == 0.05
    assert DEFAULT_EFFECTIVE_TAX_RATE == 0.02


def test_rollback_known_value_kimble():
    """Pin the dollar number for the Edwards Plateau demo parcel."""
    rb, years, rate = estimate_rollback_tax(_cad(), parcel_acreage=2340)
    # per-year-tax-diff = (4800 - 12.40) * 2340 * 0.02 = 224,099.5
    # rollup: y1*(1+0.05*2) + y2*(1+0.05*1) + y3*(1+0)
    #       = 224099.52 * 1.10 + 224099.52 * 1.05 + 224099.52 * 1.00
    #       = 224099.52 * (1.10 + 1.05 + 1.00) = 224099.52 * 3.15
    expected = (4800.0 - 12.40) * 2340 * 0.02 * (1.10 + 1.05 + 1.00)
    assert rb == pytest.approx(expected, rel=1e-6)
    assert years == 3
    assert rate == 0.02


def test_rollback_zero_when_assessed_equals_market():
    """No rollback gap when productivity assessment matches market —
    can happen in CADs that haven't refreshed market values."""
    rb, _, _ = estimate_rollback_tax(
        _cad(assessed_value_per_acre=100.0, market_value_per_acre=100.0),
        parcel_acreage=2340,
    )
    assert rb == 0.0


def test_rollback_zero_when_market_below_assessed():
    """Pathological: if assessed > market (very rare; misvalued CAD),
    the formula would yield negative. Clamp to zero — the rollback tax
    is recapture, not a refund."""
    rb, _, _ = estimate_rollback_tax(
        _cad(assessed_value_per_acre=200.0, market_value_per_acre=100.0),
        parcel_acreage=2340,
    )
    assert rb == 0.0


def test_rollback_none_when_acreage_missing():
    rb, _, _ = estimate_rollback_tax(_cad(), parcel_acreage=None)
    assert rb is None


def test_rollback_custom_rate_passes_through():
    """Adapter for a high-rate county should be able to override the
    Texas-average default without re-implementing the rollup."""
    cad = _cad()
    custom_rate = 0.025
    rb, _, rate = estimate_rollback_tax(
        cad, parcel_acreage=2340, effective_tax_rate=custom_rate,
    )
    assert rate == custom_rate
    # Math should scale linearly with rate.
    rb_default, _, _ = estimate_rollback_tax(cad, parcel_acreage=2340)
    assert rb == pytest.approx(
        rb_default * (custom_rate / DEFAULT_EFFECTIVE_TAX_RATE), rel=1e-6,
    )


def test_combined_exposure_includes_rollback():
    """assessed_to_market_reset() composes the rollback into the result."""
    out = assessed_to_market_reset(_cad(), parcel_acreage=2340)
    assert out.rollback_tax_estimated_dollars is not None
    assert out.rollback_tax_estimated_dollars > 0
    assert out.rollback_tax_years == ROLLBACK_TAX_YEARS
    assert out.rollback_tax_assumed_rate == DEFAULT_EFFECTIVE_TAX_RATE
