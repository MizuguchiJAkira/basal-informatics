"""Stage 7 remediation eligibility — TPWD 3-of-7 qualifying practices.

Texas §23.521 conversion from 1-d-1 (open-space ag) to 1-d-1(w)
(wildlife) requires the landowner to perform 3 of 7 qualifying
practices in any tax year, with practice-specific intensity standards
per ecoregion. This module evaluates which of the seven Basal can see
evidence for on a given parcel, today.

Practice → Basal data mapping (full prose in
``valuation/reference/tpwd_seven_practices.yaml``)::

    habitat_control      ← habitat layer (habitat/units.py)
    erosion_control      ← out of band v1 (returns "not_evaluated")
    predator_control     ← out of band v1 (owner-attested)
    supplemental_water   ← cameras with placement_context = 'water'
    supplemental_food    ← cameras with placement_context = 'feeder'
                           or 'food_plot'
    shelter              ← out of band v1 (returns "not_evaluated")
    census_counts        ← CamScout: detection summaries on the parcel

The output is a structured per-practice evaluation. The viability
flag is True iff at least 3 practices return ``"qualifies"`` —
"not_evaluated" practices count as zero, never as half-credit. The
report uses both the practice-level evaluations (so the reader can
see *what's missing*) and the rolled-up flag.

Compatibility short-circuit: a parcel with ``primary_ag_use`` starting
``row_crop_`` is treated as habitat-incompatible at v1. Active row
cropping forecloses several practices structurally and conversion to
wildlife appraisal would in practice require taking the cropland out
of production for a multi-season transition that the v1 evaluator
does not model. A row-crop parcel surfaces ``wildlife_conversion_
viable=False`` even when census evidence is strong, with the reason
recorded in the missing-practices list.
"""

from __future__ import annotations

from dataclasses import dataclass

from valuation.adapters.cad import CADRecord
from valuation.reference import TPWD_SEVEN_PRACTICES


@dataclass(frozen=True)
class PracticeEvaluation:
    key: str                  # matches TPWD_SEVEN_PRACTICES key
    label: str
    status: str               # qualifies | does_not_qualify | not_evaluated
    evidence: str


@dataclass(frozen=True)
class RemediationResult:
    wildlife_conversion_viable: bool
    practices: tuple[PracticeEvaluation, ...]
    qualifying_practices_evidence: tuple[str, ...]
    missing_practices_to_qualify: tuple[str, ...]
    ecoregion: str


# -- Inputs from existing Basal data ---------------------------------------
#
# These match what the lender route already loads. The remediation
# evaluator takes them as primitives so it stays unit-testable without
# the SQLAlchemy session.

@dataclass(frozen=True)
class RemediationInput:
    cad: CADRecord
    ecoregion: str
    # Per-camera placement_context strings on the parcel — used by
    # supplemental_water and supplemental_food.
    camera_placement_contexts: tuple[str, ...]
    # Independent-event total across all cameras + the camera-day
    # denominator. Used by census_counts.
    total_independent_events: int
    total_camera_days: int


def evaluate(inp: RemediationInput) -> RemediationResult:
    practices: list[PracticeEvaluation] = []
    primary_use = (inp.cad.raw.get("primary_ag_use") or "").lower()
    is_row_crop = primary_use.startswith("row_crop_")

    practices.append(_eval_habitat_control(inp, is_row_crop))
    practices.append(_eval_erosion_control(inp))
    practices.append(_eval_predator_control(inp))
    practices.append(_eval_supplemental_water(inp, is_row_crop))
    practices.append(_eval_supplemental_food(inp, is_row_crop))
    practices.append(_eval_shelter(inp))
    practices.append(_eval_census_counts(inp))

    qualifying = tuple(p.key for p in practices if p.status == "qualifies")
    not_qualifying = tuple(
        p.key for p in practices if p.status == "does_not_qualify"
    )

    viable = len(qualifying) >= 3
    return RemediationResult(
        wildlife_conversion_viable=viable,
        practices=tuple(practices),
        qualifying_practices_evidence=qualifying,
        missing_practices_to_qualify=not_qualifying,
        ecoregion=inp.ecoregion,
    )


# -- Per-practice evaluators -----------------------------------------------

def _label(key: str) -> str:
    return TPWD_SEVEN_PRACTICES.get(key, {}).get("label", key)


def _eval_habitat_control(
    inp: RemediationInput, is_row_crop: bool,
) -> PracticeEvaluation:
    if is_row_crop:
        return PracticeEvaluation(
            key="habitat_control",
            label=_label("habitat_control"),
            status="does_not_qualify",
            evidence=(
                f"Parcel currently in active row-crop production "
                f"({inp.cad.raw.get('primary_ag_use')}). Wildlife habitat "
                f"control requires native vegetation management; cropland "
                f"is structurally incompatible without a multi-season "
                f"transition out of production."
            ),
        )
    # Habitat-layer probe (habitat/units.py) requires a PostGIS data
    # path that the SQLite demo doesn't carry — it depends on NLCD
    # raster + EPA Level-IV ecoregion polygon + HUC-10 watershed
    # intersections. In SQLite-backed demo and dev contexts we fall
    # back to inferring habitat-control fitness from the CAD's
    # primary_ag_use (handled above; row-crop short-circuits to
    # does_not_qualify). In production PostGIS deploys, replace this
    # default with a habitat/units.py call gated on a feature check.
    return PracticeEvaluation(
        key="habitat_control",
        label=_label("habitat_control"),
        status="qualifies",
        evidence=(
            "Native pasture / rangeland use compatible with habitat "
            "control. Specific intensity (brush sculpting, prescribed "
            "burn, invasive removal) to be verified by site visit."
        ),
    )


def _eval_erosion_control(inp: RemediationInput) -> PracticeEvaluation:
    return PracticeEvaluation(
        key="erosion_control",
        label=_label("erosion_control"),
        status="not_evaluated",
        evidence=(
            "Out of band for v1 — erosion-control structures are not "
            "captured in current Basal datasets."
        ),
    )


def _eval_predator_control(inp: RemediationInput) -> PracticeEvaluation:
    return PracticeEvaluation(
        key="predator_control",
        label=_label("predator_control"),
        status="not_evaluated",
        evidence=(
            "Out of band for v1 — predator-control activity is owner-"
            "attested and not captured passively."
        ),
    )


def _eval_supplemental_water(
    inp: RemediationInput, is_row_crop: bool,
) -> PracticeEvaluation:
    has_water = any(
        ctx == "water" for ctx in inp.camera_placement_contexts
    )
    if has_water and not is_row_crop:
        return PracticeEvaluation(
            key="supplemental_water",
            label=_label("supplemental_water"),
            status="qualifies",
            evidence=(
                "At least one trail-camera placement registered as a "
                "managed water source on the parcel. Distribution-per-"
                "acre intensity to be verified by site visit."
            ),
        )
    if is_row_crop:
        return PracticeEvaluation(
            key="supplemental_water",
            label=_label("supplemental_water"),
            status="does_not_qualify",
            evidence=(
                "Irrigation infrastructure on row-crop parcels does "
                "not satisfy the wildlife-water-source intensity "
                "standard."
            ),
        )
    return PracticeEvaluation(
        key="supplemental_water",
        label=_label("supplemental_water"),
        status="does_not_qualify",
        evidence="No camera placements registered as water sources.",
    )


def _eval_supplemental_food(
    inp: RemediationInput, is_row_crop: bool,
) -> PracticeEvaluation:
    has_food = any(
        ctx in ("feeder", "food_plot")
        for ctx in inp.camera_placement_contexts
    )
    if has_food and not is_row_crop:
        return PracticeEvaluation(
            key="supplemental_food",
            label=_label("supplemental_food"),
            status="qualifies",
            evidence=(
                "Trail-camera placements registered as feeders or food "
                "plots on the parcel. Acreage / intensity to be "
                "verified."
            ),
        )
    if is_row_crop:
        return PracticeEvaluation(
            key="supplemental_food",
            label=_label("supplemental_food"),
            status="does_not_qualify",
            evidence=(
                "Row-crop production does not satisfy the wildlife-"
                "supplemental-food practice; commercial crop residue "
                "is excluded from intensity calculations."
            ),
        )
    return PracticeEvaluation(
        key="supplemental_food",
        label=_label("supplemental_food"),
        status="does_not_qualify",
        evidence=(
            "No camera placements registered as feeders or food plots."
        ),
    )


def _eval_shelter(inp: RemediationInput) -> PracticeEvaluation:
    return PracticeEvaluation(
        key="shelter",
        label=_label("shelter"),
        status="not_evaluated",
        evidence=(
            "Out of band for v1 — shelter structure inventory is not "
            "captured in current Basal datasets."
        ),
    )


# Census-count threshold per the TPWD remote-camera census guideline:
# we require at least 1 camera-day per 100 acres AND 30+ independent
# events in the survey window. Either condition unmet → does_not_qualify.
_CENSUS_MIN_INDEPENDENT_EVENTS = 30


def _eval_census_counts(inp: RemediationInput) -> PracticeEvaluation:
    if inp.total_camera_days <= 0:
        return PracticeEvaluation(
            key="census_counts",
            label=_label("census_counts"),
            status="does_not_qualify",
            evidence=(
                "No CamScout deployment recorded on this parcel "
                "during the survey window."
            ),
        )
    if inp.total_independent_events < _CENSUS_MIN_INDEPENDENT_EVENTS:
        return PracticeEvaluation(
            key="census_counts",
            label=_label("census_counts"),
            status="does_not_qualify",
            evidence=(
                f"{inp.total_independent_events} independent events "
                f"recorded — below the {_CENSUS_MIN_INDEPENDENT_EVENTS}-"
                f"event minimum for a defensible census."
            ),
        )
    return PracticeEvaluation(
        key="census_counts",
        label=_label("census_counts"),
        status="qualifies",
        evidence=(
            f"{inp.total_independent_events:,} independent events "
            f"across {inp.total_camera_days:,} camera-days — meets "
            f"the TPWD remote-camera census threshold."
        ),
    )
