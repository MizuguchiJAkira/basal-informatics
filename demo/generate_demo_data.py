"""Generate synthetic demo data for Basal Informatics.

⚠️ SYNTHETIC — NOT A REAL RANCH. The "Edwards Plateau Ranch" scenario
(a 2,340-acre parcel in Kimble County, TX, 14 cameras, 12 species,
~12K raw photos) is FABRICATED for product demo, test fixtures, and
the sample Nature Exposure Report. It is not a real customer, not
real trail-camera photos, and not representative of the pipeline's
statistical performance on real data. See ``demo/README.md``.

Production data (live Farm Credit pilot parcels, Strecker hunter
uploads) lives in the prod Postgres + Spaces, never in this
repository.

Usage:
    python -m demo.generate_demo_data
    python manage.py demo generate
    python manage.py db seed          # generates + inserts into PostGIS
"""

import json
import math
import os
from datetime import datetime, timedelta, date
from pathlib import Path

import numpy as np

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

SEED = 42
START = datetime(2025, 3, 1)
END = datetime(2026, 1, 31, 23, 59, 59)
N_DAYS = (date(2026, 1, 31) - date(2025, 3, 1)).days + 1  # 337

PARCEL_ID = "DEMO-KIM-001"
PARCEL_ACREAGE = 2340
PARCEL_COUNTY = "Kimble"
PARCEL_STATE = "TX"

ECO_III = ("30", "Edwards Plateau")
ECO_IV = ("30a", "Limestone Cut Plain")
HUC10 = ("1209020104", "Johnson Fork")

# Full moons in active period — ±3 days = bright moon nights
_FULL_MOONS = [
    date(2025, 3, 14), date(2025, 4, 13), date(2025, 5, 12),
    date(2025, 6, 11), date(2025, 7, 10), date(2025, 8, 9),
    date(2025, 9, 7), date(2025, 10, 7), date(2025, 11, 5),
    date(2025, 12, 4), date(2026, 1, 3),
]
BRIGHT_NIGHTS = set()
for _fm in _FULL_MOONS:
    for _d in range(-3, 4):
        BRIGHT_NIGHTS.add(_fm + timedelta(days=_d))

# Parcel boundary (lon, lat) — closed ring, ~2,340 acres
# Shifted ~12mi SW of Junction into deep Edwards Plateau ranch country
# so satellite imagery shows cedar breaks + rangeland, not town.
_LAT_SHIFT = -0.15
_LON_SHIFT = -0.15
PARCEL_RING = [
    (lon + _LON_SHIFT, lat + _LAT_SHIFT) for lon, lat in [
        (-99.7680, 30.5050), (-99.7580, 30.5070), (-99.7420, 30.5040),
        (-99.7330, 30.4950), (-99.7340, 30.4820), (-99.7380, 30.4730),
        (-99.7520, 30.4740), (-99.7600, 30.4760), (-99.7670, 30.4800),
        (-99.7690, 30.4920), (-99.7680, 30.5050),
    ]
]

# West-side cameras — nearest to exotic ranch (axis deer restriction)
WEST_CAMERAS = {"CAM-R01", "CAM-O02", "CAM-W01", "CAM-P02"}


# ═══════════════════════════════════════════════════════════════════════════
# Camera Stations — 14 cameras, 8 contributors
# ═══════════════════════════════════════════════════════════════════════════

CAMERAS = [
    # --- 3 feeder cameras: near protein feeders, center of parcel ---
    dict(camera_id="CAM-F01", lat=30.3420, lon=-99.9020, user_id="USER-01",
         placement_context="feeder", camera_model="Reconyx HyperFire 2",
         installed_date="2025-02-20", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=545, slope_degrees=4.2,
         distance_to_water_m=180, stream_order=2, canopy_cover_pct=62,
         soil_type="Tarrant-Brackett"),
    dict(camera_id="CAM-F02", lat=30.3380, lon=-99.8980, user_id="USER-01",
         placement_context="feeder", camera_model="Reconyx HyperFire 2",
         installed_date="2025-02-20", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=538, slope_degrees=3.8,
         distance_to_water_m=150, stream_order=2, canopy_cover_pct=58,
         soil_type="Tarrant-Brackett"),
    dict(camera_id="CAM-F03", lat=30.3450, lon=-99.8950, user_id="USER-02",
         placement_context="feeder", camera_model="Browning Strike Force Pro DCL",
         installed_date="2025-02-25", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=542, slope_degrees=5.1,
         distance_to_water_m=220, stream_order=2, canopy_cover_pct=55,
         soil_type="Tarrant-Brackett"),

    # --- 2 water cameras: along Johnson Fork creek/drainage ---
    dict(camera_id="CAM-W01", lat=30.3470, lon=-99.9080, user_id="USER-03",
         placement_context="water", camera_model="Stealth Cam DS4K",
         installed_date="2025-03-01", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=498, slope_degrees=2.1,
         distance_to_water_m=12, stream_order=3, canopy_cover_pct=48,
         soil_type="Dev-Frio"),
    dict(camera_id="CAM-W02", lat=30.3320, lon=-99.8920, user_id="USER-03",
         placement_context="water", camera_model="Stealth Cam DS4K",
         installed_date="2025-03-05", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=502, slope_degrees=2.8,
         distance_to_water_m=8, stream_order=3, canopy_cover_pct=45,
         soil_type="Dev-Frio"),

    # --- 3 food plot cameras: edge of planted clearings ---
    dict(camera_id="CAM-P01", lat=30.3500, lon=-99.9000, user_id="USER-02",
         placement_context="food_plot", camera_model="Browning Strike Force Pro DCL",
         installed_date="2025-02-28", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-71", nlcd_code=71,
         nlcd_class="Grassland/Herbaceous", elevation_m=530, slope_degrees=3.5,
         distance_to_water_m=320, stream_order=1, canopy_cover_pct=12,
         soil_type="Tarrant-Brackett"),
    dict(camera_id="CAM-P02", lat=30.3350, lon=-99.9050, user_id="USER-04",
         placement_context="food_plot", camera_model="Bushnell Core S-4K",
         installed_date="2025-03-01", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-71", nlcd_code=71,
         nlcd_class="Grassland/Herbaceous", elevation_m=525, slope_degrees=4.8,
         distance_to_water_m=250, stream_order=1, canopy_cover_pct=8,
         soil_type="Tarrant-Brackett"),
    dict(camera_id="CAM-P03", lat=30.3400, lon=-99.8880, user_id="USER-04",
         placement_context="food_plot", camera_model="Bushnell Core S-4K",
         installed_date="2025-03-10", last_active="2025-12-15",
         habitat_unit_id="HU-1209020104-30a-71", nlcd_code=71,
         nlcd_class="Grassland/Herbaceous", elevation_m=518, slope_degrees=3.2,
         distance_to_water_m=280, stream_order=1, canopy_cover_pct=10,
         soil_type="Tarrant-Brackett"),

    # --- 2 trail cameras: game trails at habitat edges ---
    dict(camera_id="CAM-T01", lat=30.3530, lon=-99.8930, user_id="USER-05",
         placement_context="trail", camera_model="Moultrie Mobile Edge",
         installed_date="2025-03-01", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-52", nlcd_code=52,
         nlcd_class="Shrub/Scrub", elevation_m=555, slope_degrees=7.2,
         distance_to_water_m=350, stream_order=1, canopy_cover_pct=32,
         soil_type="Eckrant-Real"),
    dict(camera_id="CAM-T02", lat=30.3280, lon=-99.8980, user_id="USER-05",
         placement_context="trail", camera_model="Moultrie Mobile Edge",
         installed_date="2025-03-01", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-52", nlcd_code=52,
         nlcd_class="Shrub/Scrub", elevation_m=520, slope_degrees=6.5,
         distance_to_water_m=120, stream_order=2, canopy_cover_pct=28,
         soil_type="Tarrant-Brackett"),

    # --- 2 random cameras: unbiased baseline ---
    dict(camera_id="CAM-R01", lat=30.3480, lon=-99.9130, user_id="USER-06",
         placement_context="random", camera_model="Reconyx HyperFire 2",
         installed_date="2025-03-15", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-41", nlcd_code=41,
         nlcd_class="Deciduous Forest", elevation_m=540, slope_degrees=5.0,
         distance_to_water_m=400, stream_order=1, canopy_cover_pct=50,
         soil_type="Tarrant-Brackett"),
    dict(camera_id="CAM-R02", lat=30.3300, lon=-99.8860, user_id="USER-07",
         placement_context="random", camera_model="Bushnell Core S-4K",
         installed_date="2025-03-15", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-71", nlcd_code=71,
         nlcd_class="Grassland/Herbaceous", elevation_m=510, slope_degrees=3.0,
         distance_to_water_m=450, stream_order=1, canopy_cover_pct=5,
         soil_type="Tarrant-Brackett"),

    # --- 2 other cameras: ridgeline + sendero ---
    dict(camera_id="CAM-O01", lat=30.3540, lon=-99.9050, user_id="USER-08",
         placement_context="other", camera_model="Stealth Cam DS4K",
         installed_date="2025-03-01", last_active="2026-01-31",
         habitat_unit_id="HU-1209020104-30a-52", nlcd_code=52,
         nlcd_class="Shrub/Scrub", elevation_m=575, slope_degrees=12.3,
         distance_to_water_m=500, stream_order=0, canopy_cover_pct=25,
         soil_type="Eckrant-Real"),
    dict(camera_id="CAM-O02", lat=30.3260, lon=-99.9100, user_id="USER-08",
         placement_context="other", camera_model="Browning Strike Force Pro DCL",
         installed_date="2025-02-15", last_active="2026-01-15",
         habitat_unit_id="HU-1209020104-30a-52", nlcd_code=52,
         nlcd_class="Shrub/Scrub", elevation_m=535, slope_degrees=8.5,
         distance_to_water_m=300, stream_order=1, canopy_cover_pct=22,
         soil_type="Eckrant-Real"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Species Detection Configuration — 12 detected species
# ═══════════════════════════════════════════════════════════════════════════

SPECIES = {
    "white_tailed_deer": dict(
        events=1400, photos=4800, n_cameras=14,
        conf_mean=0.92, conf_std=0.03, temporal="crepuscular",
        affinity=dict(feeder=1.5, food_plot=2.0, trail=1.5,
                      water=1.2, random=1.0, other=0.8)),
    "feral_hog": dict(
        events=680, photos=2250, n_cameras=11,
        conf_mean=0.89, conf_std=0.04, temporal="nocturnal_hog",
        affinity=dict(feeder=3.0, water=2.5, food_plot=1.5,
                      trail=1.0, random=1.0, other=0.5),
        lunar_avoidance=True),
    "turkey": dict(
        events=450, photos=1440, n_cameras=9,
        conf_mean=0.91, conf_std=0.03, temporal="diurnal_morning",
        affinity=dict(food_plot=2.5, trail=1.5, random=1.2,
                      feeder=1.0, water=0.8, other=0.8)),
    "raccoon": dict(
        events=380, photos=1200, n_cameras=12,
        conf_mean=0.87, conf_std=0.04, temporal="nocturnal",
        affinity=dict(feeder=3.0, water=2.0, food_plot=1.2,
                      trail=1.0, random=1.0, other=0.8)),
    "armadillo": dict(
        events=230, photos=720, n_cameras=8,
        conf_mean=0.85, conf_std=0.04, temporal="nocturnal",
        affinity=dict(trail=1.5, food_plot=1.3, random=1.2,
                      water=1.0, feeder=0.8, other=1.0)),
    "coyote": dict(
        events=190, photos=600, n_cameras=10,
        conf_mean=0.86, conf_std=0.04, temporal="crepuscular",
        affinity=dict(trail=1.8, random=1.5, food_plot=1.2,
                      water=1.0, feeder=0.8, other=1.2)),
    "bobcat": dict(
        events=110, photos=360, n_cameras=6,
        conf_mean=0.84, conf_std=0.04, temporal="crepuscular",
        affinity=dict(trail=2.0, water=1.5, random=1.2,
                      food_plot=0.8, feeder=0.5, other=1.0)),
    "cottontail_rabbit": dict(
        events=80, photos=240, n_cameras=7,
        conf_mean=0.83, conf_std=0.04, temporal="crepuscular",
        affinity=dict(food_plot=2.5, trail=1.5, random=1.5,
                      water=0.8, feeder=0.5, other=1.0)),
    "axis_deer": dict(
        events=55, photos=180, n_cameras=4,
        conf_mean=0.82, conf_std=0.05, temporal="crepuscular",
        affinity=dict(food_plot=1.5, trail=1.2, random=1.0,
                      water=1.0, feeder=0.8, other=0.8),
        restrict_to=WEST_CAMERAS),
    "opossum": dict(
        events=40, photos=120, n_cameras=5,
        conf_mean=0.80, conf_std=0.05, temporal="nocturnal",
        affinity=dict(feeder=2.0, water=1.5, trail=1.0,
                      random=1.0, food_plot=1.0, other=0.8)),
    "red_fox": dict(
        events=20, photos=60, n_cameras=3,
        conf_mean=0.78, conf_std=0.05, temporal="crepuscular",
        affinity=dict(trail=1.5, random=1.2, food_plot=1.0,
                      water=0.8, feeder=0.5, other=1.0)),
    "gray_fox": dict(
        events=10, photos=30, n_cameras=2,
        conf_mean=0.76, conf_std=0.05, temporal="nocturnal",
        affinity=dict(trail=1.5, random=1.0, water=1.0,
                      food_plot=0.8, feeder=0.5, other=1.2)),
}


# ═══════════════════════════════════════════════════════════════════════════
# Temporal Patterns — hourly probability distributions (24 elements)
# ═══════════════════════════════════════════════════════════════════════════

def _norm(a):
    """Normalize to probability distribution."""
    a = np.array(a, dtype=float)
    return a / a.sum()

TEMPORAL = {
    # Crepuscular: dawn 5-8 AM, dusk 5-8 PM
    "crepuscular": _norm([
        0.01, 0.01, 0.01, 0.01, 0.02,   # 0-4
        0.08, 0.15, 0.12, 0.05, 0.02,   # 5-9
        0.01, 0.01, 0.01, 0.01, 0.01,   # 10-14
        0.01, 0.02, 0.08, 0.15, 0.12,   # 15-19
        0.05, 0.02, 0.01, 0.01,         # 20-23
    ]),
    # Nocturnal: peak 10 PM - 5 AM
    "nocturnal": _norm([
        0.12, 0.10, 0.08, 0.06, 0.04,   # 0-4
        0.013, 0.013, 0.013, 0.013, 0.013,  # 5-9
        0.013, 0.013, 0.013, 0.013, 0.013,  # 10-14
        0.013, 0.013, 0.013, 0.013, 0.013,  # 15-19
        0.06, 0.10, 0.12, 0.12,         # 20-23
    ]),
    # Feral hog: 70% between 10 PM - 5 AM, reduced on bright moon nights
    "nocturnal_hog": _norm([
        0.15, 0.12, 0.10, 0.08, 0.05,   # 0-4: 0.50
        0.03, 0.018, 0.018, 0.018, 0.018,  # 5-9
        0.018, 0.018, 0.018, 0.018, 0.018,  # 10-14
        0.018, 0.018, 0.018, 0.018, 0.018,  # 15-19
        0.04, 0.034, 0.10, 0.10,        # 20-23: 0.274
    ]),
    # Turkey: ZERO at night, morning-heavy 6-10 AM
    "diurnal_morning": _norm([
        0, 0, 0, 0, 0, 0,               # 0-5: ZERO
        0.10, 0.20, 0.25, 0.20, 0.10,   # 6-10
        0.05, 0.03, 0.02, 0.02, 0.02, 0.01,  # 11-16
        0, 0, 0, 0, 0, 0, 0,            # 17-23: ZERO
    ]),
}


# ═══════════════════════════════════════════════════════════════════════════
# Habitat Units — 3 units from HUC10 × Ecoregion IV × NLCD intersection
# ═══════════════════════════════════════════════════════════════════════════

HABITAT_UNITS = [
    dict(id="HU-1209020104-30a-41",
         huc10=HUC10[0], huc10_name=HUC10[1],
         ecoregion_iv_code=ECO_IV[0], ecoregion_iv_name=ECO_IV[1],
         ecoregion_iii_code=ECO_III[0], ecoregion_iii_name=ECO_III[1],
         nlcd_code=41, nlcd_class="Deciduous Forest", area_km2=4.26,
         geom_wkt="MULTIPOLYGON(((-99.918 30.355,-99.908 30.357,-99.892 30.354,"
                  "-99.895 30.340,-99.902 30.335,-99.910 30.338,"
                  "-99.918 30.342,-99.918 30.355)))"),
    dict(id="HU-1209020104-30a-52",
         huc10=HUC10[0], huc10_name=HUC10[1],
         ecoregion_iv_code=ECO_IV[0], ecoregion_iv_name=ECO_IV[1],
         ecoregion_iii_code=ECO_III[0], ecoregion_iii_name=ECO_III[1],
         nlcd_code=52, nlcd_class="Shrub/Scrub", area_km2=2.84,
         geom_wkt="MULTIPOLYGON(((-99.918 30.342,-99.910 30.338,-99.902 30.335,"
                  "-99.898 30.328,-99.902 30.324,-99.910 30.326,"
                  "-99.917 30.330,-99.919 30.342,-99.918 30.342)))"),
    dict(id="HU-1209020104-30a-71",
         huc10=HUC10[0], huc10_name=HUC10[1],
         ecoregion_iv_code=ECO_IV[0], ecoregion_iv_name=ECO_IV[1],
         ecoregion_iii_code=ECO_III[0], ecoregion_iii_name=ECO_III[1],
         nlcd_code=71, nlcd_class="Grassland/Herbaceous", area_km2=2.37,
         geom_wkt="MULTIPOLYGON(((-99.892 30.354,-99.883 30.345,-99.884 30.332,"
                  "-99.888 30.323,-99.898 30.328,-99.902 30.335,"
                  "-99.895 30.340,-99.892 30.354)))"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Corridors
# ═══════════════════════════════════════════════════════════════════════════

CORRIDORS = [
    # Corridors routed through camera clusters so coverage reflects
    # a well-planned deployment, not random scatter.
    # Riparian: W01 → F01 → F02 → W02 along the creek drainage
    dict(habitat_unit_id="HU-1209020104-30a-41", corridor_type="riparian",
         length_km=3.2,
         geom_wkt="LINESTRING(-99.908 30.347,-99.902 30.342,"
                  "-99.898 30.338,-99.892 30.332)"),
    # Ridge: O01 → T01 → F03 along the northern parcel edge
    dict(habitat_unit_id="HU-1209020104-30a-52", corridor_type="ridge",
         length_km=1.8,
         geom_wkt="LINESTRING(-99.905 30.354,-99.895 30.353,-99.893 30.345)"),
    # Forest-grass edge: F03 → P03 → R02 eastern boundary
    dict(habitat_unit_id="HU-1209020104-30a-71", corridor_type="forest_grass_edge",
         length_km=2.4,
         geom_wkt="LINESTRING(-99.895 30.345,-99.890 30.340,"
                  "-99.888 30.335,-99.886 30.330)"),
]


# ═══════════════════════════════════════════════════════════════════════════
# Generation Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _seasonal_weight(d):
    """Seasonal activity multiplier by month."""
    m = d.month
    if m in (3, 4, 5):
        return 0.9   # spring
    if m in (6, 7, 8):
        return 1.1   # summer
    if m in (9, 10, 11):
        return 1.2   # fall / rut
    return 0.8       # winter (Dec-Jan)


def _camera_active_range(cam):
    """Return (start_date, end_date) clipped to monitoring period."""
    s = max(START.date(), date.fromisoformat(cam["installed_date"]))
    e = min(END.date(), date.fromisoformat(cam["last_active"]))
    return s, e


def _select_cameras(cfg, rng):
    """Select which cameras detect this species, weighted by affinity."""
    pool = CAMERAS
    if "restrict_to" in cfg:
        pool = [c for c in pool if c["camera_id"] in cfg["restrict_to"]]

    n = min(cfg["n_cameras"], len(pool))
    weights = np.array([cfg["affinity"].get(c["placement_context"], 1.0) for c in pool])
    weights /= weights.sum()

    indices = rng.choice(len(pool), size=n, replace=False, p=weights)
    return [pool[i] for i in sorted(indices)]


def _distribute_events(cameras, cfg, rng):
    """Distribute target events across cameras proportional to affinity."""
    weights = np.array([cfg["affinity"].get(c["placement_context"], 1.0) for c in cameras])
    weights /= weights.sum()
    counts = rng.multinomial(cfg["events"], weights)
    return list(zip(cameras, counts))


def _random_date(cam, rng, seasonal_weights_cache={}):
    """Pick a random date within camera's active period, weighted by season."""
    cid = cam["camera_id"]
    if cid not in seasonal_weights_cache:
        s, e = _camera_active_range(cam)
        days = (e - s).days + 1
        dates = [s + timedelta(days=i) for i in range(days)]
        w = np.array([_seasonal_weight(d) for d in dates])
        w /= w.sum()
        seasonal_weights_cache[cid] = (dates, w)

    dates, w = seasonal_weights_cache[cid]
    return dates[rng.choice(len(dates), p=w)]


def _random_timestamp(cam, cfg, rng):
    """Generate timestamp with species-appropriate time-of-day pattern."""
    d = _random_date(cam, rng)

    # Feral hog lunar avoidance: 40% chance of skipping bright moon nights
    if cfg.get("lunar_avoidance") and d in BRIGHT_NIGHTS:
        if rng.random() < 0.4:
            d = _random_date(cam, rng)

    hour_probs = TEMPORAL[cfg["temporal"]]
    hour = int(rng.choice(24, p=hour_probs))
    minute = int(rng.integers(0, 60))
    second = int(rng.integers(0, 60))

    return datetime(d.year, d.month, d.day, hour, minute, second)


def _compute_entropy(confidence, rng):
    """Approximate softmax entropy. Calibrated for ~8% review rate at 0.5 nats."""
    base = 2.05 * (1.0 - confidence)
    noise = float(rng.exponential(0.085))
    return max(0.0, base + noise)


# ═══════════════════════════════════════════════════════════════════════════
# Detection Generator
# ═══════════════════════════════════════════════════════════════════════════

def generate_detections(rng):
    """Generate ~12K raw photo-level detections with burst/event grouping."""
    all_detections = []
    event_counter = 0

    for species_key, cfg in SPECIES.items():
        target_ratio = cfg["photos"] / cfg["events"]  # mean burst size
        selected = _select_cameras(cfg, rng)
        distribution = _distribute_events(selected, cfg, rng)

        for cam, n_events in distribution:
            for _ in range(int(n_events)):
                event_counter += 1
                event_time = _random_timestamp(cam, cfg, rng)

                # Burst size from Poisson matching target photo:event ratio
                burst_size = int(min(8, max(1, rng.poisson(target_ratio - 1) + 1)))

                burst_id = f"BG-{cam['camera_id']}-{event_time:%Y%m%d%H%M%S}"
                event_id = f"IE-{species_key}-{event_counter:06d}"

                for photo_idx in range(burst_size):
                    # Photos within burst spread across 0-59 seconds
                    offset = int(rng.integers(0, 60)) if photo_idx > 0 else 0
                    photo_time = event_time + timedelta(seconds=offset)

                    # Confidence score (truncated normal)
                    conf = float(np.clip(
                        rng.normal(cfg["conf_mean"], cfg["conf_std"]), 0.72, 0.99))
                    conf = round(conf, 4)

                    # Temperature-scaled calibrated confidence (~7% reduction)
                    conf_cal = round(conf * 0.93, 4)

                    # MegaDetector confidence
                    md_conf = round(float(np.clip(
                        rng.normal(0.94, 0.03), 0.80, 0.99)), 4)

                    # Entropy → review flag
                    entropy = _compute_entropy(conf, rng)
                    review = entropy > 0.5

                    det = dict(
                        camera_id=cam["camera_id"],
                        species_key=species_key,
                        confidence=conf,
                        confidence_calibrated=conf_cal,
                        timestamp=photo_time.isoformat(),
                        image_filename=(f"{cam['camera_id']}_"
                                        f"{photo_time:%Y%m%d_%H%M%S}_"
                                        f"{photo_idx:02d}.jpg"),
                        megadetector_confidence=md_conf,
                        burst_group_id=burst_id,
                        independent_event_id=event_id,
                        review_required=review,
                    )

                    # Deer antler classification: buck 35%, doe 65%
                    # Suppressed Dec-Apr (antler shed season)
                    if species_key == "white_tailed_deer":
                        m = photo_time.month
                        if m in (5, 6, 7, 8, 9, 10, 11):
                            det["antler_classification"] = (
                                "buck" if rng.random() < 0.35 else "doe")
                        else:
                            det["antler_classification"] = None

                    all_detections.append(det)

    return all_detections


# ═══════════════════════════════════════════════════════════════════════════
# Species Confidence + Bias Correction
# ═══════════════════════════════════════════════════════════════════════════

def _confidence_grade(pct):
    """Letter grade from overall confidence percentage."""
    if pct >= 90: return "A"
    if pct >= 80: return "A-"
    if pct >= 70: return "B+"
    if pct >= 60: return "B"
    if pct >= 50: return "B-"
    if pct >= 40: return "C+"
    if pct >= 30: return "C"
    if pct >= 20: return "C-"
    if pct >= 10: return "D"
    return "F"


def compute_species_confidence(detections):
    """Compute per-habitat-unit species confidence with bias correction.

    Demonstrates that feeder cameras inflate detection rates for hogs
    and raccoons — the raw vs corrected frequencies make the bias visible.
    """
    # Map cameras to habitat units
    hu_cam_ids = {}
    cam_contexts = {}
    for cam in CAMERAS:
        hu = cam["habitat_unit_id"]
        hu_cam_ids.setdefault(hu, set()).add(cam["camera_id"])
        cam_contexts[cam["camera_id"]] = cam["placement_context"]

    # Aggregate detections by HU + species
    hu_species = {}  # (hu_id, species) → {events, cameras, confs}
    for det in detections:
        cam_id = det["camera_id"]
        # Find which HU this camera belongs to
        for hu_id, cids in hu_cam_ids.items():
            if cam_id in cids:
                key = (hu_id, det["species_key"])
                rec = hu_species.setdefault(key, dict(
                    events=set(), cameras=set(), confs=[]))
                rec["events"].add(det["independent_event_id"])
                rec["cameras"].add(cam_id)
                rec["confs"].append(det["confidence"])
                break

    # Species that show feeder-driven bias
    feeder_biased = {"feral_hog", "raccoon", "opossum"}

    records = []
    for (hu_id, species_key), agg in hu_species.items():
        cameras_total = len(hu_cam_ids[hu_id])
        cameras_detected = len(agg["cameras"])
        total_events = len(agg["events"])
        mean_conf = sum(agg["confs"]) / len(agg["confs"]) * 100

        raw_freq = cameras_detected / cameras_total * 100

        # Bias correction via simplified IPW
        # Feeder cameras in this HU get downweighted for feeder-biased species
        if species_key in feeder_biased:
            feeder_cams_detected = sum(
                1 for c in agg["cameras"]
                if cam_contexts.get(c) == "feeder")
            # IPW: feeder detections weighted at 1/3 (Kolowski inflation ~3x)
            adjusted = cameras_detected - feeder_cams_detected * (2.0 / 3.0)
            corrected_freq = max(5.0, adjusted / cameras_total * 100)
            bias_applied = True
        else:
            corrected_freq = raw_freq
            bias_applied = False

        # Corridor coverage (simplified: proportion of monitoring density)
        corridor_cov = min(100.0, total_events / max(cameras_total, 1) * 15)

        # Overall confidence: weighted composite
        overall = (0.40 * corrected_freq
                   + 0.30 * mean_conf
                   + 0.20 * corridor_cov
                   + 0.10 * min(100.0, total_events * 0.5))
        overall = min(100.0, overall)

        records.append(dict(
            habitat_unit_id=hu_id,
            species_key=species_key,
            total_detections=total_events,
            cameras_detected=cameras_detected,
            cameras_total=cameras_total,
            detection_frequency_pct=round(corrected_freq, 1),
            raw_detection_frequency_pct=round(raw_freq, 1),
            bias_correction_applied=bias_applied,
            classification_confidence_pct=round(mean_conf, 1),
            corridor_coverage_pct=round(corridor_cov, 1),
            overall_confidence_pct=round(overall, 1),
            confidence_grade=_confidence_grade(overall),
            monitoring_start="2025-03-01",
            monitoring_end="2026-01-31",
            monitoring_months=11,
        ))

    return records


# ═══════════════════════════════════════════════════════════════════════════
# File Output
# ═══════════════════════════════════════════════════════════════════════════

def _parcel_geojson():
    """Build GeoJSON FeatureCollection for the demo parcel."""
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "parcel_id": PARCEL_ID,
                "acreage": PARCEL_ACREAGE,
                "county": PARCEL_COUNTY,
                "state": PARCEL_STATE,
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [PARCEL_RING],
            },
        }],
    }


def write_files(cameras, detections, parcel_geojson):
    """Write JSON/GeoJSON to demo/demo_data/."""
    data_dir = Path(__file__).parent / "demo_data"
    data_dir.mkdir(exist_ok=True)

    with open(data_dir / "cameras.json", "w") as f:
        json.dump(cameras, f, indent=2, default=str)

    with open(data_dir / "detections.json", "w") as f:
        json.dump(detections, f, indent=2, default=str)

    with open(data_dir / "parcel.geojson", "w") as f:
        json.dump(parcel_geojson, f, indent=2)

    print(f"Files written to {data_dir}/")


# ═══════════════════════════════════════════════════════════════════════════
# Database Insertion
# ═══════════════════════════════════════════════════════════════════════════

def seed_to_db(data):
    """Insert all generated data into PostGIS."""
    from db.connection import get_connection, release_connection

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # ── Camera stations ──
            for cam in data["cameras"]:
                cur.execute("""
                    INSERT INTO camera_stations
                        (camera_id, user_id, geom, habitat_unit_id,
                         placement_context, installed_date, last_active,
                         camera_model)
                    VALUES (%s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            %s, %s, %s, %s, %s)
                    ON CONFLICT (camera_id) DO NOTHING
                """, (cam["camera_id"], cam["user_id"],
                      cam["lon"], cam["lat"],
                      cam["habitat_unit_id"], cam["placement_context"],
                      cam["installed_date"], cam["last_active"],
                      cam["camera_model"]))

            # ── Habitat fingerprints ──
            for cam in data["cameras"]:
                cur.execute("""
                    INSERT INTO habitat_fingerprints
                        (camera_id, ecoregion_iii_code, ecoregion_iii_name,
                         ecoregion_iv_code, ecoregion_iv_name,
                         nlcd_code, nlcd_class, huc10, huc10_name,
                         elevation_m, slope_degrees, distance_to_water_m,
                         stream_order, soil_type, canopy_cover_pct)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (cam["camera_id"],
                      ECO_III[0], ECO_III[1], ECO_IV[0], ECO_IV[1],
                      cam["nlcd_code"], cam["nlcd_class"],
                      HUC10[0], HUC10[1],
                      cam["elevation_m"], cam["slope_degrees"],
                      cam["distance_to_water_m"], cam["stream_order"],
                      cam["soil_type"], cam["canopy_cover_pct"]))

            # ── Habitat units ──
            for hu in data["habitat_units"]:
                cur.execute("""
                    INSERT INTO habitat_units
                        (id, huc10, huc10_name,
                         ecoregion_iv_code, ecoregion_iv_name,
                         ecoregion_iii_code, ecoregion_iii_name,
                         nlcd_code, nlcd_class, area_km2, geom)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                            ST_GeomFromText(%s, 4326))
                    ON CONFLICT (id) DO NOTHING
                """, (hu["id"], hu["huc10"], hu["huc10_name"],
                      hu["ecoregion_iv_code"], hu["ecoregion_iv_name"],
                      hu["ecoregion_iii_code"], hu["ecoregion_iii_name"],
                      hu["nlcd_code"], hu["nlcd_class"], hu["area_km2"],
                      hu["geom_wkt"]))

            # ── Corridors ──
            for corr in data["corridors"]:
                cur.execute("""
                    INSERT INTO corridors
                        (habitat_unit_id, corridor_type, length_km, geom)
                    VALUES (%s, %s, %s, ST_GeomFromText(%s, 4326))
                """, (corr["habitat_unit_id"], corr["corridor_type"],
                      corr["length_km"], corr["geom_wkt"]))

            # ── Detections (bulk) ──
            from psycopg2.extras import execute_values
            det_rows = [
                (d["camera_id"], d["species_key"], d["confidence"],
                 d["confidence_calibrated"], d["timestamp"],
                 d["image_filename"], d["megadetector_confidence"],
                 d["burst_group_id"], d["independent_event_id"],
                 d["review_required"])
                for d in data["detections"]
            ]
            execute_values(cur, """
                INSERT INTO detections
                    (camera_id, species_key, confidence,
                     confidence_calibrated, timestamp,
                     image_filename, megadetector_confidence,
                     burst_group_id, independent_event_id,
                     review_required)
                VALUES %s
            """, det_rows, page_size=1000)

            # ── Species confidence ──
            for sc in data["species_confidence"]:
                cur.execute("""
                    INSERT INTO species_confidence
                        (habitat_unit_id, species_key, total_detections,
                         cameras_detected, cameras_total,
                         detection_frequency_pct, raw_detection_frequency_pct,
                         bias_correction_applied,
                         classification_confidence_pct, corridor_coverage_pct,
                         overall_confidence_pct, confidence_grade,
                         monitoring_start, monitoring_end, monitoring_months)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (habitat_unit_id, species_key) DO NOTHING
                """, (sc["habitat_unit_id"], sc["species_key"],
                      sc["total_detections"], sc["cameras_detected"],
                      sc["cameras_total"], sc["detection_frequency_pct"],
                      sc["raw_detection_frequency_pct"],
                      sc["bias_correction_applied"],
                      sc["classification_confidence_pct"],
                      sc["corridor_coverage_pct"],
                      sc["overall_confidence_pct"], sc["confidence_grade"],
                      sc["monitoring_start"], sc["monitoring_end"],
                      sc["monitoring_months"]))

            # ── Risk assessment (parcel) ──
            parcel_wkt = ("POLYGON((" +
                          ",".join(f"{lon} {lat}" for lon, lat in PARCEL_RING) +
                          "))")
            risk_json = {
                "parcel_id": PARCEL_ID,
                "species_detected": len(SPECIES),
                "invasive_species": [k for k, v in SPECIES.items()
                                     if k in ("feral_hog", "axis_deer")],
                "total_independent_events": sum(
                    s["events"] for s in SPECIES.values()),
                "monitoring_period": {
                    "start": "2025-03-01", "end": "2026-01-31"},
                "cameras": len(CAMERAS),
            }
            cur.execute("""
                INSERT INTO risk_assessments
                    (parcel_id, parcel_boundary, acreage, county, state,
                     assessment_date, risk_json)
                VALUES (%s, ST_GeomFromText(%s, 4326),
                        %s, %s, %s, %s, %s)
                ON CONFLICT (parcel_id) DO NOTHING
            """, (PARCEL_ID, parcel_wkt, PARCEL_ACREAGE,
                  PARCEL_COUNTY, PARCEL_STATE, "2026-01-31",
                  json.dumps(risk_json)))

        conn.commit()
        n = len(data["detections"])
        print(f"Inserted {n:,} detections, {len(CAMERAS)} cameras, "
              f"{len(HABITAT_UNITS)} habitat units, {len(CORRIDORS)} corridors "
              f"into PostGIS.")
    except Exception as e:
        conn.rollback()
        raise
    finally:
        release_connection(conn)


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

def generate():
    """Generate all Edwards Plateau demo data. Returns full data dict."""
    rng = np.random.default_rng(SEED)

    print("Generating detections...")
    detections = generate_detections(rng)

    print("Computing species confidence & bias correction...")
    species_confidence = compute_species_confidence(detections)

    parcel = _parcel_geojson()

    data = dict(
        cameras=CAMERAS,
        detections=detections,
        habitat_units=HABITAT_UNITS,
        corridors=CORRIDORS,
        species_confidence=species_confidence,
        parcel=parcel,
    )

    write_files(CAMERAS, detections, parcel)
    _print_summary(detections, species_confidence)
    return data


def _print_summary(detections, species_confidence):
    """Print summary statistics for verification."""
    n_photos = len(detections)
    n_events = len(set(d["independent_event_id"] for d in detections))
    n_review = sum(1 for d in detections if d["review_required"])

    # Camera-nights
    total_nights = 0
    for cam in CAMERAS:
        s, e = _camera_active_range(cam)
        total_nights += (e - s).days + 1

    print(f"\n{'=' * 70}")
    print(f"Edwards Plateau Demo — {PARCEL_ACREAGE} acres, {PARCEL_COUNTY} County TX")
    print(f"{'=' * 70}")
    print(f"Cameras:        {len(CAMERAS)}")
    print(f"Camera-nights:  {total_nights:,}")
    print(f"Raw photos:     {n_photos:,}")
    print(f"Indep. events:  {n_events:,}")
    print(f"Photo:event:    {n_photos/n_events:.2f}:1")
    print(f"Review flagged: {n_review:,} ({n_review/n_photos*100:.1f}%)")
    print(f"\n{'Species':<25s} {'Photos':>7s} {'Events':>7s} {'Cams':>5s} "
          f"{'Ratio':>6s} {'ConfMean':>8s}")
    print("-" * 62)

    for sp in SPECIES:
        sp_dets = [d for d in detections if d["species_key"] == sp]
        sp_photos = len(sp_dets)
        sp_events = len(set(d["independent_event_id"] for d in sp_dets))
        sp_cams = len(set(d["camera_id"] for d in sp_dets))
        sp_conf = sum(d["confidence"] for d in sp_dets) / max(sp_photos, 1)
        ratio = sp_photos / max(sp_events, 1)
        print(f"  {sp:<23s} {sp_photos:>7,d} {sp_events:>7,d} {sp_cams:>5d} "
              f"{ratio:>6.2f} {sp_conf:>8.3f}")

    # Bias correction demonstration
    print(f"\n{'Bias Correction Demo':}")
    print(f"{'HU / Species':<45s} {'Raw%':>6s} {'Corr%':>6s} {'Δ':>6s}")
    print("-" * 65)
    for sc in sorted(species_confidence,
                     key=lambda x: (x["habitat_unit_id"], x["species_key"])):
        if sc["bias_correction_applied"]:
            delta = sc["raw_detection_frequency_pct"] - sc["detection_frequency_pct"]
            print(f"  {sc['habitat_unit_id'][-2:]}/{sc['species_key']:<35s} "
                  f"{sc['raw_detection_frequency_pct']:>6.1f} "
                  f"{sc['detection_frequency_pct']:>6.1f} "
                  f"{delta:>+5.1f}")


if __name__ == "__main__":
    generate()
