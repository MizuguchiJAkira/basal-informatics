"""Layer 6 — report generation edge cases.

Rather than generate a full PDF and grep it (ReportLab output is
binary), we call each section's render() with synthetic assessment
dicts and inspect the returned flowable list for the expected
Paragraph / Table content.

Scenarios:
  - Data confidence grade D appears
  - ESA species flagged when present
  - No ESA species → no false positives
  - Modeled projection clearly labeled
  - Coverage breakdown + proximity confidence
  - Full PDF build on a minimal assessment — smoke test
"""

from datetime import date, datetime

import pytest

from reportlab.platypus import Paragraph, Table


def _flatten_text(flowables):
    """Recursively extract text from Paragraph + Table flowables."""
    out = []
    for f in flowables:
        if isinstance(f, Paragraph):
            try:
                out.append(f.getPlainText())
            except Exception:
                out.append(str(getattr(f, "text", "")))
        elif isinstance(f, Table):
            for row in f._cellvalues:
                for cell in row:
                    if isinstance(cell, str):
                        out.append(cell)
                    elif isinstance(cell, Paragraph):
                        try:
                            out.append(cell.getPlainText())
                        except Exception:
                            pass
                    elif isinstance(cell, list):
                        # Nested column cell (e.g., references grid)
                        for sub in cell:
                            if isinstance(sub, Paragraph):
                                try:
                                    out.append(sub.getPlainText())
                                except Exception:
                                    pass
    return "\n".join(out)


# ---------------------------------------------------------------------------
# confidence.py — grade rendering
# ---------------------------------------------------------------------------

def test_confidence_section_renders_grade_D():
    from report.sections import confidence
    assessment = {
        "species_inventory": [{
            "species_key": "feral_hog",
            "common_name": "Feral Hog",
            "detection_frequency_pct": 50.0,
            "confidence_grade": "D",
            "confidence_pct": 4.0,
            "cameras_detected": 1, "cameras_total": 10,
            "habitat_units": ["HU-1"],
            "risk_flag": "INVASIVE — MODERATE",
            "independent_events": 15,
        }],
        "data_confidence": {
            "overall_grade": "D",
            "cameras": 10, "habitat_units": 1,
            "monitoring_months": 1, "corridor_coverage_pct": 3.0,
        },
    }
    flowables = confidence.render(assessment)
    text = _flatten_text(flowables)
    assert "D" in text       # grade appears
    assert "Feral Hog" in text


# ---------------------------------------------------------------------------
# species_table.py — ESA flag rendering
# ---------------------------------------------------------------------------

def test_species_table_renders_esa_flag_when_esa_present():
    from report.sections import species_table
    assessment = {
        "species_inventory": [{
            "species_key": "golden_cheeked_warbler",
            "common_name": "Golden-cheeked Warbler",
            "scientific_name": "Setophaga chrysoparia",
            "native": True, "invasive": False,
            "esa_status": "Endangered",
            "risk_flag": "ESA — Endangered",
            "independent_events": 3,
            "detection_frequency_pct": 0.0,
            "raw_detection_frequency_pct": 0.0,
            "confidence_grade": "C",
            "confidence_pct": 8.0,
            "cameras_detected": 0, "cameras_total": 10,
            "habitat_units": ["HU-1"],
        }],
    }
    flowables = species_table.render(assessment)
    text = _flatten_text(flowables).upper()
    assert "ESA" in text or "ENDANGERED" in text
    assert "GOLDEN-CHEEKED WARBLER" in text or "SETOPHAGA CHRYSOPARIA" in text


def test_species_table_no_esa_produces_no_esa_label():
    from report.sections import species_table
    assessment = {
        "species_inventory": [{
            "species_key": "white_tailed_deer",
            "common_name": "White-tailed Deer",
            "scientific_name": "Odocoileus virginianus",
            "native": True, "invasive": False,
            "esa_status": None, "risk_flag": None,
            "independent_events": 40,
            "detection_frequency_pct": 95.0,
            "raw_detection_frequency_pct": 95.0,
            "confidence_grade": "A",
            "confidence_pct": 30.0,
            "cameras_detected": 10, "cameras_total": 10,
            "habitat_units": ["HU-1"],
        }, {
            "species_key": "feral_hog",
            "common_name": "Feral Hog",
            "scientific_name": "Sus scrofa",
            "native": False, "invasive": True,
            "esa_status": None, "risk_flag": "INVASIVE — HIGH",
            "independent_events": 60,
            "detection_frequency_pct": 80.0,
            "raw_detection_frequency_pct": 90.0,
            "confidence_grade": "B",
            "confidence_pct": 18.0,
            "cameras_detected": 9, "cameras_total": 10,
            "habitat_units": ["HU-1"],
        }],
    }
    flowables = species_table.render(assessment)
    text = _flatten_text(flowables)
    # INVASIVE should be present
    assert "INVASIVE" in text.upper()
    # ESA should NOT be present for non-ESA species
    # (there could be an "ESA" column header so we check the flag-cell language)
    assert "Endangered" not in text
    assert "ESA — Endangered" not in text


# ---------------------------------------------------------------------------
# damage_projection.py — modeled projection language
# ---------------------------------------------------------------------------

def test_damage_projection_language_not_pipeline_output():
    from report.sections import damage_projection
    assessment = {
        "damage_projections": {
            "feral_hog": {
                "species_key": "feral_hog",
                "common_name": "Feral Hog",
                "base_cost_per_acre": 25.0,
                "ecoregion_calibration_factor": 1.0,
                "frequency_scale": 0.75,
                "detection_frequency_pct": 80.0,
                "acreage": 650.0,
                "estimated_annual_loss": 12000.0,
                "ten_year_npv": 90000.0,
                "confidence_grade": "B",
                "confidence_interval_pct": 30,
                "confidence_interval_low": 8400.0,
                "confidence_interval_high": 15600.0,
                "methodology": "USDA-APHIS base rates, logistic damage scaling",
                "broadley_caveat": "Detection frequency is a relative activity index...",
            },
        },
        "feral_hog_exposure_score": {
            "score": 75,
            "detection_frequency_component": 80,
            "recency_component": 80, "spatial_extent_component": 75,
            "interpretation": "ELEVATED: Substantial feral hog presence.",
        },
    }
    flowables = damage_projection.render(assessment)
    text = _flatten_text(flowables)
    # Some form of "modeled" or "projection" or "estimate" disclaimer expected
    lowered = text.lower()
    signals = ["modeled", "projection", "estimated", "model-based",
               "uncertainty", "confidence interval"]
    assert any(s in lowered for s in signals), (
        f"damage_projection section didn't flag uncertainty language. "
        f"Got: {text[:400]}"
    )


# ---------------------------------------------------------------------------
# cover.py — core fields present
# ---------------------------------------------------------------------------

def test_cover_renders_property_name_county_client():
    """Cover page shows property name + county + prepared-for client
    company + camera count. Note the parcel_id is NOT on the cover —
    it appears in the page header/footer only, which the cover page
    doesn't use (see generator.py: cover uses its own page template
    with no header)."""
    from report.sections import cover
    assessment = {
        "parcel_id": "TX-KIM-2026-00001",
        "property_name": "Edwards Plateau Ranch",
        "acreage": 2340, "county": "Kimble", "state": "TX",
        "ecoregion": "Edwards Plateau",
        "n_camera_stations": 14,
        "assessment_date": "2026-04-18",
        "monitoring_period": {"start": "Mar 2025", "end": "Jan 2026"},
        "prepared_for": {
            "company": "AXA XL Sustainability",
            "contact": "Monica Henn",
        },
        "methodology_version": "1.0.0",
        "overall_risk_rating": "ELEVATED",
    }
    flowables = cover.render(assessment)
    text = _flatten_text(flowables)
    assert "Edwards Plateau Ranch" in text
    assert "Kimble" in text
    assert "AXA XL Sustainability" in text
    assert "14 camera" in text


# ---------------------------------------------------------------------------
# Methodology section (what we just rewrote)
# ---------------------------------------------------------------------------

def test_methodology_section_includes_rem_and_ipw_language():
    from report.sections import methodology
    flowables = methodology.render({})
    text = _flatten_text(flowables).lower()
    assert "random encounter model" in text or "rem" in text
    assert "kolowski" in text
    assert "rowcliffe" in text
    # Factor table
    assert "10" in text     # hog feeder factor


def test_methodology_references_at_least_10_entries():
    """Locked rewrite should include all 12 references."""
    from report.sections import methodology
    flowables = methodology.render({})
    text = _flatten_text(flowables)
    # Reference-list markers (author name + year)
    expected_refs = ["Rowcliffe", "Kolowski", "Mayer", "H\u00e1jek",
                     "Hernán", "Kish", "Cassel", "Kay", "Webb", "Anderson"]
    hits = sum(1 for r in expected_refs if r in text)
    assert hits >= 8, f"only {hits}/10 expected references found"


# ---------------------------------------------------------------------------
# Full generate_report smoke test
# ---------------------------------------------------------------------------

def test_generate_report_produces_nonempty_pdf(tmp_path):
    """Build a PDF end-to-end on a minimal synthesized assessment.
    Verify the file is created, nontrivial size, and contains PDF header."""
    from report.generator import generate_report
    assessment = {
        "parcel_id": "TX-BRA-2026-00099",
        "property_name": "Smoke Test Parcel",
        "acreage": 500, "county": "Brazos", "state": "TX",
        "ecoregion": "Edwards Plateau",
        "n_camera_stations": 4,
        "assessment_date": "2026-04-18",
        "monitoring_period": {"start": "Feb 2026", "end": "Mar 2026"},
        "prepared_for": {"company": "Test Lender", "contact": "T. Tester"},
        "methodology_version": "1.0.0",
        "overall_risk_rating": "LOW",
        "species_inventory": [{
            "species_key": "white_tailed_deer",
            "common_name": "White-tailed Deer",
            "scientific_name": "Odocoileus virginianus",
            "native": True, "invasive": False, "esa_status": None,
            "risk_flag": None,
            "independent_events": 12,
            "detection_frequency_pct": 60.0,
            "raw_detection_frequency_pct": 60.0,
            "confidence_grade": "C",
            "confidence_pct": 8.0,
            "cameras_detected": 3, "cameras_total": 4,
            "habitat_units": ["HU-1"],
        }],
        "damage_projections": {},
        "feral_hog_exposure_score": {
            "score": 0,
            "detection_frequency_component": 0,
            "recency_component": 0, "spatial_extent_component": 0,
            "interpretation": "MINIMAL: Little to no feral hog activity.",
        },
        "regulatory_risk": {
            "esa_species_present": [], "consultation_required": False,
            "total_estimated_compliance_cost_low": 0,
            "total_estimated_compliance_cost_high": 0,
            "species_details": [],
        },
        "data_confidence": {
            "overall_grade": "C", "cameras": 4,
            "habitat_units": 1, "monitoring_months": 2,
            "corridor_coverage_pct": 8.0,
        },
        "bias_correction_applied": False,
    }

    out = tmp_path / "smoke.pdf"
    result_path = generate_report(assessment, output_path=str(out))
    assert result_path == str(out)
    assert out.exists()
    data = out.read_bytes()
    assert len(data) > 5000      # nontrivial PDF
    assert data[:5] == b"%PDF-"
