"""Parcel map section — spatial visualization.

Matplotlib scatter plot of camera locations over parcel boundary.
Species detection markers, habitat unit boundaries as dashed overlay.
Hog detections visually dominant (larger markers, red).

Falls back gracefully if contextily is unavailable (no basemap tiles).
"""

import json
import tempfile
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, Spacer

from report.styles import (
    COLORS, CONTENT_WIDTH,
    STYLE_BODY_SMALL, STYLE_CAPTION,
    section_bar, setup_chart_style,
)

setup_chart_style()


def render(assessment: dict, detections=None, cameras_json=None,
           parcel_geojson=None) -> list:
    """Return flowables for the parcel map page."""
    elements = []

    elements.append(section_bar("Parcel Overview", CONTENT_WIDTH))
    elements.append(Spacer(1, 0.12 * inch))

    # Generate the map chart
    map_path = _make_parcel_map(
        assessment, detections, cameras_json, parcel_geojson)

    if map_path:
        elements.append(Image(map_path,
                              width=CONTENT_WIDTH,
                              height=5.5 * inch))
        elements.append(Paragraph(
            "Camera stations shown as open circles; stations where "
            "feral hogs were detected are marked with a filled navy "
            "diamond. Each label carries a placement-context suffix: "
            "f\u2009=\u2009feeder, p\u2009=\u2009food plot, "
            "w\u2009=\u2009water, t\u2009=\u2009trail, "
            "r\u2009=\u2009random, o\u2009=\u2009other. "
            "The parcel boundary is the white outline. "
            "Imagery: Esri World Imagery.",
            STYLE_CAPTION))
    else:
        elements.append(Paragraph(
            "Map generation requires camera location data. "
            "No spatial data available for this assessment.",
            STYLE_BODY_SMALL))

    return elements


def _make_parcel_map(assessment, detections, cameras_json,
                     parcel_geojson) -> str:
    """Generate the parcel map as a PNG and return the temp file path."""

    # Load camera data
    if cameras_json is None:
        try:
            cam_path = (Path(__file__).parent.parent.parent
                        / "demo" / "demo_data" / "cameras.json")
            with open(cam_path) as f:
                cameras_json = json.load(f)
        except Exception:
            return None

    if not cameras_json:
        return None

    # Load parcel boundary
    if parcel_geojson is None:
        try:
            parcel_path = (Path(__file__).parent.parent.parent
                           / "demo" / "demo_data" / "parcel.geojson")
            with open(parcel_path) as f:
                parcel_geojson = json.load(f)
        except Exception:
            pass

    # ── Coordinate helpers ──
    # contextily needs Web Mercator (EPSG:3857). Convert lon/lat on
    # the fly so we can overlay satellite tiles.
    def _to_mercator(lon, lat):
        """Convert WGS-84 lon/lat → Web Mercator x/y."""
        import math
        x = lon * 20037508.34 / 180.0
        y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
        y = y * 20037508.34 / 180.0
        return x, y

    def _to_mercator_arrays(lons_arr, lats_arr):
        xs, ys = [], []
        for lo, la in zip(lons_arr, lats_arr):
            x, y = _to_mercator(lo, la)
            xs.append(x)
            ys.append(y)
        return xs, ys

    _use_satellite = False
    try:
        import contextily as cx
        _use_satellite = True
    except ImportError:
        pass

    fig, ax = plt.subplots(figsize=(7.0, 5.5))

    # Draw parcel boundary
    boundary_lons, boundary_lats = [], []
    if parcel_geojson:
        try:
            coords = parcel_geojson["features"][0]["geometry"]["coordinates"][0]
            boundary_lons = [c[0] for c in coords]
            boundary_lats = [c[1] for c in coords]
        except (KeyError, IndexError):
            pass

    if _use_satellite and boundary_lons:
        # Plot in Mercator for satellite tile alignment
        bx, by = _to_mercator_arrays(boundary_lons, boundary_lats)
        ax.plot(bx, by, color="#FFFFFF", linewidth=2.0, zorder=2)
        ax.fill(bx, by, color="#FFFFFF", alpha=0.08, zorder=1)
    elif boundary_lons:
        ax.plot(boundary_lons, boundary_lats,
                color=COLORS["brand_navy"], linewidth=1.2, zorder=2)
        ax.fill(boundary_lons, boundary_lats,
                color=COLORS["brand_navy"], alpha=0.03, zorder=1)

    # Build species-per-camera lookup from inventory
    cam_species = {}
    cam_hog_detected = set()
    inventory = assessment.get("species_inventory", [])

    # Use detection data to map cameras to species
    if detections:
        from collections import defaultdict
        cam_sp_counts = defaultdict(lambda: defaultdict(int))
        for det in detections:
            cam_sp_counts[det.camera_id][det.species_key] += 1
        cam_species = dict(cam_sp_counts)
        for cid, sps in cam_sp_counts.items():
            if "feral_hog" in sps:
                cam_hog_detected.add(cid)
    else:
        # Estimate from camera placement context
        for cam in cameras_json:
            cid = cam["camera_id"]
            ctx = cam.get("placement_context", "")
            if ctx in ("feeder", "food_plot", "water"):
                cam_hog_detected.add(cid)

    # Plot cameras
    cam_lats = [c["lat"] for c in cameras_json]
    cam_lons = [c["lon"] for c in cameras_json]
    cam_ids = [c["camera_id"] for c in cameras_json]

    # Hog cameras: larger red markers
    hog_lats = [lat for lat, cid in zip(cam_lats, cam_ids)
                if cid in cam_hog_detected]
    hog_lons = [lon for lon, cid in zip(cam_lons, cam_ids)
                if cid in cam_hog_detected]
    non_hog_lats = [lat for lat, cid in zip(cam_lats, cam_ids)
                    if cid not in cam_hog_detected]
    non_hog_lons = [lon for lon, cid in zip(cam_lons, cam_ids)
                    if cid not in cam_hog_detected]

    if _use_satellite:
        # Convert to Mercator for satellite tiles
        hog_xs, hog_ys = _to_mercator_arrays(hog_lons, hog_lats)
        non_hog_xs, non_hog_ys = _to_mercator_arrays(
            non_hog_lons, non_hog_lats)
        plot_cam_x = [_to_mercator(lo, la)[0]
                      for lo, la in zip(cam_lons, cam_lats)]
        plot_cam_y = [_to_mercator(lo, la)[1]
                      for lo, la in zip(cam_lons, cam_lats)]
    else:
        hog_xs, hog_ys = hog_lons, hog_lats
        non_hog_xs, non_hog_ys = non_hog_lons, non_hog_lats
        plot_cam_x, plot_cam_y = cam_lons, cam_lats

    # Marker colors — white outlines on satellite, gray on white bg
    _marker_edge = "#FFFFFF" if _use_satellite else COLORS["text_secondary"]
    _marker_face = "#FFFFFF" if _use_satellite else COLORS["page_bg"]
    _hog_fill = "#FFFFFF" if _use_satellite else COLORS["brand_navy"]
    _hog_edge = "#FFFFFF" if _use_satellite else COLORS["brand_navy"]

    ax.scatter(non_hog_xs, non_hog_ys, s=55,
               facecolors=_marker_face,
               edgecolors=_marker_edge,
               linewidth=1.2, zorder=4, label="Camera station")
    ax.scatter(hog_xs, hog_ys, s=120,
               c=_hog_fill,
               edgecolors=_hog_edge,
               linewidth=0.8, zorder=5, marker="D",
               label="Hog detected")

    # Camera labels — monospace so 0 (slashed) ≠ O.
    # Placement context appended as a lowercase letter code:
    #   f = feeder, p = food plot, w = water, t = trail, r = random
    _CTX_CODES = {
        "feeder": "f",
        "food_plot": "p",
        "water": "w",
        "trail": "t",
        "random": "r",
        "other": "o",
    }

    def _slashed_zeros(s: str) -> str:
        """Replace digit 0 with slashed-zero (U+00D8) for legibility."""
        return s.replace("0", "\u00D8")

    _label_color = "#FFFFFF" if _use_satellite else COLORS["text_secondary"]

    cam_lookup = {c["camera_id"]: c for c in cameras_json}
    for px, py, cid in zip(plot_cam_x, plot_cam_y, cam_ids):
        short_id = _slashed_zeros(cid.replace("CAM-", ""))
        ctx = cam_lookup.get(cid, {}).get("placement_context", "")
        code = _CTX_CODES.get(ctx, "")
        label = f"{short_id}-{code}" if code else short_id
        ax.annotate(label, (px, py), fontsize=6,
                    fontfamily="monospace",
                    fontstyle="italic",
                    fontweight="bold" if _use_satellite else "normal",
                    color=_label_color,
                    xytext=(4, 4), textcoords="offset points",
                    zorder=6)

    if _use_satellite:
        # Hide axis decorations — the satellite image speaks for itself
        ax.set_xlabel("")
        ax.set_ylabel("")
        ax.tick_params(labelbottom=False, labelleft=False,
                       bottom=False, left=False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_aspect("equal")
    else:
        ax.set_xlabel("Longitude", fontsize=8, fontstyle="italic",
                      color=COLORS["text_secondary"])
        ax.set_ylabel("Latitude", fontsize=8, fontstyle="italic",
                      color=COLORS["text_secondary"])
        ax.tick_params(labelsize=7, colors=COLORS["text_secondary"])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(COLORS["text_primary"])
        ax.spines["left"].set_linewidth(0.7)
        ax.spines["bottom"].set_color(COLORS["text_primary"])
        ax.spines["bottom"].set_linewidth(0.7)
        ax.set_aspect("equal")

    # Legend — white background box for readability on satellite
    leg = ax.legend(
        loc="upper right", fontsize=8,
        frameon=True, fancybox=False,
        edgecolor=COLORS["border_light"],
        facecolor=COLORS["page_bg"],
        framealpha=0.95,
        borderpad=0.7,
        handletextpad=0.8,
        labelspacing=1.0,
        scatterpoints=1,
        markerscale=0.8,
    )
    leg.get_frame().set_linewidth(0.7)
    for text in leg.get_texts():
        text.set_color(COLORS["text_primary"])
    # Re-color legend markers to navy so they're visible on white box
    for handle in leg.legend_handles:
        handle.set_edgecolor(COLORS["brand_navy"])
        if hasattr(handle, 'get_facecolor'):
            fc = handle.get_facecolor()
            # Diamond (hog) gets navy fill; circle stays open
            if handle.get_label() == "Hog detected":
                handle.set_facecolor(COLORS["brand_navy"])
            else:
                handle.set_facecolor(COLORS["page_bg"])

    county = assessment.get("county", "")
    state = assessment.get("state", "")
    acreage = assessment.get("acreage", 0)
    _title_color = "#FFFFFF" if _use_satellite else COLORS["brand_navy"]
    ax.set_title(
        f"{county} County, {state}   ·   {acreage:,.0f} acres   ·   "
        f"{len(cameras_json)} camera stations",
        fontsize=11, fontweight="bold",
        color=_title_color, pad=12)

    # ── Satellite basemap ──
    if _use_satellite:
        try:
            cx.add_basemap(
                ax,
                source=cx.providers.Esri.WorldImagery,
                zoom="auto",
                attribution=False,
            )
        except Exception:
            # Network failure — fall back to white background
            pass

    fig.tight_layout()

    _bg = "none" if _use_satellite else COLORS["page_bg"]
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    fig.savefig(tmp.name, dpi=300, bbox_inches="tight",
                facecolor=COLORS["page_bg"], edgecolor="none")
    plt.close(fig)
    return tmp.name
