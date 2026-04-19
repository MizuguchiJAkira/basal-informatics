"""Data confidence section — transparency on grades and gaps.

Per-species confidence grades table. Camera density. Regional model
accuracy from feedback data. Top 3 data gaps with projected confidence
improvement. Tells the insurer where uncertainty is highest.
"""

from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from report.styles import (
    TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE, BRAND_NAVY,
    FONTS, COLORS, CONTENT_WIDTH,
    STYLE_H2, STYLE_BODY, STYLE_BODY_SMALL,
    STYLE_FOOTNOTE, base_table_style, grade_color, section_bar,
)


def render(assessment: dict) -> list:
    """Return flowables for the data confidence page."""
    elements = []

    elements.append(section_bar("Data Confidence", CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    dc = assessment.get("data_confidence", {})

    # ── Overview metrics ──
    overview_rows = [
        ["Overall confidence grade", dc.get("overall_grade", "N/A")],
        ["Monitoring duration", f"{dc.get('monitoring_months', 0)} months"],
        ["Camera density",
         f"{dc.get('camera_density_per_km2', 0):.2f} cameras/km\u00b2"],
        ["Bias correction",
         "Applied" if assessment.get("bias_correction_applied")
         else "Not applied"],
    ]

    ot = Table(overview_rows, colWidths=[3.0 * inch, 4.0 * inch])
    ot.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), FONTS["serif_italic"]),
        ("FONTNAME", (1, 0), (1, -1), FONTS["serif_bold"]),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), TEXT_SECONDARY),
        ("TEXTCOLOR", (1, 0), (1, -1), BRAND_NAVY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEABOVE", (0, 0), (-1, 0), 1.0, BRAND_NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, BRAND_NAVY),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, GRIDLINE),
    ]))
    elements.append(ot)
    elements.append(Spacer(1, 0.12 * inch))

    # ── Per-species confidence table ──
    elements.append(Paragraph("Species Confidence Grades", STYLE_H2))

    inventory = assessment.get("species_inventory", [])
    # Show top 8 species to keep table on one page
    display_inventory = inventory[:8]
    remaining = len(inventory) - len(display_inventory)
    if display_inventory:
        header = ["Species", "Det. Freq.", "Grade", "Cameras",
                  "Events"]
        rows = [header]
        for sp in display_inventory:
            rows.append([
                sp["common_name"],
                f"{sp['detection_frequency_pct']:.1f}%",
                sp["confidence_grade"],
                f"{sp['cameras_detected']}/{sp['cameras_total']}",
                str(sp["independent_events"]),
            ])

        col_widths = [2.5 * inch, 1.0 * inch, 0.7 * inch,
                      1.2 * inch, 1.0 * inch]
        st = Table(rows, colWidths=col_widths, repeatRows=1)

        style_cmds = base_table_style(len(rows))
        style_cmds.append(("ALIGN", (1, 0), (1, -1), "RIGHT"))
        style_cmds.append(("ALIGN", (2, 0), (2, -1), "CENTER"))
        style_cmds.append(("ALIGN", (3, 0), (3, -1), "CENTER"))
        style_cmds.append(("ALIGN", (4, 0), (4, -1), "RIGHT"))

        # Color-code grade column
        for i, sp in enumerate(inventory, start=1):
            gc = grade_color(sp["confidence_grade"])
            style_cmds.append(
                ("TEXTCOLOR", (2, i), (2, i),
                 colors.HexColor(gc)))

        st.setStyle(TableStyle(style_cmds))
        elements.append(st)

        if remaining > 0:
            elements.append(Paragraph(
                f"+ {remaining} additional species (see Species "
                f"Inventory table for full list)",
                STYLE_FOOTNOTE))

    # ── Regional model accuracy ──
    elements.append(Spacer(1, 0.12 * inch))
    elements.append(Paragraph("Regional Classification Accuracy", STYLE_H2))

    rma = dc.get("regional_model_accuracy", {})
    accuracies = rma.get("species_accuracies", {})
    val_status = rma.get("ecological_validation_status", "unvalidated")

    elements.append(Paragraph(
        f"Source: <b>hunter-verified corrections</b> | "
        f"Validation status: <b>{val_status}</b>",
        STYLE_BODY_SMALL))

    if accuracies:
        acc_header = ["Species", "Accuracy"]
        acc_rows = [acc_header]
        for sp_key, acc in sorted(accuracies.items(),
                                   key=lambda x: -x[1]):
            name = sp_key.replace("_", " ").title()
            acc_rows.append([name, f"{acc:.1f}%"])

        at = Table(acc_rows,
                   colWidths=[CONTENT_WIDTH - 1.5 * inch, 1.5 * inch])
        at.setStyle(TableStyle(base_table_style(len(acc_rows)) + [
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]))
        elements.append(at)

    elements.append(Paragraph(
        rma.get("calibration_note", ""),
        STYLE_FOOTNOTE))

    # ── Top data gaps ──
    # KeepTogether so the heading + table don't orphan onto a new page
    gaps = dc.get("top_data_gaps", [])
    if gaps:
        gap_block = []
        gap_block.append(Spacer(1, 0.12 * inch))
        gap_block.append(Paragraph("Top Monitoring Gaps", STYLE_H2))
        gap_block.append(Paragraph(
            "Gaps in corridor coverage where additional cameras would "
            "most improve data confidence.",
            STYLE_BODY_SMALL))

        gap_header = ["Corridor", "Habitat Unit", "Gap (m)",
                      "Species Affected", "Cameras Needed"]
        gap_rows = [gap_header]
        for g in gaps:
            gap_rows.append([
                g["corridor_type"].replace("_", " ").title(),
                g["habitat_unit_id"],
                f"{g['gap_length_m']:.0f}",
                g["species_most_affected"].replace("_", " ").title(),
                str(g["cameras_needed"]),
            ])

        gt = Table(gap_rows, colWidths=[
            1.3 * inch, 2.0 * inch, 0.8 * inch,
            1.7 * inch, 1.2 * inch])
        gt.setStyle(TableStyle(base_table_style(len(gap_rows)) + [
            ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ("ALIGN", (4, 0), (4, -1), "CENTER"),
        ]))
        gap_block.append(gt)
        elements.append(KeepTogether(gap_block))

    return elements
