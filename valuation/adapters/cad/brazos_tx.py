"""Brazos County (TX) CAD adapter — v1 hand-curated snapshot.

Riverbend Farm sits here. Demo data tuned to surface a *distinct* risk
band from Edwards Plateau Ranch: row-crop ag (corn) on Post Oak
Savannah land with a recent ownership change and tighter assessed-vs-
market spread. The combination should land in a higher band than the
Kimble parcel even though both are currently 1-d-1.

This file is structurally identical to ``kimble_tx.py``; both follow
the template defined by ``CADAdapter`` in ``base.py``.
"""

from __future__ import annotations

from datetime import date

from valuation.adapters.cad.base import CADAdapter, CADRecord


_RECORDS = {
    "TX-BRA-2026-00002": {
        "classification": "ag_open_space",
        # Productivity-based ag valuation for row-crop corn — higher
        # than grazing because corn productivity per acre is greater.
        "assessed_value_per_acre": 38.20,
        # Brazos County market values reflect college-town pressure
        # (Texas A&M / Bryan-College Station); ranchland comparables
        # within the county trade higher than Hill Country open range.
        "market_value_per_acre": 7_400.00,
        # Recent change → triggers ownership_change_recent factor with
        # higher weight than the Kimble parcel's older transfer.
        "ownership_change_date": date(2025, 11, 22),
        "raw": {
            "cad_account_no": "BRA-RBF-09144",
            "ag_class_code": "1-D-1",
            "appraisal_year": 2025,
            "primary_ag_use": "row_crop_corn",
            "irrigated_acres": 412,
        },
    },
}


class BrazosCADAdapter(CADAdapter):
    county_slug = "brazos_tx"

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
