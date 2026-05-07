"""Pure-function tests for valuation/scoring.py.

The scoring path is the most-audit-sensitive part of Stage 7: every
factor's weight, fire condition, and evidence string is on the report
verbatim. These tests pin the rubric.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from valuation.adapters.cad.base import CADRecord
from valuation.scoring import (
    FACTORS,
    RiskScore,
    ScoringInput,
    factor_keys,
    score,
)


# ---------------------------------------------------------------------------
# Rubric invariants
# ---------------------------------------------------------------------------

def test_rubric_weights_sum_to_one():
    """Documented invariant: every weight slot adds up to exactly 1.000.

    Asserted at import time; this test guards against a regression that
    silently violates the invariant by, say, adding a factor without
    rebalancing the existing ones.
    """
    total = sum((f.weight for f in FACTORS), Decimal("0"))
    assert total == Decimal("1.000"), (
        f"FACTORS weights sum to {total}, expected 1.000"
    )


def test_factor_keys_stable():
    """Factor keys are part of the JSON contract; renaming one would
    break the report layer + any downstream consumer. Pin the list."""
    assert factor_keys() == (
        "ownership_change_recent",
        "classification_vulnerable",
        "assessed_market_spread_extreme",
        "drought_pdsi_24mo",
        "intensity_below_ecoregion_standard",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cad(
    *,
    classification: str = "ag_open_space",
    assessed: float = 12.40,
    market: float = 4_800.00,
    transfer_date: date | None = date(2024, 6, 15),
) -> CADRecord:
    return CADRecord(
        parcel_id="TEST-00001",
        county_slug="kimble_tx",
        classification=classification,
        assessed_value_per_acre=assessed,
        market_value_per_acre=market,
        ownership_change_date=transfer_date,
        as_of_date=date(2025, 10, 1),
    )


def _scoring(cad: CADRecord, **kw) -> ScoringInput:
    base = dict(
        cad=cad,
        ecoregion="edwards_plateau",
        parcel_acreage=2340,
        today=date(2026, 5, 5),
    )
    base.update(kw)
    return ScoringInput(**base)


# ---------------------------------------------------------------------------
# Reproducibility (the explicit constraint from the spec)
# ---------------------------------------------------------------------------

def test_score_is_deterministic_for_identical_inputs():
    inp = _scoring(_cad())
    assert score(inp) == score(inp), (
        "Scoring is not deterministic — same input yielded different output."
    )


def test_score_uses_input_today_not_wall_clock():
    """Spec: no wall-clock reads in scoring. ``today`` comes from
    ScoringInput. Behavioral check — same CAD, different ``today`` →
    different age-since-transfer evidence."""
    cad = _cad(transfer_date=date(2025, 11, 22))
    r_close = score(_scoring(cad, today=date(2026, 1, 22)))   # 2 mo
    r_far = score(_scoring(cad, today=date(2027, 11, 22)))    # 24 mo
    e_close = next(
        d.evidence for d in r_close.drivers
        if d.key == "ownership_change_recent"
    )
    e_far = next(
        d.evidence for d in r_far.drivers
        if d.key == "ownership_change_recent"
    )
    assert "2 months" in e_close
    assert "24 months" in e_far


# ---------------------------------------------------------------------------
# Driver: ownership_change_recent
# ---------------------------------------------------------------------------

def test_ownership_change_within_12mo_fires():
    cad = _cad(transfer_date=date(2025, 11, 22))   # 5.5 mo before today
    result = score(_scoring(cad))
    fired = next(d for d in result.drivers if d.key == "ownership_change_recent")
    assert fired.triggered is True
    assert "5 months" in fired.evidence


def test_ownership_change_outside_12mo_does_not_fire():
    cad = _cad(transfer_date=date(2024, 6, 15))    # 22 mo before today
    result = score(_scoring(cad))
    fired = next(d for d in result.drivers if d.key == "ownership_change_recent")
    assert fired.triggered is False
    assert "22 months" in fired.evidence


def test_ownership_change_missing_date_does_not_fire():
    cad = _cad(transfer_date=None)
    result = score(_scoring(cad))
    fired = next(d for d in result.drivers if d.key == "ownership_change_recent")
    assert fired.triggered is False
    assert "no ownership change" in fired.evidence.lower()


# ---------------------------------------------------------------------------
# Driver: classification_vulnerable
# ---------------------------------------------------------------------------

def test_classification_vulnerable_fires_for_ag_open_space():
    result = score(_scoring(_cad(classification="ag_open_space")))
    fired = next(d for d in result.drivers if d.key == "classification_vulnerable")
    assert fired.triggered is True
    # Texas-only language enforced — must mention 1-d-1, not "ag" generally.
    assert "1-d-1" in fired.evidence


def test_classification_vulnerable_does_not_fire_for_wildlife():
    result = score(_scoring(_cad(classification="wildlife_open_space")))
    fired = next(d for d in result.drivers if d.key == "classification_vulnerable")
    assert fired.triggered is False
    assert "1-d-1(w)" in fired.evidence


def test_classification_vulnerable_does_not_fire_for_market():
    result = score(_scoring(_cad(classification="market")))
    fired = next(d for d in result.drivers if d.key == "classification_vulnerable")
    assert fired.triggered is False


# ---------------------------------------------------------------------------
# Driver: assessed_market_spread_extreme
# ---------------------------------------------------------------------------

def test_spread_above_100x_fires():
    result = score(_scoring(_cad(assessed=10.0, market=2000.0)))   # 200×
    fired = next(d for d in result.drivers
                 if d.key == "assessed_market_spread_extreme")
    assert fired.triggered is True


def test_spread_at_100x_does_not_fire():
    """The threshold is strict greater-than, not greater-or-equal."""
    result = score(_scoring(_cad(assessed=10.0, market=1000.0)))   # exactly 100×
    fired = next(d for d in result.drivers
                 if d.key == "assessed_market_spread_extreme")
    assert fired.triggered is False


def test_spread_missing_values_does_not_fire():
    cad = _cad()
    cad = CADRecord(
        parcel_id=cad.parcel_id, county_slug=cad.county_slug,
        classification=cad.classification,
        assessed_value_per_acre=None, market_value_per_acre=None,
        ownership_change_date=cad.ownership_change_date,
        as_of_date=cad.as_of_date,
    )
    result = score(_scoring(cad))
    fired = next(d for d in result.drivers
                 if d.key == "assessed_market_spread_extreme")
    assert fired.triggered is False


# ---------------------------------------------------------------------------
# Driver: drought_pdsi_24mo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,fires", [
    ("severe", True),
    ("moderate", True),
    ("mild", False),
    ("neutral", False),
    ("garbage", False),
])
def test_drought_levels(level, fires):
    result = score(_scoring(_cad(), drought_level=level))
    fired = next(d for d in result.drivers if d.key == "drought_pdsi_24mo")
    assert fired.triggered is fires, (
        f"drought={level!r} should fire={fires}, got {fired.triggered}"
    )


# ---------------------------------------------------------------------------
# Driver: intensity_below_ecoregion_standard
# ---------------------------------------------------------------------------

def test_intensity_factor_skipped_when_input_missing():
    result = score(_scoring(_cad(), operating_intensity_below_standard=None))
    fired = next(d for d in result.drivers
                 if d.key == "intensity_below_ecoregion_standard")
    assert fired.triggered is False
    assert "not run" in fired.evidence.lower()


def test_intensity_factor_fires_when_below_standard():
    result = score(_scoring(_cad(), operating_intensity_below_standard=True))
    fired = next(d for d in result.drivers
                 if d.key == "intensity_below_ecoregion_standard")
    assert fired.triggered is True


# ---------------------------------------------------------------------------
# Band assignment + roll-up
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected_band", [
    (0.00, "low"),
    (0.24, "low"),
    (0.25, "moderate"),
    (0.49, "moderate"),
    (0.50, "elevated"),
    (0.74, "elevated"),
    (0.75, "high"),
    (1.00, "high"),
])
def test_band_boundaries(value, expected_band):
    """Band cutpoints are part of the report — moving them silently
    would change a parcel's reported risk without changing its drivers.
    """
    from valuation.scoring import _band_for
    assert _band_for(value) == expected_band


def test_no_drivers_fired_yields_low():
    """A parcel with classification=wildlife, no recent change, neutral
    drought, intensity-not-evaluated, market=assessed → all factors off
    → score = 0.0 → low band."""
    cad = _cad(
        classification="wildlife_open_space",
        assessed=100.0, market=100.0,
        transfer_date=date(2010, 1, 1),
    )
    result = score(_scoring(cad, drought_level="neutral"))
    assert result.value == 0.0
    assert result.band == "low"
    # All factors recorded even when none fire.
    assert len(result.drivers) == len(FACTORS)
    assert all(d.triggered is False for d in result.drivers)


def test_all_drivers_fired_yields_high():
    cad = _cad(
        classification="ag_open_space",
        assessed=10.0, market=10_000.0,        # 1000× spread
        transfer_date=date(2026, 1, 1),         # ~4 months
    )
    result = score(_scoring(
        cad, drought_level="severe",
        operating_intensity_below_standard=True,
    ))
    assert result.value == 1.0
    assert result.band == "high"
    assert all(d.triggered for d in result.drivers)


def test_drivers_recorded_in_declared_order():
    """The report relies on a stable driver order so the table layout
    doesn't shuffle between renders."""
    result = score(_scoring(_cad()))
    assert tuple(d.key for d in result.drivers) == factor_keys()


def test_demo_parcels_yield_expected_bands():
    """Pin the demo parcels' bands so a rubric edit accidentally
    flipping any of them shows up in CI before it ships."""
    today = date(2026, 5, 5)

    # Edwards Plateau Ranch: ownership change 2024-06-15 (22 mo, no fire),
    # ag_open_space (fire), spread 387× (fire), drought moderate (fire),
    # intensity not evaluated (no fire) → 0.20 + 0.15 + 0.15 = 0.50 → elevated.
    ep = score(_scoring(
        _cad(transfer_date=date(2024, 6, 15)),
        today=today, drought_level="moderate",
    ))
    assert ep.band == "elevated"
    assert ep.value == 0.5

    # Riverbend Farm: ownership change 2025-11-22 (5 mo, fire), ag_open_space
    # (fire), spread 194× (fire), drought neutral (no fire), intensity
    # not evaluated (no fire) → 0.40 + 0.20 + 0.15 = 0.75 → high.
    rb = score(_scoring(
        _cad(
            assessed=38.20, market=7400.0,
            transfer_date=date(2025, 11, 22),
        ),
        today=today, drought_level="neutral",
    ))
    assert rb.band == "high"
    assert rb.value == 0.75

    # Llano Highlands: long-tenured (no fire), wildlife (no fire), spread
    # 378× (fire), drought moderate (fire), intensity not evaluated
    # (no fire) → 0.15 + 0.15 = 0.30 → moderate.
    lh = score(_scoring(
        _cad(
            classification="wildlife_open_space",
            assessed=14.80, market=5600.0,
            transfer_date=date(2015, 3, 9),
        ),
        today=today, drought_level="moderate",
    ))
    assert lh.band == "moderate"
    assert lh.value == 0.3
