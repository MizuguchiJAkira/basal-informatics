"""Valuation Risk — Stage 7 PDF section.

Mirrors the lender-facing HTML block. Renders only when the
``assessment["valuation_risk"]`` slot is populated; legacy parcels
pass nothing through and the section is skipped.

Restrained tone — see spec constraints:

  * "Indicative risk band" never a probability or percentage.
  * Texas-only language. "1-d-1" / "1-d-1(w)" verbatim.
  * Describe risk; do not recommend filing actions.
"""

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, Spacer, Table, TableStyle,
)

from report.styles import (
    BRAND_NAVY, TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE,
    CONTENT_WIDTH,
    STYLE_BODY, STYLE_BODY_SMALL, STYLE_FOOTNOTE,
    section_bar,
)


# Band → color hint. We map to existing brand palette so the new section
# doesn't introduce a new accent — it inherits the report's restrained
# forest/ink/rose discipline.
_BAND_COLORS = {
    "low":      colors.HexColor("#2b4432"),
    "moderate": colors.HexColor("#7a5a20"),
    "elevated": colors.HexColor("#a8651b"),
    "high":     colors.HexColor("#7d2818"),
}

_CLASS_LABELS = {
    "ag_open_space":       "1-d-1 (open-space agricultural)",
    "wildlife_open_space": "1-d-1(w) (wildlife)",
    "timber":              "Timber (§23.71)",
    "market":              "Market value",
    "unknown":             "Unknown",
}


def render(assessment: dict) -> list:
    vr = assessment.get("valuation_risk")
    if not vr:
        return []  # legacy parcel — section absent

    elements: list = []
    elements.append(section_bar(
        "Texas Ag Valuation Risk", CONTENT_WIDTH,
    ))
    elements.append(Spacer(1, 0.12 * inch))

    cv = vr["current_valuation"]
    cls_label = _CLASS_LABELS.get(
        cv["classification"], cv["classification"]
    )
    elements.append(Paragraph(
        f"<b>Current classification:</b> {cls_label}. "
        f"As-of {cv['as_of_date']}, source {cv['data_source']}. "
        f"Indicative risk band on a 24-month horizon: "
        f"<b><font color='{_BAND_COLORS.get(vr['risk_score']['band'], '#1a1816').hexval()}'>"
        f"{vr['risk_score']['band'].upper()}</font></b>.",
        STYLE_BODY,
    ))
    elements.append(Spacer(1, 0.10 * inch))

    # Drivers table — every factor in the rubric, triggered or not, so
    # the reader sees what was considered.
    drivers = vr["risk_score"]["drivers"]
    rows = [["Driver", "W.", "", "Evidence"]]
    for d in drivers:
        rows.append([
            d["factor"].replace("_", " ").title(),
            f"{d['weight']:.2f}",
            "✓" if d["triggered"] else "—",
            Paragraph(d["evidence"], STYLE_BODY_SMALL),
        ])
    tbl = Table(
        rows,
        colWidths=[1.7 * inch, 0.4 * inch, 0.35 * inch,
                   CONTENT_WIDTH - 2.45 * inch],
    )
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_SECONDARY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, GRIDLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 0.12 * inch))

    # Exposure block.
    expo = vr["exposure_if_lost"]
    if expo["collateral_value_delta_dollars"] is not None:
        delta = expo["collateral_value_delta_dollars"]
        elements.append(Paragraph(
            f"<b>Collateral value delta if special-use appraisal "
            f"is lost:</b> ${abs(delta):,.0f} reduction "
            f"({expo['method']}, {expo['confidence']} confidence). "
            f"Asset-side impact only; cash-side §23.55 liability "
            f"reported below.",
            STYLE_BODY,
        ))
        rb = expo.get("rollback_tax_estimated_dollars")
        if rb is not None and rb > 0:
            yrs = expo.get("rollback_tax_years")
            rate = expo.get("rollback_tax_assumed_rate")
            elements.append(Paragraph(
                f"<b>Estimated §23.55 rollback liability:</b> "
                f"${rb:,.0f} ({yrs} years at 5% simple interest, "
                f"{rate * 100:.1f}% effective property tax rate "
                f"assumed). Cash impact at conversion.",
                STYLE_BODY,
            ))
    else:
        elements.append(Paragraph(
            "<b>Collateral value delta if special-use appraisal "
            "is lost:</b> not estimable from the available CAD "
            "snapshot.",
            STYLE_BODY,
        ))
    elements.append(Spacer(1, 0.10 * inch))

    # Remediation block — describe pathway, do NOT recommend filing.
    rem = vr["remediation"]
    viable = rem["wildlife_conversion_viable"]
    if viable:
        elements.append(Paragraph(
            f"<b>1-d-1(w) conversion pathway:</b> qualifying-practice "
            f"evidence is present for "
            f"{len(rem['qualifying_practices_evidence'])} of seven "
            f"TPWD practices in the {rem['ecoregion'].replace('_', ' ')} "
            f"ecoregion (3 required). Specific intensity standards "
            f"and filing windows are not addressed by this report.",
            STYLE_BODY,
        ))
    else:
        elements.append(Paragraph(
            f"<b>1-d-1(w) conversion pathway:</b> qualifying-practice "
            f"evidence is present for only "
            f"{len(rem['qualifying_practices_evidence'])} of seven "
            f"TPWD practices (3 required). Pathway not viable on "
            f"current parcel use.",
            STYLE_BODY,
        ))
    elements.append(Spacer(1, 0.06 * inch))

    # Per-practice mini-table.
    p_rows = [["Practice", "Status", "Evidence"]]
    for p in rem["practices"]:
        p_rows.append([
            p["label"],
            p["status"].replace("_", " "),
            Paragraph(p["evidence"], STYLE_BODY_SMALL),
        ])
    p_tbl = Table(
        p_rows,
        colWidths=[1.7 * inch, 1.1 * inch,
                   CONTENT_WIDTH - 2.8 * inch],
    )
    p_tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_SECONDARY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, GRIDLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
    ]))
    elements.append(p_tbl)
    elements.append(Spacer(1, 0.12 * inch))

    # Footnote — disclaim probability framing and underline scope.
    elements.append(Paragraph(
        "Indicative risk band — not a probability or forecast. Texas "
        "1-d-1 and 1-d-1(w) only; no homestead, over-65, or timber "
        "valuations are addressed. This section describes risk and "
        "remediation pathway; it does not recommend filing actions.",
        STYLE_FOOTNOTE,
    ))

    if vr["human_feedback"]["underwriter_override"]:
        elements.append(Spacer(1, 0.06 * inch))
        elements.append(Paragraph(
            f"<i>Underwriter override on file: band recorded as "
            f"<b>{vr['human_feedback']['underwriter_override'].upper()}</b>. "
            f"{vr['human_feedback'].get('underwriter_notes') or ''}</i>",
            STYLE_FOOTNOTE,
        ))

    return elements
