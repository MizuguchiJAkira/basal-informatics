"""Enterprise PDF report generator.

Orchestrates section rendering into a complete parcel risk
assessment PDF for insurer/lender delivery.

Input: risk assessment JSON from the synthesis engine.
Output: multi-page PDF using ReportLab, charts via Matplotlib.

Design language: McKinsey meets Bloomberg.
"""

import os
import tempfile
from pathlib import Path
from typing import List, Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, NextPageTemplate,
    PageBreak, PageTemplate, Spacer,
)

from report.styles import (
    BRAND_NAVY, TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE,
    FONTS, COLORS,
    PAGE_WIDTH, PAGE_HEIGHT,
    MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM,
    CONTENT_WIDTH,
    COVER_BG, COVER_TEXT, PAGE_BG,
)

# Section modules
from report.sections import (
    cover,
    executive_summary,
    parcel_map,
    species_table,
    damage_projection,
    temporal,
    confidence,
    methodology,
)


def generate_report(
    assessment: dict,
    output_path: str = None,
    detections=None,
    cameras_json=None,
    parcel_geojson=None,
) -> str:
    """Generate the enterprise Nature Exposure Report PDF.

    Args:
        assessment: Complete risk assessment dict from synthesis engine.
        output_path: Where to write the PDF. Defaults to reports/ dir.
        detections: Detection objects for temporal charts (optional).
        cameras_json: Camera location data for map (optional).
        parcel_geojson: Parcel boundary GeoJSON for map (optional).

    Returns:
        Path to the generated PDF file.
    """
    if output_path is None:
        reports_dir = Path(__file__).parent.parent / "reports"
        reports_dir.mkdir(exist_ok=True)
        parcel_id = assessment.get("parcel_id", "unknown")
        output_path = str(reports_dir / f"nature_exposure_{parcel_id}.pdf")

    # Build the document
    doc = BaseDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=MARGIN_LEFT,
        rightMargin=MARGIN_RIGHT,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=f"Nature Exposure Report — {assessment.get('parcel_id', '')}",
        author="Basal Informatics",
    )

    # Page templates — the cover uses tighter margins and a black
    # background so the hero image reads as full-bleed.
    cover_margin = 0.6 * inch
    cover_frame = Frame(
        cover_margin, cover_margin,
        PAGE_WIDTH - 2 * cover_margin,
        PAGE_HEIGHT - 2 * cover_margin,
        id="cover_frame",
        leftPadding=0, rightPadding=0,
        topPadding=0, bottomPadding=0,
    )
    content_frame = Frame(
        MARGIN_LEFT, MARGIN_BOTTOM + 0.3 * inch,
        CONTENT_WIDTH, PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM - 0.3 * inch,
        id="content_frame",
    )

    def _cover_page(canvas, doc):
        """Cover page — paint entire page black, no header/footer."""
        canvas.saveState()
        canvas.setFillColor(COVER_BG)
        canvas.setStrokeColor(COVER_BG)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
        canvas.restoreState()

    def _content_page(canvas, doc):
        """Content pages — institutional running header/footer.

        Typography matches Goldman Sachs / McKinsey research reports:
          - Fraunces italic 8.5pt for running masthead and confidential
            stamp (sentence case, not all-caps mono)
          - Inter regular 9pt for the page number
          - Thin ink rules above the header and below the footer
        No mono in the page chrome — mono is reserved for tabular data
        and data captions inside the content frame.
        """
        canvas.saveState()

        # Paint page background.
        canvas.setFillColor(PAGE_BG)
        canvas.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)

        # Header hairline
        y_top = PAGE_HEIGHT - 0.55 * inch
        canvas.setStrokeColor(BRAND_NAVY)  # = INK in the new palette
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, y_top,
                    PAGE_WIDTH - MARGIN_RIGHT, y_top)

        # Header: "Basal Informatics" left in Fraunces italic; parcel
        # reference right in Fraunces italic. Sentence case, no bullets.
        parcel_id = assessment.get("parcel_id", "")
        canvas.setFont(FONTS["serif_italic"], 8.5)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.drawString(MARGIN_LEFT, y_top + 5,
                          "Basal Informatics")
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, y_top + 5,
                               f"Nature Exposure Report — {parcel_id}")

        # Footer hairline
        y_bot = 0.55 * inch
        canvas.setStrokeColor(BRAND_NAVY)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_LEFT, y_bot,
                    PAGE_WIDTH - MARGIN_RIGHT, y_bot)

        # Footer: italic "Confidential" left, plain page number right.
        canvas.setFont(FONTS["serif_italic"], 8)
        canvas.setFillColor(TEXT_SECONDARY)
        canvas.drawString(MARGIN_LEFT, y_bot - 12,
                          "Confidential — for authorized recipients")
        canvas.setFont(FONTS["sans_regular"], 9)
        canvas.setFillColor(BRAND_NAVY)
        canvas.drawRightString(PAGE_WIDTH - MARGIN_RIGHT, y_bot - 12,
                               f"{doc.page}")

        canvas.restoreState()

    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame],
                     onPage=_cover_page),
        PageTemplate(id="content", frames=[content_frame],
                     onPage=_content_page),
    ])

    # ── Build story ──
    #
    # Sections flow. The section_bar (hairline rule + display title)
    # is the visual divider; an explicit PageBreak between every
    # section was forcing half-empty pages where the next section's
    # header + short content would have fit below its predecessor.
    # Each render() ends with a small spacer before the next section
    # title takes over.
    #
    # The cover keeps its own PageBreak (it's a bespoke template).
    # Back matter keeps its break so the sign-off page is clean.
    story = []

    # Cover page
    story.extend(cover.render(assessment))
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # Executive summary
    story.extend(executive_summary.render(assessment))
    story.append(Spacer(1, 0.35 * inch))

    # Parcel map
    story.extend(parcel_map.render(
        assessment, detections=detections,
        cameras_json=cameras_json,
        parcel_geojson=parcel_geojson))
    story.append(Spacer(1, 0.35 * inch))

    # Species inventory table
    story.extend(species_table.render(assessment))
    story.append(Spacer(1, 0.35 * inch))

    # Damage projections
    story.extend(damage_projection.render(assessment))
    story.append(Spacer(1, 0.35 * inch))

    # Temporal analysis
    story.extend(temporal.render(assessment, detections=detections))
    story.append(Spacer(1, 0.35 * inch))

    # Data confidence
    story.extend(confidence.render(assessment))
    story.append(Spacer(1, 0.35 * inch))

    # Methodology
    story.extend(methodology.render(assessment))
    story.append(PageBreak())

    # Back matter — references + sign-off on a single final page.
    # Break before it so references don't trail onto the methodology
    # page and leave the sign-off stranded on a half-empty final
    # page (the previous layout's failure mode).
    story.extend(_back_cover(assessment))

    # Build PDF
    doc.build(story)

    return output_path


def _back_cover(assessment: dict) -> list:
    """Back page — references above, compact sign-off block below.

    The references list used to live at the end of the methodology
    section and was spilling onto its own half-empty page. Here it
    sits above the sign-off block — still the last content in the
    document, but no longer consuming a dedicated page.
    """
    from reportlab.platypus import Paragraph
    from report.styles import (
        STYLE_H2, STYLE_BODY, STYLE_BODY_SMALL, STYLE_SUBTITLE,
        CONTENT_WIDTH,
    )
    from report.sections.methodology import render_references

    elements = []

    # References (2-col) — take the natural top of the back page
    elements.extend(render_references(width=CONTENT_WIDTH))

    elements.append(Spacer(1, 0.35 * inch))

    # Sign-off block — compact, no 3" spacer
    elements.append(Paragraph("Basal Informatics", STYLE_H2))
    elements.append(Paragraph(
        "Ground-truth ecological data for nature-risk assessment. "
        "We deploy scalable camera-trap networks across private land, "
        "process imagery through calibrated classifiers, and deliver "
        "bias-corrected species inventories and density estimates to "
        "agricultural lenders and reinsurers for TNFD and EU CSRD "
        "disclosure.",
        STYLE_BODY))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "basal.eco  ·  info@basal.eco", STYLE_BODY_SMALL))
    elements.append(Spacer(1, 0.18 * inch))
    ver = assessment.get("methodology_version", "1.0.0")
    elements.append(Paragraph(
        f"Methodology version {ver}  ·  "
        f"Assessment date: {assessment.get('assessment_date', '')}",
        STYLE_BODY_SMALL))
    elements.append(Paragraph(
        "This report contains proprietary analysis. Distribution "
        "is restricted to the named recipient and their authorized "
        "agents.",
        STYLE_BODY_SMALL))

    return elements
