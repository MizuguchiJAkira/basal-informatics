"""Cover page — Parcel-Level Nature Exposure Report.

Editorial, not corporate. Black ground, cream Libre Baskerville type,
full-bleed camera trap image. The photograph is the artifact the
buyer will remember; everything else is metadata.
"""

from pathlib import Path

from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, Paragraph, Spacer, Table, TableStyle,
)

from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle

from report.styles import (
    PAGE_WIDTH,
    COVER_TEXT, COVER_MUTED, COVER_RULE,
    FONTS,
    STYLE_COVER_WORDMARK, STYLE_COVER_LABEL,
    STYLE_COVER_EYEBROW, STYLE_COVER_TITLE, STYLE_COVER_SUBTITLE,
    STYLE_COVER_META_KEY, STYLE_COVER_META_VAL,
    STYLE_COVER_CAPTION, STYLE_COVER_FOOTER,
)
from report.logo import BasalMark

# Large white report-type headline above the title block
_STYLE_REPORT_TYPE = ParagraphStyle(
    "CoverReportType",
    fontName=FONTS["serif_regular"], fontSize=16, leading=20,
    textColor=COVER_TEXT, alignment=TA_LEFT,
    spaceBefore=0, spaceAfter=0,
)

_COVER_IMAGE_PATH = Path(__file__).parent.parent / "assets" / "cover_hogs.jpg"

# Matches the cover_frame dimensions in generator.py (0.6" margins).
COVER_CONTENT_WIDTH = PAGE_WIDTH - 2 * (0.6 * inch)


def _format_property_name(assessment: dict) -> str:
    """Derive a display property name from the assessment.

    Prefers explicit property_name, then falls back to a derived
    "<County> County Ranch" string.
    """
    name = assessment.get("property_name")
    if name:
        return name
    county = assessment.get("county", "")
    if county:
        return f"{county} County Ranch"
    return "Parcel Assessment"


def _format_date_range(assessment: dict) -> str:
    """Return a human-readable date range or fall back to assessment date."""
    rng = assessment.get("monitoring_period") or {}
    start = rng.get("start")
    end = rng.get("end")
    if start and end:
        return f"{start} — {end}"
    date = assessment.get("assessment_date", "")
    return date or ""


def _hrule(width: float, color=COVER_RULE, thickness: float = 0.5) -> Table:
    """Horizontal rule used for editorial separators on the cover."""
    rule = Table([[""]], colWidths=[width], rowHeights=[0.01 * inch])
    rule.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), thickness, color),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    return rule


def render(assessment: dict) -> list:
    """Return list of ReportLab flowables for the cover page."""
    elements: list = []

    # ── Masthead (logo + wordmark) ────────────────────────────────────
    # Wordmark matches the website exactly: Fraunces regular, lowercase
    # "basal", italic forest-lit " / ", regular "informatics" — tight
    # tracking at -0.02em. No bold.
    _masthead_style = ParagraphStyle(
        "CoverMasthead",
        fontName=FONTS["serif_regular"], fontSize=20, leading=24,
        textColor=COVER_TEXT, alignment=TA_LEFT,
        # ReportLab charSpace is in points; -0.02em on 20pt ≈ -0.4pt
        charSpace=-0.4,
    )
    _masthead_tag_style = ParagraphStyle(
        "CoverMastheadTag",
        fontName=FONTS["mono_regular"], fontSize=7.5, leading=10,
        textColor=COVER_MUTED, alignment=TA_LEFT,
    )
    # Inline-italic slash tinted forest-lit, matching the website
    # ( <em> colored with --forest-lit ).
    from report.styles import COLORS as _C
    wordmark_html = (
        f'basal<font color="{_C["forest_lit"]}"><i> /</i></font> informatics'
    )
    # Logo sits inside a narrow cell to its left; wordmark + tagline
    # stack in the right cell. Keeps the whole masthead to one row.
    logo = BasalMark(size=0.42 * inch, color=COVER_TEXT)
    masthead_tbl = Table(
        [[
            logo,
            [
                Paragraph(wordmark_html, _masthead_style),
                Paragraph("ECOLOGICAL VERIFICATION", _masthead_tag_style),
            ],
        ]],
        colWidths=[0.55 * inch, COVER_CONTENT_WIDTH - 0.55 * inch],
    )
    masthead_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(masthead_tbl)
    elements.append(Spacer(1, 0.18 * inch))
    elements.append(_hrule(COVER_CONTENT_WIDTH))
    elements.append(Spacer(1, 0.22 * inch))

    # ── Title block ───────────────────────────────────────────────────
    property_name = _format_property_name(assessment)
    elements.append(Paragraph(property_name, STYLE_COVER_TITLE))

    county = assessment.get("county", "")
    state = assessment.get("state", "")
    acreage = assessment.get("acreage", 0)
    ecoregion = assessment.get("ecoregion", "Edwards Plateau")
    n_stations = assessment.get("n_camera_stations", 14)
    date_range = _format_date_range(assessment)

    sub_parts = []
    if county and state:
        sub_parts.append(f"{county} County, {state}")
    if acreage:
        sub_parts.append(f"{acreage:,.0f} acres")
    if date_range:
        sub_parts.append(date_range)
    subtitle = "  ·  ".join(sub_parts)
    if subtitle:
        elements.append(Paragraph(
            f"<i>{subtitle}</i>", STYLE_COVER_SUBTITLE))

    # Secondary metadata row — stations, ecoregion
    meta_parts = []
    if n_stations:
        meta_parts.append(f"{n_stations} camera stations")
    if ecoregion:
        meta_parts.append(f"{ecoregion} ecoregion")
    if meta_parts:
        elements.append(Paragraph(
            "  ·  ".join(meta_parts), STYLE_COVER_EYEBROW))

    elements.append(Spacer(1, 0.22 * inch))

    # ── Hero image ────────────────────────────────────────────────────
    if _COVER_IMAGE_PATH.exists():
        # Crop to a tighter 16:9 aspect so the footer block fits above
        # the fold without pushing to page 2.
        img_w = COVER_CONTENT_WIDTH
        img_h = img_w * (9 / 16)
        hero = Image(str(_COVER_IMAGE_PATH),
                     width=img_w, height=img_h)
        elements.append(hero)
        elements.append(Spacer(1, 0.08 * inch))
        elements.append(Paragraph(
            "Station CW-04 · 18 Jun 2023 · 14:11 — sounder of feral "
            "hogs (Sus scrofa), infrared capture",
            STYLE_COVER_CAPTION))
    else:
        # Graceful fallback — a blank rule where the image would sit
        elements.append(_hrule(
            COVER_CONTENT_WIDTH, color=COVER_MUTED, thickness=1))
        elements.append(Spacer(1, 3.0 * inch))
        elements.append(_hrule(
            COVER_CONTENT_WIDTH, color=COVER_MUTED, thickness=1))

    elements.append(Spacer(1, 0.12 * inch))

    # ── Prepared for / Prepared by ────────────────────────────────────
    prepared_for = assessment.get("prepared_for") or {}
    pf_company = prepared_for.get("company", "AXA XL Sustainability")
    pf_contact = prepared_for.get("contact", "")

    prepared_by_name = assessment.get("prepared_by", "Basal Informatics")

    pf_cell = [
        Paragraph("PREPARED FOR", STYLE_COVER_META_KEY),
        Spacer(1, 0.04 * inch),
        Paragraph(pf_company, STYLE_COVER_META_VAL),
    ]
    if pf_contact:
        pf_cell.append(Paragraph(
            f"<i>{pf_contact}</i>", STYLE_COVER_CAPTION))

    pb_cell = [
        Paragraph("PREPARED BY", STYLE_COVER_META_KEY),
        Spacer(1, 0.04 * inch),
        Paragraph(prepared_by_name, STYLE_COVER_META_VAL),
        Paragraph(
            "<i>Ground-truth ecological verification</i>",
            STYLE_COVER_CAPTION),
    ]

    # Rule, then report-type headline, then prepared block
    elements.append(_hrule(COVER_CONTENT_WIDTH))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "Parcel-Level Nature Exposure Report",
        _STYLE_REPORT_TYPE))
    elements.append(Spacer(1, 0.1 * inch))

    prep_table = Table(
        [[pf_cell, pb_cell]],
        colWidths=[COVER_CONTENT_WIDTH * 0.5,
                   COVER_CONTENT_WIDTH * 0.5],
    )
    prep_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(prep_table)

    # ── Footer ────────────────────────────────────────────────────────
    elements.append(Spacer(1, 0.2 * inch))
    elements.append(_hrule(COVER_CONTENT_WIDTH))
    elements.append(Spacer(1, 0.08 * inch))

    footer = Table(
        [[
            Paragraph("<i>Processed by Basal Informatics</i>", STYLE_COVER_FOOTER),
            Paragraph("basalinformatics.com", STYLE_COVER_FOOTER),
        ]],
        colWidths=[COVER_CONTENT_WIDTH * 0.5,
                   COVER_CONTENT_WIDTH * 0.5],
    )
    footer.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    elements.append(footer)

    return elements
