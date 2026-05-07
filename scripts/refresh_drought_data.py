#!/usr/bin/env python3
"""Refresh ``valuation/reference/drought_pdsi.yaml`` from NOAA NCEI.

Stage 7's ``drought_pdsi_24mo`` factor reads a static county→level
snapshot to decide whether the drought driver fires on a parcel.
Production deploys want this snapshot refreshed monthly because the
rolling 24-month PDSI moves each month; this script is the cron-able
entry point.

Source data:

    NOAA NCEI Climate at a Glance — county time series:
    https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/county/

    The relevant variable is the 24-month-window Palmer Drought
    Severity Index (PDSI) at the county level. The endpoint returns
    monthly values; we read the most recent available month and map
    it to one of the four levels Stage 7 understands::

        ≥ -1.99               → neutral
        -2.00  to  -2.99      → mild
        -3.00  to  -3.99      → moderate
        ≤ -4.00               → severe

Usage::

    python scripts/refresh_drought_data.py
    python scripts/refresh_drought_data.py --dry-run         # don't write
    python scripts/refresh_drought_data.py --counties=kimble,brazos

Cron::

    # /etc/cron.d/basal — first day of each month at 04:30
    30 4 1 * *  basal  /opt/basal/.venv/bin/python \
        /opt/basal/scripts/refresh_drought_data.py >> /var/log/basal/drought.log 2>&1

NETWORK ACCESS NOT YET WIRED. The NOAA fetch path is documented
inline as a deferred implementation; the script currently runs in
``--simulate`` mode (default for v1), which preserves the YAML
structure and stamps a fresh ``snapshot_date`` without actually
hitting NOAA. Production deploys that need live data should
implement ``_fetch_pdsi_for_county`` against the NCEI endpoint and
remove the simulate gate.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import pathlib
import sys

import yaml


_HERE = pathlib.Path(__file__).resolve().parent
_REF = _HERE.parent / "valuation" / "reference"
_YAML_PATH = _REF / "drought_pdsi.yaml"


def _level_from_pdsi(pdsi: float) -> str:
    """Map a 24-month-window PDSI value to one of the four levels."""
    if pdsi <= -4.00:
        return "severe"
    if pdsi <= -3.00:
        return "moderate"
    if pdsi <= -2.00:
        return "mild"
    return "neutral"


# Texas county → NOAA NCEI county code. The county code is the last
# five digits of the FIPS code (state 48 is Texas; "001" suffix gives
# Anderson County full FIPS 48001, NCEI county code "001"). The full
# table is canonical and lives elsewhere; the snippet here is for the
# 15 counties already in the demo + a placeholder pattern. A full
# build of this map is part of the productionize-this-script PR.
_COUNTY_NCEI_CODES = {
    "kimble":    "267",
    "llano":     "299",
    "mason":     "319",
    "sutton":    "435",
    "edwards":   "137",
    "real":      "385",
    "bandera":   "019",
    "kerr":      "265",
    "gillespie": "171",
    "blanco":    "031",
    "brazos":    "041",
    "burleson":  "051",
    "robertson": "395",
    "lee":       "287",
    "bastrop":   "021",
}


def _fetch_pdsi_for_county(county_slug: str, *, month: _dt.date) -> float | None:
    """Fetch the 24-month rolling PDSI for one county for one month.

    NOT IMPLEMENTED. The production version pulls JSON from::

        https://www.ncei.noaa.gov/access/monitoring/climate-at-a-glance/
        county/time-series/<state_fips>-<county_code>/pdsi/24/<YYYYMM>-<YYYYMM>.json

    Returns the most recent PDSI value or None if the county isn't in
    the NOAA dataset. Until the live fetch lands, the simulate path
    (below) is used.
    """
    # Productionization checklist:
    #   1. requests.get(url) with retry/backoff, 30s timeout.
    #   2. Parse the JSON ``data`` envelope; the "value" field is the
    #      24-month PDSI for the requested month.
    #   3. Cache responses for 24h to avoid hammering NOAA across
    #      multiple workers.
    #   4. Add the script to acceptable-use review with NCEI.
    return None


def _simulate_levels(prev: dict) -> dict:
    """When --simulate (or the fetch is not yet wired), preserve the
    YAML structure unchanged but stamp a fresh ``snapshot_date``. The
    cron entry still runs and writes a file every month; the values
    only flip when an operator updates them by hand or once the
    NOAA fetch is wired."""
    out = dict(prev)
    out["snapshot_date"] = _dt.date.today().isoformat()
    return out


_HEADER_SENTINEL = "# ----- AUTO-REFRESHED BLOCK BELOW"


def _write_yaml(data: dict, *, dry_run: bool) -> None:
    """Rewrite the YAML preserving the documented header comments.

    The file's top comments (source attribution, level definitions,
    audit notes) are NOT round-trippable through yaml.safe_dump.
    Strategy: split on the AUTO-REFRESHED sentinel, keep the header
    verbatim, and rewrite only the data block underneath. If the
    sentinel is missing (corrupted file), fall back to writing the
    full document and emit a warning the operator can act on.
    """
    body = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    full = _YAML_PATH.read_text() if _YAML_PATH.exists() else ""
    if _HEADER_SENTINEL in full:
        header = full.split(_HEADER_SENTINEL, 1)[0]
        out = header + _HEADER_SENTINEL + " (do not edit comments below this line) -----\n" + body
    else:
        print(
            f"warning: {_YAML_PATH} has no header sentinel; rewriting "
            f"without comments. Restore the header from git if "
            f"unintentional.",
            file=sys.stderr,
        )
        out = body
    if dry_run:
        print("--- would write to", _YAML_PATH, "---")
        print(out)
        return
    _YAML_PATH.write_text(out)
    print(f"wrote {_YAML_PATH} ({len(out)} bytes)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Print the new YAML to stdout without overwriting the file.",
    )
    ap.add_argument(
        "--counties", default="",
        help="Comma-separated subset (e.g. 'kimble,brazos'); default all.",
    )
    ap.add_argument(
        "--simulate", action="store_true", default=True,
        help=("Don't hit NOAA; stamp a fresh snapshot_date and "
              "preserve current values. The default until the live "
              "fetch path is implemented."),
    )
    ap.add_argument(
        "--no-simulate", dest="simulate", action="store_false",
        help="Hit NOAA NCEI for live PDSI values (requires fetch impl).",
    )
    args = ap.parse_args(argv)

    if not _YAML_PATH.exists():
        print(f"missing input YAML: {_YAML_PATH}", file=sys.stderr)
        return 2
    prev = yaml.safe_load(_YAML_PATH.read_text())

    if args.simulate:
        data = _simulate_levels(prev)
        _write_yaml(data, dry_run=args.dry_run)
        return 0

    target = (
        {c.strip().lower() for c in args.counties.split(",") if c.strip()}
        or set(prev.get("levels", {}).keys())
    )
    today = _dt.date.today()
    new_levels = dict(prev.get("levels", {}))
    failed: list[str] = []
    for county in sorted(target):
        if county not in _COUNTY_NCEI_CODES:
            failed.append(f"{county} (no NCEI code mapping)")
            continue
        pdsi = _fetch_pdsi_for_county(county, month=today)
        if pdsi is None:
            failed.append(county)
            continue
        new_levels[county] = _level_from_pdsi(pdsi)

    if failed:
        print(
            f"warning: {len(failed)} counties failed to fetch — "
            f"keeping previous values for: {', '.join(failed)}",
            file=sys.stderr,
        )

    out = {"snapshot_date": today.isoformat(), "levels": new_levels}
    _write_yaml(out, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
