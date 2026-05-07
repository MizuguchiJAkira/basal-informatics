"""Llano County (TX) CAD adapter — v1 hand-curated snapshot.

Llano Highlands sits here. The point of this third demo parcel is to
exercise the *post-conversion* state: a ranch that has already moved
from 1-d-1 to 1-d-1(w) wildlife appraisal and now operates against
the seven TPWD practices instead of grazing intensity. The adapter
returns ``classification = "wildlife_open_space"``, which suppresses
the classification_vulnerable factor in scoring and keeps the band
low absent other risk drivers.

Same template as the other county adapters; new counties are a one-
line edit to ``valuation/adapters/cad/__init__.py`` once the snapshot
file lands.
"""

from __future__ import annotations

from datetime import date

from valuation.adapters.cad.base import CADAdapter, CADRecord


_RECORDS = {
    "TX-LLA-2026-00006": {
        "classification": "wildlife_open_space",       # 1-d-1(w)
        # Wildlife appraisal carries a productivity-style assessment
        # similar to ag-open-space; per-acre often slightly higher
        # than grazing under §23.521 wildlife valuation tables.
        "assessed_value_per_acre": 14.80,
        # Llano Co. land prices reflect Hill Country tourism demand
        # and improved-pasture comps; market trades higher than
        # remote NE-Kimble rangeland.
        "market_value_per_acre": 5_600.00,
        # Long-tenured ownership — no transfer in 11 years. Should
        # NOT trigger ownership_change_recent.
        "ownership_change_date": date(2015, 3, 9),
        "raw": {
            "cad_account_no": "LLA-LH-02873",
            "ag_class_code": "1-D-1(W)",
            "appraisal_year": 2025,
            "primary_ag_use": "wildlife_management",
            "wildlife_plan_filed": True,
            "wildlife_plan_filed_year": 2018,
        },
    },
}


class LlanoCADAdapter(CADAdapter):
    county_slug = "llano_tx"

    def fetch(
        self, parcel_id: str, *, as_of_date: date,
    ) -> CADRecord | None:
        rec = _RECORDS.get(parcel_id)
        if not rec:
            return None
        return CADRecord(
            parcel_id=parcel_id,
            county_slug=self.county_slug,
            classification=rec["classification"],
            assessed_value_per_acre=rec["assessed_value_per_acre"],
            market_value_per_acre=rec["market_value_per_acre"],
            ownership_change_date=rec["ownership_change_date"],
            as_of_date=as_of_date,
            raw=dict(rec["raw"]),
        )
