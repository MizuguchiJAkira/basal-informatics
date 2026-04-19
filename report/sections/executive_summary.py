"""Executive summary — one page of key findings.

Overall risk rating badge. Feral Hog Exposure Score as a big number.
3-4 bullet key findings. Template-generated one-paragraph summary.
"""

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from report.styles import (
    TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE,
    BRAND_NAVY, BRAND_BLUE, BRAND_TEAL, SECTION_BAR_TEXT,
    FONTS, COLORS, CONTENT_WIDTH,
    STYLE_H2, STYLE_BODY, STYLE_BODY_SMALL,
    STYLE_METRIC_LARGE, STYLE_METRIC_LABEL, STYLE_FOOTNOTE,
    section_bar, risk_color,
)


def render(assessment: dict) -> list:
    """Return flowables for the executive summary page."""
    elements = []

    elements.append(section_bar("Executive Summary", CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    # ── Headline row — two typographic figures, no badges, no fills ──
    # GS / McKinsey idiom: Fraunces-Bold numerals with italic serif
    # labels above, separated by a thin vertical rule. No filled
    # wordmark blocks, no gauges.
    from reportlab.lib.enums import TA_LEFT as _TA_L
    rating = assessment.get("overall_risk_rating", "MODERATE")
    rating_color = risk_color(rating)
    fh = assessment.get("feral_hog_exposure_score") or {}
    fh_score = fh.get("score", "N/A")

    lbl_style = ParagraphStyle(
        "HdrLabel",
        fontName=FONTS["serif_italic"], fontSize=8.5, leading=11,
        textColor=TEXT_SECONDARY, alignment=_TA_L,
    )
    rating_value = ParagraphStyle(
        "RatingValue",
        fontName=FONTS["serif_bold"], fontSize=22, leading=26,
        textColor=rating_color, alignment=_TA_L,
    )
    score_value = ParagraphStyle(
        "ScoreValue",
        fontName=FONTS["serif_bold"], fontSize=22, leading=26,
        textColor=BRAND_NAVY, alignment=_TA_L,
    )

    left_cell = [
        Paragraph("Overall Nature-Risk Rating", lbl_style),
        Spacer(1, 0.02 * inch),
        Paragraph(rating.title(), rating_value),
    ]
    right_cell = [
        Paragraph("Feral Hog Exposure Score", lbl_style),
        Spacer(1, 0.02 * inch),
        Paragraph(
            f"{fh_score}"
            f"<font size='13' color='{COLORS['text_secondary']}'>"
            f"  / 100</font>",
            score_value),
    ]

    top_row = Table(
        [[left_cell, right_cell]],
        colWidths=[CONTENT_WIDTH * 0.5, CONTENT_WIDTH * 0.5],
    )
    top_row.setStyle(TableStyle([
        ("VALIGN",     (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE",  (0, 0), (-1, 0), 0.5, BRAND_NAVY),
        ("LINEBELOW",  (0, -1), (-1, -1), 0.5, BRAND_NAVY),
        ("LINEAFTER",  (0, 0), (0, 0), 0.3, GRIDLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",  (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    elements.append(top_row)
    elements.append(Spacer(1, 0.14 * inch))

    # ── Summary paragraph ──
    summary_text = _generate_summary(assessment)
    elements.append(Paragraph(summary_text, STYLE_BODY))
    elements.append(Spacer(1, 0.15 * inch))

    # ── Key findings bullets ──
    elements.append(Paragraph("Key Findings", STYLE_H2))
    findings = _generate_findings(assessment)
    for finding in findings:
        elements.append(Paragraph(
            f'<bullet>&bull;</bullet> {finding}', STYLE_BODY))

    # ── Summary metrics table ──
    elements.append(Spacer(1, 0.12 * inch))
    elements.append(Paragraph("Assessment Metrics", STYLE_H2))

    n_species = len(assessment.get("species_inventory", []))
    n_invasive = sum(1 for s in assessment.get("species_inventory", [])
                     if s.get("invasive"))
    total_annual = sum(
        p.get("estimated_annual_loss", 0)
        for p in assessment.get("damage_projections", {}).values())
    dc = assessment.get("data_confidence", {})
    overall_grade = dc.get("overall_grade", "N/A")
    mon_months = dc.get("monitoring_months", 0)
    cam_density = dc.get("camera_density_per_km2", 0)
    bias_applied = assessment.get("bias_correction_applied", False)
    reg = assessment.get("regulatory_risk", {})
    n_esa = len(reg.get("esa_species_present", []))

    metrics = [
        ["Species detected", str(n_species),
         "Invasive species", str(n_invasive)],
        ["Est. annual loss", f"${total_annual:,.0f}",
         "ESA species flagged", str(n_esa)],
        ["Monitoring months", str(mon_months),
         "Camera density", f"{cam_density:.2f}/km\u00b2"],
        ["Data confidence", overall_grade,
         "Bias correction", "Applied" if bias_applied else "Not needed"],
    ]
    mt = Table(metrics, colWidths=[1.5 * inch, 2.0 * inch,
                                   1.5 * inch, 2.0 * inch])
    mt.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONTS["body"]),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), FONTS["serif_italic"]),
        ("FONTNAME", (2, 0), (2, -1), FONTS["serif_italic"]),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_SECONDARY),
        ("TEXTCOLOR", (2, 0), (2, -1), TEXT_SECONDARY),
        ("FONTNAME", (1, 0), (1, -1), FONTS["serif_bold"]),
        ("FONTNAME", (3, 0), (3, -1), FONTS["serif_bold"]),
        ("TEXTCOLOR", (1, 0), (1, -1), BRAND_NAVY),
        ("TEXTCOLOR", (3, 0), (3, -1), BRAND_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, BRAND_NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, BRAND_NAVY),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRIDLINE),
    ]))
    elements.append(mt)

    return elements


def _generate_summary(a: dict) -> str:
    """Template-generated one-paragraph executive summary."""
    county = a.get("county", "")
    state = a.get("state", "")
    acreage = a.get("acreage", 0)
    rating = a.get("overall_risk_rating", "MODERATE")
    n_sp = len(a.get("species_inventory", []))
    inv_sp = [s for s in a.get("species_inventory", []) if s.get("invasive")]
    fh = a.get("feral_hog_exposure_score", {})
    fh_score = fh.get("score", 0)
    total_annual = sum(
        p.get("estimated_annual_loss", 0)
        for p in a.get("damage_projections", {}).values())

    inv_names = ", ".join(s["common_name"] for s in inv_sp[:3])
    bias_note = ("Detection frequencies are IPW-adjusted for non-random "
                 "camera placement." if a.get("bias_correction_applied")
                 else "")

    return (
        f"This assessment covers a {acreage:,.0f}-acre parcel in "
        f"{county} County, {state}. Camera trap monitoring detected "
        f"{n_sp} species across the property, including {len(inv_sp)} "
        f"invasive species ({inv_names}). The overall nature exposure "
        f'risk is rated <b>{rating}</b> with a Feral Hog Exposure Score '
        f"of {fh_score}/100. Estimated annual invasive species damage "
        f"totals ${total_annual:,.0f}. {bias_note}"
    )


def _generate_findings(a: dict) -> list:
    """Generate 3-4 bullet key findings."""
    findings = []

    # Feral hog finding
    hog_proj = a.get("damage_projections", {}).get("feral_hog")
    if hog_proj:
        findings.append(
            f"<b>Feral hog damage estimated at "
            f"${hog_proj['estimated_annual_loss']:,.0f}/year</b> "
            f"(10-yr NPV: ${hog_proj['ten_year_npv']:,.0f}), based on "
            f"IPW-adjusted detection frequency of "
            f"{hog_proj['detection_frequency_pct']:.1f}% across "
            f"{a.get('acreage', 0):,.0f} acres."
        )

    # ESA finding
    reg = a.get("regulatory_risk", {})
    esa_sp = reg.get("esa_species_present", [])
    if esa_sp:
        cost_low = reg.get("total_estimated_compliance_cost_low", 0)
        cost_high = reg.get("total_estimated_compliance_cost_high", 0)
        findings.append(
            f"<b>{len(esa_sp)} ESA-listed species</b> "
            f"with potential habitat overlap identified. "
            f"Estimated compliance cost: "
            f"${cost_low:,.0f}\u2013${cost_high:,.0f}."
        )

    # Bias correction finding
    if a.get("bias_correction_applied"):
        hog_inv = next((s for s in a.get("species_inventory", [])
                        if s["species_key"] == "feral_hog"), None)
        if hog_inv:
            raw = hog_inv.get("raw_detection_frequency_pct", 0)
            adj = hog_inv.get("detection_frequency_pct", 0)
            delta = raw - adj
            findings.append(
                f"<b>Bias correction reduced feral hog detection "
                f"frequency by {delta:.1f} percentage points</b> "
                f"(raw {raw:.1f}% \u2192 adjusted {adj:.1f}%), "
                f"correcting for non-random camera placement near "
                f"feeders and water sources."
            )

    # Data confidence finding
    dc = a.get("data_confidence", {})
    grade = dc.get("overall_grade", "")
    gaps = dc.get("top_data_gaps", [])
    if gaps:
        total_cameras_needed = sum(g.get("cameras_needed", 0)
                                   for g in gaps)
        findings.append(
            f"<b>Monitoring gaps identified</b> requiring an "
            f"estimated {total_cameras_needed} additional cameras "
            f"to improve corridor coverage. Current data confidence: "
            f"grade {grade}."
        )

    return findings
