"""Pure-function tests for valuation/remediation.py.

The 3-of-7 TPWD logic decides which parcels qualify for 1-d-1(w)
conversion. A regression here would either tell a row-crop parcel it
qualifies (false positive in the report) or tell a viable wildlife
parcel it does not (false negative). Both are bad. Pin the per-
practice evaluations and the roll-up.
"""

from __future__ import annotations

from datetime import date

import pytest

from valuation.adapters.cad.base import CADRecord
from valuation.remediation import (
    RemediationInput,
    evaluate,
)


def _cad(*, primary_use: str = "grazing_native_pasture") -> CADRecord:
    return CADRecord(
        parcel_id="TEST-00001",
        county_slug="kimble_tx",
        classification="ag_open_space",
        assessed_value_per_acre=12.40,
        market_value_per_acre=4_800.00,
        ownership_change_date=date(2024, 6, 15),
        as_of_date=date(2025, 10, 1),
        raw={"primary_ag_use": primary_use},
    )


def _input(**kw) -> RemediationInput:
    base = dict(
        cad=_cad(),
        ecoregion="edwards_plateau",
        camera_placement_contexts=("feeder", "trail", "water"),
        total_independent_events=1500,
        total_camera_days=900,
    )
    base.update(kw)
    return RemediationInput(**base)


# ---------------------------------------------------------------------------
# Roll-up: viability requires 3+ "qualifies"
# ---------------------------------------------------------------------------

def test_viable_when_three_practices_qualify():
    """Edwards Plateau Ranch demo profile: habitat_control (default),
    supplemental_water (water cam), supplemental_food (feeder cam),
    census_counts (Strecker) — 4 qualifying → viable."""
    result = evaluate(_input())
    assert result.wildlife_conversion_viable is True
    assert len(result.qualifying_practices_evidence) >= 3


def test_not_viable_when_fewer_than_three_qualify():
    """Strip everything that fires: no cameras at all + zero events."""
    result = evaluate(_input(
        camera_placement_contexts=(),
        total_independent_events=0,
        total_camera_days=0,
    ))
    assert result.wildlife_conversion_viable is False
    # habitat_control still defaults to qualifies for non-row-crop, so
    # the qualifying count is 1, not 0. Documented behavior.
    assert len(result.qualifying_practices_evidence) == 1


def test_not_viable_for_row_crop_parcel():
    """Riverbend Farm demo profile: row-crop short-circuits habitat /
    water / food to does_not_qualify. Only census can qualify."""
    result = evaluate(_input(
        cad=_cad(primary_use="row_crop_corn"),
        camera_placement_contexts=("trail", "feeder", "water"),
        total_independent_events=4721,
        total_camera_days=1500,
    ))
    assert result.wildlife_conversion_viable is False
    assert "census_counts" in result.qualifying_practices_evidence
    assert "habitat_control" not in result.qualifying_practices_evidence
    # Row-crop reasoning in the evidence string — needed for the report.
    habitat = next(
        p for p in result.practices if p.key == "habitat_control"
    )
    assert "row-crop" in habitat.evidence.lower()


# ---------------------------------------------------------------------------
# Per-practice evaluators
# ---------------------------------------------------------------------------

def test_census_qualifies_above_threshold():
    """30+ events AND camera_days > 0 → qualifies."""
    result = evaluate(_input(
        total_independent_events=31, total_camera_days=10,
    ))
    census = next(p for p in result.practices if p.key == "census_counts")
    assert census.status == "qualifies"


def test_census_does_not_qualify_below_event_threshold():
    result = evaluate(_input(
        total_independent_events=29, total_camera_days=10,
    ))
    census = next(p for p in result.practices if p.key == "census_counts")
    assert census.status == "does_not_qualify"
    assert "29 independent events" in census.evidence


def test_census_does_not_qualify_when_no_deployment():
    result = evaluate(_input(
        total_independent_events=100, total_camera_days=0,
    ))
    census = next(p for p in result.practices if p.key == "census_counts")
    assert census.status == "does_not_qualify"


def test_water_qualifies_with_water_camera():
    result = evaluate(_input(camera_placement_contexts=("water",)))
    water = next(p for p in result.practices
                 if p.key == "supplemental_water")
    assert water.status == "qualifies"


def test_water_does_not_qualify_without_water_camera():
    result = evaluate(_input(camera_placement_contexts=("trail", "feeder")))
    water = next(p for p in result.practices
                 if p.key == "supplemental_water")
    assert water.status == "does_not_qualify"


def test_food_qualifies_with_feeder():
    result = evaluate(_input(camera_placement_contexts=("feeder",)))
    food = next(p for p in result.practices
                if p.key == "supplemental_food")
    assert food.status == "qualifies"


def test_food_qualifies_with_food_plot():
    result = evaluate(_input(camera_placement_contexts=("food_plot",)))
    food = next(p for p in result.practices
                if p.key == "supplemental_food")
    assert food.status == "qualifies"


def test_food_does_not_qualify_for_row_crop_parcel():
    """Even with feeders on a row-crop parcel, food doesn't qualify —
    crop residue is excluded under the wildlife intensity rules."""
    result = evaluate(_input(
        cad=_cad(primary_use="row_crop_corn"),
        camera_placement_contexts=("feeder", "food_plot"),
    ))
    food = next(p for p in result.practices
                if p.key == "supplemental_food")
    assert food.status == "does_not_qualify"


# ---------------------------------------------------------------------------
# Out-of-band practices
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "erosion_control",
    "predator_control",
    "shelter",
])
def test_oob_practices_return_not_evaluated(key):
    """v1 deliberately doesn't evaluate three of the seven; they must
    surface as 'not_evaluated' (zero credit toward the 3-of-7 count),
    not 'qualifies' or 'does_not_qualify'."""
    result = evaluate(_input())
    practice = next(p for p in result.practices if p.key == key)
    assert practice.status == "not_evaluated"


def test_not_evaluated_does_not_count_toward_viability():
    """Even if all four 'real' evaluators short-circuit to fail, a
    parcel can't reach viability via the three out-of-band practices.
    Belt-and-suspenders: assert this directly."""
    result = evaluate(_input(
        cad=_cad(primary_use="row_crop_corn"),  # kills habitat/water/food
        camera_placement_contexts=("trail",),    # trail is neither water nor food
        total_independent_events=0,              # kills census
    ))
    qualifying = result.qualifying_practices_evidence
    assert len(qualifying) == 0
    assert result.wildlife_conversion_viable is False


# ---------------------------------------------------------------------------
# Output shape stability
# ---------------------------------------------------------------------------

def test_all_seven_practices_in_output_in_declared_order():
    """The report iterates result.practices in order. Reordering would
    silently shuffle the report; the YAML order is the contract."""
    result = evaluate(_input())
    expected = (
        "habitat_control",
        "erosion_control",
        "predator_control",
        "supplemental_water",
        "supplemental_food",
        "shelter",
        "census_counts",
    )
    assert tuple(p.key for p in result.practices) == expected
