"""Damage projection — the financial headline page.

Feral Hog Exposure Score gauge. Estimated Annual Loss as large dollar
figure. 10-year NPV. Confidence interval bar chart. DCF assumptions
table. This is the page the underwriter uses.
"""

import math
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image, Paragraph, Spacer, Table, TableStyle,
)

from report.styles import (
    BRAND_NAVY, BRAND_BLUE, BRAND_TEAL, TEXT_PRIMARY, TEXT_SECONDARY, GRIDLINE,
    FONTS, COLORS, CONTENT_WIDTH,
    STYLE_H2, STYLE_H3, STYLE_BODY, STYLE_BODY_SMALL,
    STYLE_METRIC_LARGE, STYLE_METRIC_LABEL, STYLE_FOOTNOTE,
    STYLE_CAPTION, risk_color, section_bar, setup_chart_style,
)

setup_chart_style()


def render(assessment: dict) -> list:
    """Return flowables for the damage projection page."""
    elements = []

    elements.append(section_bar("Invasive Species Damage Projection",
                                 CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    projections = assessment.get("damage_projections", {})
    fh = assessment.get("feral_hog_exposure_score")

    if not projections:
        elements.append(Paragraph(
            "No invasive species damage models applicable.",
            STYLE_BODY))
        return elements

    # ── Headline figures — three-up typographic panel ──
    # GS / McKinsey idiom: a row of three bold-numeral metrics under
    # small italic labels, separated by thin rules. No gauges, no
    # arcs, no decorative graphics. Numbers do the work.
    hog_proj = projections.get("feral_hog")
    if hog_proj:
        score_val = fh.get("score", "N/A") if fh else "N/A"
        num_style = ParagraphStyle(
            "HeadlineNum",
            fontName=FONTS["serif_bold"], fontSize=26, leading=30,
            textColor=BRAND_NAVY, alignment=1,
        )
        lbl_style = ParagraphStyle(
            "HeadlineLbl",
            fontName=FONTS["serif_italic"], fontSize=8.5, leading=11,
            textColor=TEXT_SECONDARY, alignment=1,
        )

        def _cell(number: str, label: str):
            return [
                Paragraph(number, num_style),
                Spacer(1, 0.03 * inch),
                Paragraph(label, lbl_style),
            ]

        col_w = CONTENT_WIDTH / 3.0
        top_row = Table(
            [[
                _cell(f"{score_val}", "Feral Hog Exposure Score"),
                _cell(f"${hog_proj['estimated_annual_loss']:,.0f}",
                      "Estimated Annual Loss"),
                _cell(f"${hog_proj['ten_year_npv']:,.0f}",
                      "10-Year NPV (5% discount)"),
            ]],
            colWidths=[col_w, col_w, col_w],
        )
        top_row.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            # Thin vertical rules between the three cells
            ("LINEAFTER",  (0, 0), (0, 0), 0.4, GRIDLINE),
            ("LINEAFTER",  (1, 0), (1, 0), 0.4, GRIDLINE),
            # Top and bottom hairlines
            ("LINEABOVE",  (0, 0), (-1, 0), 0.5, BRAND_NAVY),
            ("LINEBELOW",  (0, -1), (-1, -1), 0.5, BRAND_NAVY),
        ]))
        elements.append(top_row)
        elements.append(Spacer(1, 0.06 * inch))
        elements.append(Paragraph(
            f"Confidence interval "
            f"(\u00b1{hog_proj['confidence_interval_pct']:.0f}%): "
            f"${hog_proj['confidence_interval_low']:,.0f} \u2013 "
            f"${hog_proj['confidence_interval_high']:,.0f}.",
            STYLE_BODY_SMALL))
        elements.append(Spacer(1, 0.15 * inch))

    # ── Confidence interval chart ──
    ci_path = _make_ci_chart(projections)
    if ci_path:
        elements.append(Paragraph("Damage Estimates with Confidence Intervals",
                                  STYLE_H2))
        elements.append(Image(ci_path,
                              width=CONTENT_WIDTH,
                              height=2.0 * inch))
        elements.append(Spacer(1, 0.1 * inch))

    # ── DCF assumptions table ──
    elements.append(Paragraph("Model Assumptions", STYLE_H2))

    for sp_key, proj in projections.items():
        assumption_rows = [
            ["Parameter", "Value"],
            ["Base rate source", proj.get("methodology", "").split(
                " calibrated")[0]],
            ["Base cost", f"${proj['base_cost_per_acre']:.2f}/acre/year"],
            ["Ecoregion calibration",
             f"{proj['ecoregion_calibration_factor']:.2f}\u00d7"],
            ["Detection frequency (IPW-adjusted)",
             f"{proj['detection_frequency_pct']:.1f}%"],
            ["Logistic frequency scale",
             f"{proj['frequency_scale']:.4f}"],
            ["Parcel acreage", f"{proj['acreage']:,.0f} acres"],
            ["Discount rate (NPV)", "5.0%"],
            ["NPV horizon", "10 years"],
            ["Confidence grade", proj['confidence_grade']],
            ["CI width", f"\u00b1{proj['confidence_interval_pct']:.0f}%"],
        ]

        elements.append(Paragraph(
            f"<b>{proj['common_name']}</b>", STYLE_H3))

        at = Table(assumption_rows,
                   colWidths=[3.0 * inch, 4.0 * inch])
        from report.styles import base_table_style
        style_cmds = base_table_style(len(assumption_rows))
        style_cmds.append(("ALIGN", (1, 0), (1, -1), "LEFT"))
        at.setStyle(TableStyle(style_cmds))
        elements.append(at)

    # ── Broadley caveat ──
    if hog_proj:
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(Paragraph(
            f"<i>{hog_proj.get('broadley_caveat', '')}</i>",
            STYLE_FOOTNOTE))

    return elements


def _make_exposure_gauge(fh: dict) -> str:
    """Semicircle gauge for Feral Hog Exposure Score (0-100).

    McKinsey idiom: heavy neutral-gray ring with a teal arc showing
    the captured score. The numeral sits inside in navy serif bold,
    "/ 100" below in italic grey.
    """
    score = fh.get("score", 0)

    fig, ax = plt.subplots(figsize=(3.0, 2.0))

    # Unfilled arc — neutral gray ring
    bg_arc = mpatches.Arc((0.5, 0.0), 0.9, 0.9,
                          angle=0, theta1=0, theta2=180,
                          linewidth=16, color=COLORS["chart_neutral"])
    ax.add_patch(bg_arc)

    # Filled arc — teal accent
    score_frac = score / 100.0
    score_angle = score_frac * 180
    if score > 0:
        score_arc = mpatches.Arc((0.5, 0.0), 0.9, 0.9,
                                 angle=0, theta1=180 - score_angle,
                                 theta2=180,
                                 linewidth=16,
                                 color=COLORS["brand_teal"])
        ax.add_patch(score_arc)

    # Score text in center — navy serif bold
    ax.text(0.5, 0.15, str(score),
            ha="center", va="center",
            fontsize=32, fontweight="bold",
            color=COLORS["brand_navy"])
    ax.text(0.5, -0.08, "/ 100",
            ha="center", va="center",
            fontsize=10, fontstyle="italic",
            color=COLORS["text_secondary"])

    ax.set_xlim(-0.1, 1.1)
    ax.set_ylim(-0.2, 0.65)
    ax.set_aspect("equal")
    ax.axis("off")

    fig.tight_layout()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=180, bbox_inches="tight",
                facecolor=COLORS["page_bg"], edgecolor="none")
    plt.close(fig)
    return tmp.name


def _make_ci_chart(projections: dict) -> str:
    """Horizontal bar chart with confidence intervals.

    Hog (the primary subject) gets the navy fill; secondary species
    get the medium-blue fill. CI brackets stay in navy for all.
    """
    if not projections:
        return None

    species = list(projections.keys())
    central = [projections[s]["estimated_annual_loss"] for s in species]
    low = [projections[s]["confidence_interval_low"] for s in species]
    high = [projections[s]["confidence_interval_high"] for s in species]
    names = [projections[s]["common_name"] for s in species]

    fig, ax = plt.subplots(figsize=(7.0, 1.2 + 0.55 * len(species)))

    y_pos = range(len(species))

    # Hog is navy; other species get the blue shade.
    bar_colors = [
        COLORS["brand_navy"] if sp == "feral_hog"
        else COLORS["brand_blue"]
        for sp in species
    ]
    ax.barh(y_pos, central,
            color=bar_colors,
            height=0.5,
            edgecolor=COLORS["page_bg"], linewidth=0.5, zorder=3)

    # CI bracket — line + caps.  Segments that overlap the bar
    # are drawn white; segments outside the bar stay navy.
    for i, (lo, hi, c) in enumerate(zip(low, high, central)):
        # Horizontal line — split at the bar's right edge (central).
        # Portion inside bar (lo → min(hi, c)): white
        # Portion outside bar (c → hi): navy
        if lo < c:
            ax.plot([lo, min(hi, c)], [i, i],
                    color="#FFFFFF", linewidth=1.4, zorder=4)
        if hi > c:
            ax.plot([c, hi], [i, i],
                    color=COLORS["brand_navy"], linewidth=1.2, zorder=4)

        # Left cap — inside the bar when lo < central
        lo_color = "#FFFFFF" if lo < c else COLORS["brand_navy"]
        ax.plot([lo, lo], [i - 0.15, i + 0.15],
                color=lo_color, linewidth=1.4, zorder=5)
        # Right cap — inside the bar when hi <= central (rare)
        hi_color = "#FFFFFF" if hi <= c else COLORS["brand_navy"]
        ax.plot([hi, hi], [i - 0.15, i + 0.15],
                color=hi_color, linewidth=1.4, zorder=5)

    # Value labels — italic serif, navy
    for i, c in enumerate(central):
        ax.text(high[i] + (max(high) * 0.01), i,
                f"${c:,.0f}",
                va="center", fontsize=9,
                fontstyle="italic",
                color=COLORS["brand_navy"])

    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(names, fontsize=9.5,
                       color=COLORS["text_primary"])
    ax.set_xlabel("Estimated annual loss (USD)",
                  fontsize=8, fontstyle="italic",
                  color=COLORS["text_secondary"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLORS["text_primary"])
    ax.spines["left"].set_linewidth(0.8)
    ax.spines["bottom"].set_color(COLORS["text_primary"])
    ax.spines["bottom"].set_linewidth(0.8)
    ax.tick_params(colors=COLORS["text_secondary"], labelsize=8)
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=COLORS["gridline"], linewidth=0.4)
    # Leave room on the right for the value labels
    ax.set_xlim(0, max(high) * 1.18)

    fig.tight_layout()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=180, bbox_inches="tight",
                facecolor=COLORS["page_bg"], edgecolor="none")
    plt.close(fig)
    return tmp.name
