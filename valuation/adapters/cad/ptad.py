"""Texas Comptroller PTAD-download adapter.

The Property Tax Assistance Division (PTAD) at the Texas Comptroller
publishes annual property-value-study (PVS) appraisal-roll data for
participating CADs. The published files are available at::

    https://comptroller.texas.gov/taxes/property-tax/data/

…in per-county Excel (.xlsx) workbooks under the "Appraisal Roll" tab,
delivered by tax year. Each row is a parcel; columns vary by year but
the long-stable subset is captured in ``PTAD_COLUMNS`` below.

Architecture
============

Three layers, each independently swappable:

    Cache         — JSON files under ``valuation/_ptad_cache/<slug>/<year>.json``,
                    one row per parcel. Format is documented + stable;
                    ``PTAD_COLUMNS`` lists the keys.

    Loader        — ``_load_year_cache(slug, year)`` reads the cache
                    and returns a list of row dicts. Pure function of
                    disk state; no network, safe to call from any
                    request-handling code path.

    Refresher     — ``scripts/refresh_ptad_cache.py`` (separate
                    process) is what fetches from the live comptroller
                    endpoint and writes the cache. Cron-driven,
                    monthly. Runs out-of-band so user-facing requests
                    never block on a slow PTAD pull.

The adapter (``PTADAdapter`` subclass per county) sits on top of the
loader. It exposes the same ``fetch(parcel_id, *, as_of_date)``
interface as the hand-curated v1 adapters, so callers don't change.

Cache miss policy
-----------------

If the cache file is absent, the adapter returns None (same posture
as a hand-curated adapter for an unknown parcel). This means a county
without a refreshed cache silently skips the Stage 7 section rather
than 500-ing — the report degrades gracefully. Operators see the
absent cache via ``manage.py valuation ptad-cache-status``.
"""

from __future__ import annotations

import abc
import json
import pathlib
from dataclasses import dataclass
from datetime import date
from typing import ClassVar

from valuation.adapters.cad.base import CADAdapter, CADRecord


_CACHE_ROOT = pathlib.Path(__file__).resolve().parents[2] / "_ptad_cache"


# Canonical column names this adapter expects after normalization.
# Implementations of ``_load_year_workbook`` are responsible for
# mapping the PTAD year-specific column names to these keys.
PTAD_COLUMNS = (
    "account_no",          # str — CAD's local parcel identifier
    "property_class_code", # str — e.g. "D1", "D1W", "F1", "C"
    "land_acres",           # float
    "land_productivity_value",  # float (assessed under §23.51)
    "land_market_value",        # float (assessed at market)
    "owner_hash",           # str — anonymized owner ID
    "tax_year",             # int
)


# Per-county class-code → Stage 7 classification keyword map.
#
# This is the bit that varies between counties — a "D1" class in
# Kimble means open-space ag, but the same code in a few coastal
# counties carries a sub-meaning. Each entry below is the safe-to-
# assume mapping for the demo counties; a real productionization
# replaces this with one map per (county_slug, tax_year) keyed off
# the county's published class-code reference.
_CLASSIFICATION_MAP: dict[str, str] = {
    # Edwards Plateau / Hill Country counties
    "D1":  "ag_open_space",
    "D1W": "wildlife_open_space",
    "TIM": "timber",
    # Default for codes not enumerated — the adapter MUST surface
    # "unknown" rather than guess. Downstream scoring treats unknown
    # as "classification factor does not apply."
}


@dataclass
class PTADAdapter(CADAdapter):
    """PTAD-cache-backed CAD adapter.

    Reads the per-county JSON cache written by
    ``scripts/refresh_ptad_cache.py``; lookup is by ``parcel_id`` via
    the county's local ``parcel_id_field`` (CAD account number, by
    default ``account_no``). The hand-curated per-county adapters
    remain a valid alternative for counties whose CAD doesn't appear
    on PTAD; both implement the same interface.
    """

    county_slug: str = ""
    parcel_id_field: str = "account_no"

    def fetch(
        self, parcel_id: str, *, as_of_date: date,
    ) -> CADRecord | None:
        rows = _load_year_cache(self.county_slug, as_of_date.year)
        if rows is None:
            # Cache absent — degrade gracefully. Operators see the
            # gap via ``manage.py valuation ptad-cache-status``.
            return None
        row = next(
            (r for r in rows if r.get(self.parcel_id_field) == parcel_id),
            None,
        )
        if row is None:
            return None

        acres = row.get("land_acres") or 0
        return CADRecord(
            parcel_id=parcel_id,
            county_slug=self.county_slug,
            classification=_CLASSIFICATION_MAP.get(
                row.get("property_class_code", ""), "unknown",
            ),
            assessed_value_per_acre=(
                row["land_productivity_value"] / acres if acres else None
            ),
            market_value_per_acre=(
                row["land_market_value"] / acres if acres else None
            ),
            # PTAD doesn't expose ownership_change_date directly. The
            # refresh script computes it via owner_hash year-over-year
            # diff and writes it into the cached row when available.
            ownership_change_date=_parse_iso_date(
                row.get("ownership_change_date"),
            ),
            as_of_date=as_of_date,
            raw=dict(row),
        )


def _parse_iso_date(s) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


# -- Cache loader ----------------------------------------------------------

def _load_year_cache(county_slug: str, tax_year: int) -> list[dict] | None:
    """Read the JSON cache for one (county, year). Returns a list of
    rows or None when the cache file is absent.

    Cache layout::

        valuation/_ptad_cache/<county_slug>/<year>.json   →  [
            {"account_no": "R042170100", "property_class_code": "D1", ...},
            ...
        ]
    """
    p = cache_path_for(county_slug, tax_year)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def cache_path_for(county_slug: str, tax_year: int) -> pathlib.Path:
    """Resolve the cache file path for one (county, year)."""
    return _CACHE_ROOT / county_slug / f"{tax_year}.json"


def cache_status() -> list[dict]:
    """Return a list of {county_slug, tax_year, rows} for everything
    currently present in the cache. Used by the manage.py status
    command and by alerting cron."""
    out: list[dict] = []
    if not _CACHE_ROOT.exists():
        return out
    for county_dir in sorted(_CACHE_ROOT.iterdir()):
        if not county_dir.is_dir():
            continue
        for cache_file in sorted(county_dir.glob("*.json")):
            try:
                year = int(cache_file.stem)
            except ValueError:
                continue
            try:
                rows = json.loads(cache_file.read_text())
                row_count = len(rows) if isinstance(rows, list) else 0
            except (json.JSONDecodeError, OSError):
                row_count = -1
            out.append({
                "county_slug": county_dir.name,
                "tax_year": year,
                "rows": row_count,
                "path": str(cache_file),
            })
    return out
