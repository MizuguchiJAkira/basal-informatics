"""Stage 7 orchestrator — one entry point per parcel.

The lender route calls ``valuation.compute.for_parcel(parcel)`` once
per page render. This module:

  1. Resolves the CAD adapter for the parcel's county and pulls a
     snapshot. Persists it to ``cad_snapshot`` (idempotent on
     ``(parcel_id, as_of_date)``).
  2. Gathers ScoringInput / RemediationInput from existing Basal
     models (cameras, detection summaries, parcel acreage).
  3. Runs ``scoring.score``, ``exposure.assessed_to_market_reset``,
     and ``remediation.evaluate``.
  4. Upserts ``parcel_valuation_status`` + ``valuation_risk_factors``.
  5. Returns the JSON contract shape (a plain dict the report layers
     can consume without importing internals).

Returns ``None`` for parcels with no registered CAD adapter — the
report layers treat that as "section not applicable to this parcel"
and render the existing report unchanged.

Pure with respect to the input parcel: same parcel + same as_of_date
+ same upstream Basal data → same output dict. The only non-determ-
inistic piece is ``computed_at`` on the persisted row, which is
explicitly excluded from the returned JSON contract.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from db.models import (
    db,
    Camera,
    CADSnapshot,
    DetectionSummary,
    ParcelValuationStatus,
    Property,
    Season,
    ValuationRiskFactor,
)
from valuation.adapters.cad import get_adapter
from valuation.exposure import assessed_to_market_reset
from valuation.reference import (
    drought_level_for_county,
    ecoregion_for_county,
    effective_tax_rate_for_county,
)
from valuation.remediation import RemediationInput, evaluate as eval_remediation
from valuation.scoring import ScoringInput, score


# County → CAD-adapter slug. Property.county is "Kimble", "Brazos", …;
# adapter slugs are "kimble_tx", "brazos_tx". Two-step (county →
# ecoregion → ecoregion-specific behavior) is handled by the reference
# module; this mapping is just the adapter lookup.
def _county_to_adapter_slug(county: str | None) -> str | None:
    if not county:
        return None
    return county.strip().lower().replace(" ", "_") + "_tx"


def for_parcel(
    parcel: Property,
    *,
    as_of_date: date | None = None,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Run Stage 7 end-to-end for one parcel and persist the result.

    Returns the JSON contract dict, or ``None`` if no CAD adapter is
    registered for the parcel's county.
    """
    if today is None:
        today = date.today()
    if as_of_date is None:
        as_of_date = today

    slug = _county_to_adapter_slug(parcel.county)
    if not slug:
        return None
    adapter = get_adapter(slug)
    if not adapter:
        return None

    cad = adapter.fetch(parcel.parcel_id, as_of_date=as_of_date)
    if cad is None:
        return None

    ecoregion = ecoregion_for_county(parcel.county) or "unknown"

    cad_row = _upsert_cad_snapshot(parcel, cad)

    # Scoring inputs — drought + intensity probes are not yet wired to
    # external datasets in v1; they default to "neutral" / "not
    # provided" so the rubric records them as considered-but-not-fired
    # rather than skipped entirely.
    score_inp = ScoringInput(
        cad=cad,
        ecoregion=ecoregion,
        parcel_acreage=float(parcel.acreage) if parcel.acreage else None,
        today=today,
        drought_level=drought_level_for_county(parcel.county),
    )
    risk = score(score_inp)
    exposure = assessed_to_market_reset(
        cad, parcel_acreage=float(parcel.acreage) if parcel.acreage else None,
        effective_tax_rate=effective_tax_rate_for_county(parcel.county),
    )

    rem_inp = RemediationInput(
        cad=cad,
        ecoregion=ecoregion,
        camera_placement_contexts=tuple(
            (c.placement_context or "unknown")
            for c in parcel.cameras.all()
        ),
        total_independent_events=_total_events(parcel),
        total_camera_days=_total_camera_days(parcel),
    )
    rem = eval_remediation(rem_inp)

    status_row = _upsert_status_row(parcel, cad_row, risk, exposure, rem)

    return _to_json_contract(parcel, cad, risk, exposure, rem, status_row)


# -- Persistence helpers ---------------------------------------------------

def _upsert_cad_snapshot(parcel: Property, cad) -> CADSnapshot:
    row = (
        CADSnapshot.query
        .filter_by(parcel_id=parcel.id, as_of_date=cad.as_of_date)
        .first()
    )
    if row is None:
        row = CADSnapshot(
            parcel_id=parcel.id,
            county_slug=cad.county_slug,
            classification=cad.classification,
            assessed_value_per_acre=cad.assessed_value_per_acre,
            market_value_per_acre=cad.market_value_per_acre,
            ownership_change_date=cad.ownership_change_date,
            as_of_date=cad.as_of_date,
            raw_record_json=json.dumps(cad.raw, default=str),
        )
        db.session.add(row)
        db.session.flush()
    else:
        row.classification = cad.classification
        row.assessed_value_per_acre = cad.assessed_value_per_acre
        row.market_value_per_acre = cad.market_value_per_acre
        row.ownership_change_date = cad.ownership_change_date
        row.raw_record_json = json.dumps(cad.raw, default=str)
    return row


def _upsert_status_row(
    parcel: Property, cad_row: CADSnapshot, risk, exposure, rem,
) -> ParcelValuationStatus:
    row = (
        ParcelValuationStatus.query
        .filter_by(parcel_id=parcel.id)
        .first()
    )
    if row is None:
        row = ParcelValuationStatus(parcel_id=parcel.id)
        db.session.add(row)

    row.cad_snapshot_id = cad_row.id
    row.risk_band = risk.band
    row.risk_score_value = Decimal(str(round(risk.value, 3)))
    row.exposure_dollars = (
        Decimal(str(round(exposure.collateral_value_delta_dollars, 2)))
        if exposure.collateral_value_delta_dollars is not None
        else None
    )
    row.exposure_method = exposure.method
    row.exposure_confidence = exposure.confidence
    row.remediation_viable = rem.wildlife_conversion_viable
    row.ecoregion = rem.ecoregion
    row.computed_at = datetime.utcnow()
    db.session.flush()

    # Replace driver rows wholesale. Cleaner than diffing — the rubric
    # is small and updates are infrequent (once per page render).
    ValuationRiskFactor.query.filter_by(
        parcel_valuation_status_id=row.id,
    ).delete(synchronize_session=False)
    for i, d in enumerate(risk.drivers):
        db.session.add(
            ValuationRiskFactor(
                parcel_valuation_status_id=row.id,
                factor_key=d.key,
                weight=d.weight,
                triggered=d.triggered,
                evidence=d.evidence,
                display_order=i,
            )
        )
    db.session.commit()
    return row


# -- Existing-model adapters -----------------------------------------------

def _total_events(parcel: Property) -> int:
    """Sum of independent events across every camera + species on the
    parcel's seasons. Inputs the census_counts practice and the
    on-screen "events behind the score" line."""
    total = 0
    for s in Season.query.filter_by(property_id=parcel.id).all():
        total += sum(
            int(d.independent_events or 0)
            for d in DetectionSummary.query
            .filter_by(season_id=s.id).all()
        )
    return total


def _total_camera_days(parcel: Property) -> int:
    """Approximate camera-days = active cameras × season length.

    A real worker-side computation would track per-camera deployment
    intervals; v1 uses a coarse parcel-level approximation that's good
    enough for "did this parcel meet the census threshold?" decisions.
    """
    cams = parcel.cameras.filter_by(is_active=True).count()
    if cams == 0:
        return 0
    days = 0
    for s in Season.query.filter_by(property_id=parcel.id).all():
        if s.start_date and s.end_date:
            days += (s.end_date - s.start_date).days
    return cams * days


# -- Output shaping --------------------------------------------------------

def _to_json_contract(
    parcel: Property, cad, risk, exposure, rem, status_row,
) -> dict[str, Any]:
    """Map internal types to the JSON contract dict.

    The contract is documented in the spec and consumed by both report
    layers. Field names match the spec verbatim.
    """
    effective_band = (
        status_row.underwriter_override
        if status_row.underwriter_override
        else risk.band
    )
    return {
        "parcel_id": parcel.parcel_id,
        "current_valuation": {
            "classification": cad.classification,
            "assessed_value_per_acre": (
                float(cad.assessed_value_per_acre)
                if cad.assessed_value_per_acre is not None else None
            ),
            "market_value_per_acre": (
                float(cad.market_value_per_acre)
                if cad.market_value_per_acre is not None else None
            ),
            "data_source": (
                f"CAD_{cad.county_slug}_{cad.as_of_date.isoformat()}"
            ),
            "as_of_date": cad.as_of_date.isoformat(),
        },
        "risk_score": {
            "value": round(risk.value, 3),
            "band": risk.band,
            "effective_band": effective_band,
            "drivers": [
                {
                    "factor": d.key,
                    "weight": float(d.weight),
                    "triggered": d.triggered,
                    "evidence": d.evidence,
                }
                for d in risk.drivers
            ],
        },
        "exposure_if_lost": {
            "collateral_value_delta_dollars": (
                round(exposure.collateral_value_delta_dollars, 2)
                if exposure.collateral_value_delta_dollars is not None
                else None
            ),
            "method": exposure.method,
            "confidence": exposure.confidence,
            "rollback_tax_estimated_dollars": (
                round(exposure.rollback_tax_estimated_dollars, 2)
                if exposure.rollback_tax_estimated_dollars is not None
                else None
            ),
            "rollback_tax_years": exposure.rollback_tax_years,
            "rollback_tax_assumed_rate": exposure.rollback_tax_assumed_rate,
        },
        "remediation": {
            "wildlife_conversion_viable": rem.wildlife_conversion_viable,
            "qualifying_practices_evidence": list(
                rem.qualifying_practices_evidence
            ),
            "missing_practices_to_qualify": list(
                rem.missing_practices_to_qualify
            ),
            "ecoregion": rem.ecoregion,
            "practices": [
                {
                    "key": p.key,
                    "label": p.label,
                    "status": p.status,
                    "evidence": p.evidence,
                }
                for p in rem.practices
            ],
        },
        "human_feedback": {
            "underwriter_override": status_row.underwriter_override,
            "underwriter_notes": status_row.underwriter_notes,
            "override_at": (
                status_row.override_at.isoformat()
                if status_row.override_at else None
            ),
        },
    }
