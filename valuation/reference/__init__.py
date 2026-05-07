"""Static reference dataset loader for the Stage 7 valuation module.

The three YAML files in this package are hand-curated snapshots of:

    ecoregion_intensity.yaml   — Comptroller manual: 8 wildlife regions
                                  + reduced-acreage minimums.
    tpwd_seven_practices.yaml  — TPWD: the 7 qualifying practices.
    county_to_ecoregion.yaml   — Texas county → ecoregion lookup.

They are loaded once at import time. They are NOT regenerated from
external sources at runtime. To update a value, edit the YAML — the
audit trail of "what numbers we used when" is the file's git history.
"""

from __future__ import annotations

import pathlib

import yaml


_HERE = pathlib.Path(__file__).resolve().parent


def _load(name: str) -> dict:
    """Load one YAML file from this package directory."""
    with open(_HERE / name) as f:
        return yaml.safe_load(f) or {}


# Loaded eagerly at import. All three datasets are tiny (< 5 KB each)
# so the up-front cost is negligible and downstream callers don't need
# to remember to call a loader.
ECOREGION_INTENSITY: dict = _load("ecoregion_intensity.yaml")
TPWD_SEVEN_PRACTICES: dict = _load("tpwd_seven_practices.yaml")
DROUGHT_PDSI: dict = _load("drought_pdsi.yaml")
EFFECTIVE_TAX_RATES: dict = _load("effective_tax_rate.yaml")


# County → ecoregion lookup. The YAML stores the inverse (ecoregion →
# list of counties) for editorial readability — Texas has 254 counties
# and a flat list grouped by ecoregion is much easier to audit by eye
# than a 254-line county-keyed map. Invert at load time.
def _build_county_to_ecoregion() -> dict[str, str]:
    raw = _load("county_to_ecoregion.yaml")
    out: dict[str, str] = {}
    for ecoregion, counties in raw.items():
        if not isinstance(counties, list):
            continue
        for county in counties:
            key = str(county).strip().lower()
            if key in out and out[key] != ecoregion:
                # Document which ecoregion a boundary county landed in
                # so the YAML edit history is the source of truth.
                raise ValueError(
                    f"county {key!r} listed under both "
                    f"{out[key]!r} and {ecoregion!r} — pick one."
                )
            out[key] = ecoregion
    return out


COUNTY_TO_ECOREGION: dict = _build_county_to_ecoregion()


def ecoregion_for_county(county: str) -> str | None:
    """Resolve a Texas county name to its ecoregion key.

    Case-insensitive on the county name; whitespace and the trailing
    "County" suffix are tolerated so the same lookup works whether the
    caller passes "Kimble", "kimble", "Kimble County", or "  KIMBLE  ".

    Returns None when the county isn't in the v1 lookup. Callers are
    expected to fail loud on None rather than silently use a default
    ecoregion — picking the wrong region would change the qualifying-
    practices intensity standards and therefore the eligibility output.
    """
    if not county:
        return None
    key = county.strip().lower()
    if key.endswith(" county"):
        key = key[: -len(" county")]
    return COUNTY_TO_ECOREGION.get(key)


def ecoregion_for_parcel_geometry(boundary_geojson: str) -> str | None:
    """Spatial fallback: resolve a parcel's ecoregion from its boundary.

    For parcels whose county isn't in the static lookup, or that span
    a boundary where county-level resolution is wrong, this would do a
    PostGIS spatial intersect against the EPA Level III ecoregion
    polygon layer.

    v1 stub: not implemented. Returns None so callers transparently
    fall through to the county-level lookup. v1.1 implementation:

        1. Load the EPA Level III TX ecoregion polygons into PostGIS
           on first call (one-shot, cached).
        2. Parse boundary_geojson, run ``ST_Intersects`` against each
           ecoregion polygon, return the one with greatest overlap
           area.

    The deferred implementation is documented here so the call site
    in valuation/compute.py can already use it; flipping the stub
    over to live PostGIS is a one-file change.
    """
    return None


def practice_keys() -> list[str]:
    """Stable list of the seven TPWD practice keys, in declared order."""
    return list(TPWD_SEVEN_PRACTICES.keys())


def effective_tax_rate_for_county(county: str) -> float:
    """Resolve a county to its combined effective property-tax rate.

    Returns the county-level average from
    ``effective_tax_rate.yaml`` when known; otherwise the
    ``DEFAULT`` entry (Texas state average, 2.0%). Same name
    normalization as the other lookups.

    Note: rates here are county *averages*. For a parcel sitting
    inside a city or MUD with above-average levies, a CAD adapter
    can pass an override into ``estimate_rollback_tax`` directly.
    """
    default = float(EFFECTIVE_TAX_RATES.get("DEFAULT", 0.02))
    if not county:
        return default
    key = county.strip().lower()
    if key.endswith(" county"):
        key = key[: -len(" county")]
    val = EFFECTIVE_TAX_RATES.get(key)
    if val is None:
        return default
    return float(val)


def drought_level_for_county(county: str) -> str:
    """Resolve a county to its rolling-24-month drought level.

    Returns "neutral" when the county isn't in the snapshot — the
    scoring rubric documents this as "considered, evidence absent"
    rather than fabricating a worse signal. Same name normalization
    as ``ecoregion_for_county``.
    """
    if not county:
        return "neutral"
    key = county.strip().lower()
    if key.endswith(" county"):
        key = key[: -len(" county")]
    return DROUGHT_PDSI.get("levels", {}).get(key, "neutral")
