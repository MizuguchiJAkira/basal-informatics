"""Species inventory table — sorted by risk relevance.

McKinsey idiom: each row opens with a filled category chip ("I" for
invasive, "E" for ESA-listed, "N" for native). Chip color signals
severity — deep navy for invasive-high, medium blue for moderate,
pale blue for ESA/native. The rest of the row is restrained serif
text, so the chip is the only chromatic mark.
"""

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from report.styles import (
    TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE,
    BRAND_NAVY, BRAND_BLUE, BRAND_BLUE_LIGHT, SECTION_BAR_TEXT,
    FONTS, COLORS, CONTENT_WIDTH,
    STYLE_FOOTNOTE, base_table_style, section_bar,
)


def render(assessment: dict) -> list:
    """Return flowables for the species inventory table page."""
    elements = []

    elements.append(section_bar("Species Inventory", CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    inventory = assessment.get("species_inventory", [])
    if not inventory:
        elements.append(Paragraph("No species detected.", STYLE_FOOTNOTE))
        return elements

    # Build table — leading chip column plus the usual fields.
    header = ["", "Species", "Events", "Det. Freq.", "Conf.", "Risk Flag"]
    rows = [header]

    chip_meta = []  # list of (letter, fill_color) per body row
    for sp in inventory:
        flag = sp.get("risk_flag") or ""
        esa = "ESA" in flag
        invasive = sp.get("invasive")
        if "HIGH" in flag:
            letter, fill = "I", BRAND_NAVY
        elif "MODERATE" in flag and invasive:
            letter, fill = "I", BRAND_BLUE
        elif esa:
            letter, fill = "E", BRAND_BLUE_LIGHT
        else:
            letter, fill = "N", BRAND_BLUE_LIGHT
        chip_meta.append((letter, fill))
        rows.append([
            letter,
            sp["common_name"],
            str(sp["independent_events"]),
            f"{sp['detection_frequency_pct']:.1f}%",
            sp["confidence_grade"],
            flag if flag else "\u2014",
        ])

    col_widths = [0.35 * inch, 2.0 * inch, 0.8 * inch,
                  1.0 * inch, 0.65 * inch, 2.2 * inch]

    t = Table(rows, colWidths=col_widths, repeatRows=1)

    # Base styling
    style_cmds = base_table_style(len(rows))

    # Right-align numeric columns; chip column stays centered
    style_cmds.append(("ALIGN", (0, 0), (0, -1), "CENTER"))
    style_cmds.append(("ALIGN", (2, 0), (2, -1), "RIGHT"))
    style_cmds.append(("ALIGN", (3, 0), (3, -1), "RIGHT"))
    style_cmds.append(("ALIGN", (4, 0), (4, -1), "CENTER"))

    # Paint the chip cells — filled square with white bold letter
    for i, (letter, fill) in enumerate(chip_meta, start=1):
        # Cell fill
        style_cmds.append(("BACKGROUND", (0, i), (0, i), fill))
        # Letter styling — white bold serif, tight padding
        style_cmds.append(
            ("TEXTCOLOR", (0, i), (0, i), SECTION_BAR_TEXT))
        style_cmds.append(
            ("FONTNAME", (0, i), (0, i), FONTS["serif_bold"]))
        style_cmds.append(
            ("FONTSIZE", (0, i), (0, i), 9))
        # Bold the species name on invasive-high rows for emphasis
        sp = inventory[i - 1]
        flag = sp.get("risk_flag") or ""
        if "HIGH" in flag:
            style_cmds.append(
                ("FONTNAME", (1, i), (1, i), FONTS["serif_bold"]))
            style_cmds.append(
                ("FONTNAME", (5, i), (5, i), FONTS["serif_bold"]))
            style_cmds.append(
                ("TEXTCOLOR", (5, i), (5, i), BRAND_NAVY))
        elif "MODERATE" in flag:
            style_cmds.append(
                ("FONTNAME", (5, i), (5, i), FONTS["serif_italic"]))
            style_cmds.append(
                ("TEXTCOLOR", (5, i), (5, i), BRAND_BLUE))

    # Chip cell padding — tighter than the rest so the letter centers
    style_cmds.append(("LEFTPADDING", (0, 1), (0, -1), 0))
    style_cmds.append(("RIGHTPADDING", (0, 1), (0, -1), 0))
    style_cmds.append(("TOPPADDING", (0, 1), (0, -1), 3))
    style_cmds.append(("BOTTOMPADDING", (0, 1), (0, -1), 3))
    # Hide the header chip column cell (no fill, no text)
    style_cmds.append(("LINEBELOW", (0, 0), (0, 0), 0.4, TEXT_PRIMARY))

    t.setStyle(TableStyle(style_cmds))
    elements.append(t)

    # Footnotes
    elements.append(Spacer(1, 0.15 * inch))

    if assessment.get("bias_correction_applied"):
        elements.append(Paragraph(
            "Detection frequencies are IPW-adjusted for non-random camera "
            "placement (Kolowski &amp; Forrester 2017). Raw frequencies "
            "before correction are available in the full data export.",
            STYLE_FOOTNOTE))

    elements.append(Paragraph(
        "Events = independent detections (30-min threshold). "
        "Confidence grades reflect corridor coverage, temporal "
        "completeness, and detection frequency (A = highest).",
        STYLE_FOOTNOTE))

    return elements
