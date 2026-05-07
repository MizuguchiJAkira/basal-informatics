"""Kimble County (TX) CAD adapter — v1 hand-curated snapshot.

Kimble CAD does not publish bulk parcel data, so v1 ships a hand-
curated snapshot for the known demo parcels. The shape of this file
is the template for any other county that needs to be added before
PTAD-download integration is built: define ``_RECORDS``, mapping
parcel-id strings to dictionaries of CAD fields.

When PTAD-download or scrape-based implementations are built, this
file gets replaced with one that pulls from the live source; the
adapter interface (``CADAdapter.fetch``) does not change.
"""

from __future__ import annotations

from datetime import date

from valuation.adapters.cad.base import CADAdapter, CADRecord


# Hand-curated snapshot. Values reflect a typical 1-d-1 (open-space
# agricultural) appraisal in Edwards Plateau ranchland: assessed on
# productivity, very low per-acre; market value reflects current Hill
# Country land prices. Ownership change date set to a recent value to
# exercise the ownership_change_recent risk factor on the demo parcel.
_RECORDS = {
    "TX-KIM-2026-00001": {
        "classification": "ag_open_space",
        "assessed_value_per_acre": 12.40,    # productivity-based
        "market_value_per_acre": 4_800.00,   # current Hill Country
        "ownership_change_date": date(2024, 6, 15),
        "raw": {
            "cad_account_no": "KIM-EPR-04217",
            "ag_class_code": "1-D-1",
            "appraisal_year": 2025,
            "stocking_rate_aum": 0.18,
            "primary_ag_use": "grazing_native_pasture",
        },
    },
}


class KimbleCADAdapter(CADAdapter):
    county_slug = "kimble_tx"

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
