"""PTAD cache + adapter tests.

Covers the cache loader, the cache-miss degrade path, and the live-
fetch guard (NotImplementedError until productionized). The simulate
path is exercised end-to-end against a tempdir cache root.
"""

from __future__ import annotations

import json
import pathlib
from datetime import date

import pytest


def _row(**overrides):
    base = {
        "account_no": "R000000001",
        "property_class_code": "D1",
        "land_acres": 1000.0,
        "land_productivity_value": 12_500.0,    # → $12.50/ac assessed
        "land_market_value": 5_000_000.0,       # → $5,000/ac market
        "owner_hash": "test",
        "tax_year": 2025,
        "ownership_change_date": "2025-06-01",
    }
    base.update(overrides)
    return base


@pytest.fixture
def cache_root(tmp_path, monkeypatch):
    """Point the PTAD module's cache root at a tempdir."""
    from valuation.adapters.cad import ptad
    monkeypatch.setattr(ptad, "_CACHE_ROOT", tmp_path)
    return tmp_path


def _write_cache(root: pathlib.Path, slug: str, year: int, rows: list[dict]):
    p = root / slug / f"{year}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    return p


# ---------------------------------------------------------------------------
# Cache loader
# ---------------------------------------------------------------------------

def test_load_returns_none_when_cache_missing(cache_root):
    from valuation.adapters.cad.ptad import _load_year_cache
    assert _load_year_cache("kimble_tx", 2025) is None


def test_load_returns_rows_when_cache_present(cache_root):
    from valuation.adapters.cad.ptad import _load_year_cache
    _write_cache(cache_root, "kimble_tx", 2025, [_row()])
    rows = _load_year_cache("kimble_tx", 2025)
    assert isinstance(rows, list) and len(rows) == 1
    assert rows[0]["account_no"] == "R000000001"


def test_load_handles_corrupt_cache_gracefully(cache_root):
    from valuation.adapters.cad.ptad import _load_year_cache
    p = cache_root / "kimble_tx" / "2025.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not valid json")
    assert _load_year_cache("kimble_tx", 2025) is None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

def test_adapter_returns_none_for_missing_county_cache(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    a = PTADAdapter(county_slug="kimble_tx")
    assert a.fetch("R000000001", as_of_date=date(2025, 10, 1)) is None


def test_adapter_returns_none_for_unknown_parcel(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [_row(account_no="A")])
    a = PTADAdapter(county_slug="kimble_tx")
    assert a.fetch("OTHER", as_of_date=date(2025, 10, 1)) is None


def test_adapter_maps_classification_codes(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [
        _row(account_no="A1", property_class_code="D1"),
        _row(account_no="A2", property_class_code="D1W"),
        _row(account_no="A3", property_class_code="TIM"),
        _row(account_no="A4", property_class_code="ZZZ"),  # unknown code
    ])
    a = PTADAdapter(county_slug="kimble_tx")
    cls = lambda pid: a.fetch(pid, as_of_date=date(2025, 10, 1)).classification
    assert cls("A1") == "ag_open_space"
    assert cls("A2") == "wildlife_open_space"
    assert cls("A3") == "timber"
    assert cls("A4") == "unknown"


def test_adapter_per_acre_normalization(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [
        _row(land_acres=2000.0,
             land_productivity_value=24_800.0,
             land_market_value=9_600_000.0),
    ])
    a = PTADAdapter(county_slug="kimble_tx")
    rec = a.fetch("R000000001", as_of_date=date(2025, 10, 1))
    assert rec.assessed_value_per_acre == pytest.approx(12.40)
    assert rec.market_value_per_acre == pytest.approx(4_800.0)


def test_adapter_handles_missing_acres(cache_root):
    """A row with land_acres == 0 must not divide-by-zero."""
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [
        _row(land_acres=0),
    ])
    a = PTADAdapter(county_slug="kimble_tx")
    rec = a.fetch("R000000001", as_of_date=date(2025, 10, 1))
    assert rec.assessed_value_per_acre is None
    assert rec.market_value_per_acre is None


def test_adapter_parses_ownership_change_date(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [
        _row(ownership_change_date="2024-06-15"),
    ])
    a = PTADAdapter(county_slug="kimble_tx")
    rec = a.fetch("R000000001", as_of_date=date(2025, 10, 1))
    assert rec.ownership_change_date == date(2024, 6, 15)


def test_adapter_tolerates_malformed_ownership_change_date(cache_root):
    from valuation.adapters.cad.ptad import PTADAdapter
    _write_cache(cache_root, "kimble_tx", 2025, [
        _row(ownership_change_date="not-a-date"),
    ])
    a = PTADAdapter(county_slug="kimble_tx")
    rec = a.fetch("R000000001", as_of_date=date(2025, 10, 1))
    assert rec.ownership_change_date is None


# ---------------------------------------------------------------------------
# Cache-status helper
# ---------------------------------------------------------------------------

def test_cache_status_reports_present_files(cache_root):
    from valuation.adapters.cad.ptad import cache_status
    _write_cache(cache_root, "kimble_tx", 2025, [_row(), _row(account_no="A2")])
    _write_cache(cache_root, "brazos_tx", 2025, [_row()])
    entries = cache_status()
    by = {(e["county_slug"], e["tax_year"]): e for e in entries}
    assert by[("kimble_tx", 2025)]["rows"] == 2
    assert by[("brazos_tx", 2025)]["rows"] == 1


def test_cache_status_empty_when_root_missing(tmp_path, monkeypatch):
    from valuation.adapters.cad import ptad
    monkeypatch.setattr(ptad, "_CACHE_ROOT", tmp_path / "does-not-exist")
    assert ptad.cache_status() == []


# ---------------------------------------------------------------------------
# Refresh script — simulate path
# ---------------------------------------------------------------------------

def test_refresh_simulate_writes_fixture(cache_root, monkeypatch):
    """The simulate fixture should produce a valid cache file the
    adapter can read end-to-end."""
    from scripts import refresh_ptad_cache
    monkeypatch.setattr(
        refresh_ptad_cache, "_DEFAULT_COUNTIES", ["kimble_tx"],
    )
    rc = refresh_ptad_cache.main([
        "--year", "2025", "--simulate", "--counties", "kimble_tx",
    ])
    assert rc == 0
    cache_file = cache_root / "kimble_tx" / "2025.json"
    assert cache_file.exists()
    rows = json.loads(cache_file.read_text())
    assert rows[0]["account_no"] == "R042170100"


def test_refresh_no_simulate_raises(cache_root, monkeypatch):
    """Live fetch is not yet wired; --no-simulate should fail loud
    rather than silently degrade."""
    from scripts import refresh_ptad_cache
    rc = refresh_ptad_cache.main([
        "--year", "2025", "--no-simulate", "--counties", "kimble_tx",
    ])
    # Returns 1 because live fetch raises NotImplementedError; the
    # script catches that and reports a per-county failure.
    assert rc == 1
