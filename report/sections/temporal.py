"""Temporal analysis — activity patterns by hour and trend.

Detection-by-hour bar charts for key species (hog, deer, axis deer).
Weekly trend line showing activity direction over the monitoring period.
"""

import tempfile
from collections import defaultdict
from datetime import datetime
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, Spacer

from report.styles import (
    COLORS, CONTENT_WIDTH,
    STYLE_H2, STYLE_BODY_SMALL, STYLE_CAPTION,
    section_bar, setup_chart_style,
)

setup_chart_style()


# Species to chart (in order). Navy for hog (the subject), blue for
# deer, neutral gray for axis deer — the McKinsey palette lets the hog
# series read as primary without looking like monochrome print.
_KEY_SPECIES = ["feral_hog", "white_tailed_deer", "axis_deer"]
_SPECIES_COLORS = {
    "feral_hog": COLORS["brand_navy"],
    "white_tailed_deer": COLORS["brand_blue"],
    "axis_deer": COLORS["chart_neutral"],
}
_SPECIES_NAMES = {
    "feral_hog": "Feral Hog",
    "white_tailed_deer": "White-tailed Deer",
    "axis_deer": "Axis Deer",
}


def render(assessment: dict, detections=None) -> list:
    """Return flowables for the temporal analysis page."""
    elements = []

    elements.append(section_bar("Activity Patterns", CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    if detections is None:
        elements.append(Paragraph(
            "Temporal analysis requires detection-level data. "
            "See species inventory for aggregate frequencies.",
            STYLE_BODY_SMALL))
        return elements

    # Build hourly data per species
    species_hourly = defaultdict(lambda: defaultdict(set))
    species_weekly = defaultdict(lambda: defaultdict(set))

    for det in detections:
        sp = det.species_key
        hour = det.timestamp.hour
        species_hourly[sp][hour].add(det.independent_event_id)

        # Weekly: ISO week number
        week_key = det.timestamp.strftime("%Y-W%W")
        species_weekly[sp][week_key].add(det.independent_event_id)

    # Generate combined activity chart
    chart_path = _make_combined_activity(species_hourly)
    if chart_path:
        elements.append(Image(chart_path,
                              width=CONTENT_WIDTH,
                              height=3.2 * inch))
        elements.append(Paragraph(
            "Independent events by hour of day. Shading indicates "
            "dawn (05:00\u201307:00), dusk (17:00\u201320:00), "
            "and night periods.",
            STYLE_CAPTION))

    # Generate weekly trend chart
    elements.append(Spacer(1, 0.12 * inch))
    elements.append(Paragraph("Weekly Activity Trend", STYLE_H2))

    trend_path = _make_weekly_trend(species_weekly)
    if trend_path:
        elements.append(Image(trend_path,
                              width=CONTENT_WIDTH,
                              height=2.5 * inch))
        elements.append(Paragraph(
            "Weekly independent event counts. Trend lines show "
            "direction of activity over the monitoring period.",
            STYLE_CAPTION))

    # Activity pattern summary
    elements.append(Spacer(1, 0.15 * inch))
    for sp_key in _KEY_SPECIES:
        if sp_key in species_hourly:
            hourly = {h: len(evts)
                      for h, evts in species_hourly[sp_key].items()}
            pattern, night_pct, day_pct = _classify_pattern(hourly)
            name = _SPECIES_NAMES.get(sp_key, sp_key)
            elements.append(Paragraph(
                f"<b>{name}:</b> {pattern} "
                f"({night_pct}% nocturnal, {day_pct}% diurnal)",
                STYLE_BODY_SMALL))

    return elements


def _make_combined_activity(species_hourly: dict) -> str:
    """Three-panel hourly activity chart for key species."""
    present = [s for s in _KEY_SPECIES if s in species_hourly]
    if not present:
        return None

    n_panels = len(present)
    fig, axes = plt.subplots(1, n_panels,
                             figsize=(7.0, 2.8),
                             sharey=False)
    if n_panels == 1:
        axes = [axes]

    hours = list(range(24))

    for ax, sp_key in zip(axes, present):
        hourly = species_hourly[sp_key]
        counts = [len(hourly.get(h, set())) for h in hours]
        color = _SPECIES_COLORS.get(sp_key, COLORS["text_primary"])

        ax.bar(hours, counts, color=color,
               edgecolor=COLORS["page_bg"],
               linewidth=0.3)

        # Diel shading — neutral grey bands, no hue
        ax.axvspan(-0.5, 5, alpha=0.08, color=COLORS["text_secondary"])
        ax.axvspan(20, 23.5, alpha=0.08, color=COLORS["text_secondary"])
        ax.axvspan(5, 7, alpha=0.04, color=COLORS["text_secondary"])
        ax.axvspan(17, 20, alpha=0.04, color=COLORS["text_secondary"])

        name = _SPECIES_NAMES.get(sp_key, sp_key)
        ax.set_title(name, fontsize=10, fontweight="bold",
                     color=COLORS["text_primary"], pad=6)
        ax.set_xlabel("Hour", fontsize=7.5, fontstyle="italic",
                      color=COLORS["text_secondary"])
        ax.set_xticks([0, 6, 12, 18, 23])
        ax.set_xticklabels(["00", "06", "12", "18", "23"], fontsize=7)
        ax.set_xlim(-0.5, 23.5)
        ax.tick_params(labelsize=7, colors=COLORS["text_secondary"])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(COLORS["text_primary"])
        ax.spines["left"].set_linewidth(0.7)
        ax.spines["bottom"].set_color(COLORS["text_primary"])
        ax.spines["bottom"].set_linewidth(0.7)
        ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    axes[0].set_ylabel("Events", fontsize=7.5, fontstyle="italic",
                       color=COLORS["text_secondary"])
    fig.tight_layout()

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=180, bbox_inches="tight",
                facecolor=COLORS["page_bg"], edgecolor="none")
    plt.close(fig)
    return tmp.name


def _make_weekly_trend(species_weekly: dict) -> str:
    """Weekly event trend with regression lines."""
    present = [s for s in _KEY_SPECIES if s in species_weekly]
    if not present:
        return None

    fig, ax = plt.subplots(figsize=(7.0, 2.2))

    # Monochrome: solid / dashed / dotted linestyles differentiate
    # species instead of hue. Hog is the solid black line.
    linestyles = {
        "feral_hog": "-",
        "white_tailed_deer": "--",
        "axis_deer": ":",
    }
    markers = {
        "feral_hog": "o",
        "white_tailed_deer": "s",
        "axis_deer": "^",
    }

    for sp_key in present:
        weekly = species_weekly[sp_key]
        if not weekly:
            continue

        sorted_weeks = sorted(weekly.keys())
        counts = [len(weekly[w]) for w in sorted_weeks]
        x = np.arange(len(counts))

        color = _SPECIES_COLORS.get(sp_key, COLORS["text_primary"])
        name = _SPECIES_NAMES.get(sp_key, sp_key)

        ax.plot(x, counts,
                color=color,
                linewidth=1.4,
                linestyle=linestyles.get(sp_key, "-"),
                marker=markers.get(sp_key, "o"),
                markersize=3.5,
                markerfacecolor=color,
                markeredgecolor=color,
                label=name)

    ax.set_xlabel("Week", fontsize=7.5, fontstyle="italic",
                  color=COLORS["text_secondary"])
    ax.set_ylabel("Events", fontsize=7.5, fontstyle="italic",
                  color=COLORS["text_secondary"])
    ax.tick_params(labelsize=7, colors=COLORS["text_secondary"])
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(COLORS["text_primary"])
    ax.spines["left"].set_linewidth(0.7)
    ax.spines["bottom"].set_color(COLORS["text_primary"])
    ax.spines["bottom"].set_linewidth(0.7)
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    leg = ax.legend(fontsize=8, frameon=False,
                    loc="upper right")
    for text in leg.get_texts():
        text.set_color(COLORS["text_primary"])
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=COLORS["gridline"], linewidth=0.4)

    fig.tight_layout()
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=180, bbox_inches="tight",
                facecolor=COLORS["page_bg"], edgecolor="none")
    plt.close(fig)
    return tmp.name


def _classify_pattern(hourly: dict):
    """Classify activity as Nocturnal/Diurnal/Crepuscular."""
    night = sum(hourly.get(h, 0)
                for h in list(range(0, 5)) + list(range(21, 24)))
    day = sum(hourly.get(h, 0) for h in range(7, 18))
    total = sum(hourly.values()) or 1
    night_pct = int(night / total * 100)
    day_pct = int(day / total * 100)
    if night_pct > 65:
        return "Nocturnal", night_pct, day_pct
    if day_pct > 65:
        return "Diurnal", night_pct, day_pct
    return "Crepuscular", night_pct, day_pct
