"""Direct-SQL demo seeder for Edwards Plateau Ranch.

Generates realistic 6-week monitoring data for a Texas Hill Country ranch:
- 3 camera stations at different placement contexts (feeder, feeder, trail)
- 4 species: feral hog, white-tailed deer, raccoon, coyote
- Density profiles reflect actual hog-agriculture literature:
    hogs concentrated at feeders, deer mixed, predators on trails
- Independent-event counts assume 30-min independence window
- Hourly distributions encode realistic activity windows per species

No ML, no Spaces, no ingest pipeline — just SQL INSERTs that populate
the same tables the real pipeline would. Lets the dashboard render
demo-quality numbers while the worker Droplet is upsized for live ML.

Idempotent: re-running wipes prior demo data for this property and
re-seeds. Safe to invoke repeatedly (e.g., from a deploy hook).

Usage (from inside the worker container, which has DATABASE_URL etc):
    docker exec strecker-worker python3 /app/demo/seed/seed_dashboard.py

Or from a local shell with .env loaded:
    python3 demo/seed/seed_dashboard.py
"""
import json, os, sys
from datetime import datetime, date

# Make imports from the repo work regardless of where we run.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from config import settings
import psycopg2

PROPERTY_ID = 1
SEASON_NAME = "Spring 2026"
SEASON_START = date(2026, 2, 1)
SEASON_END = date(2026, 3, 31)

PROPERTY_NAME = "Edwards Plateau Ranch"
PROPERTY_COUNTY = "Kimble"
PROPERTY_STATE = "TX"
PROPERTY_ACREAGE = 2340.0
PROPERTY_BOUNDARY = json.dumps({
    "type": "Feature",
    "properties": {"name": PROPERTY_NAME},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-99.77, 30.46], [-99.77, 30.53],
            [-99.69, 30.53], [-99.69, 30.46],
            [-99.77, 30.46],
        ]],
    },
})


def hourly(*slots):
    """Build 24-hour distribution from (start, end, weight) triples."""
    out = [0] * 24
    for start, end, w in slots:
        for h in range(start, end):
            out[h % 24] += w
    return out


# 3 camera stations with realistic species mix + activity windows.
CAMERAS = [
    {
        "label": "CAM-NORTH-FEEDER",
        "name": "North food plot",
        "lat": 30.512, "lon": -99.744,
        "placement_context": "feeder",
        "camera_model": "Reconyx HP2X",
        "installed_date": date(2026, 1, 15),
        "species": {
            "white_tailed_deer": {
                "photos": 142, "events": 38, "conf": 0.93,
                "buck": 48, "doe": 94,
                "hourly": hourly((5, 9, 3), (17, 21, 4), (9, 17, 1)),
                "first_seen": datetime(2026, 2, 3, 6, 14, 22),
                "last_seen":  datetime(2026, 3, 29, 19, 41, 8),
            },
            "feral_hog": {
                "photos": 38, "events": 9, "conf": 0.87,
                "hourly": hourly((20, 24, 4), (0, 5, 4), (5, 20, 0)),
                "first_seen": datetime(2026, 2, 11, 22, 18, 4),
                "last_seen":  datetime(2026, 3, 27, 3, 55, 31),
            },
            "raccoon": {
                "photos": 24, "events": 11, "conf": 0.91,
                "hourly": hourly((20, 24, 3), (0, 4, 3), (4, 20, 0)),
                "first_seen": datetime(2026, 2, 8, 21, 30, 12),
                "last_seen":  datetime(2026, 3, 30, 2, 45, 57),
            },
        },
    },
    {
        "label": "CAM-SOUTH-FEEDER",
        "name": "South feeder (heavy hog pressure)",
        "lat": 30.482, "lon": -99.751,
        "placement_context": "feeder",
        "camera_model": "Reconyx HP2X",
        "installed_date": date(2026, 1, 15),
        "species": {
            "feral_hog": {
                "photos": 186, "events": 52, "conf": 0.91,
                "hourly": hourly((20, 24, 5), (0, 6, 5), (6, 20, 0)),
                "first_seen": datetime(2026, 2, 2, 22, 3, 18),
                "last_seen":  datetime(2026, 3, 31, 4, 8, 44),
            },
            "white_tailed_deer": {
                "photos": 44, "events": 12, "conf": 0.89,
                "buck": 8, "doe": 36,
                "hourly": hourly((6, 9, 3), (18, 21, 3)),
                "first_seen": datetime(2026, 2, 14, 7, 12, 0),
                "last_seen":  datetime(2026, 3, 24, 19, 33, 21),
            },
            "raccoon": {
                "photos": 19, "events": 8, "conf": 0.88,
                "hourly": hourly((21, 24, 3), (0, 3, 3)),
                "first_seen": datetime(2026, 2, 10, 23, 1, 17),
                "last_seen":  datetime(2026, 3, 28, 1, 22, 9),
            },
        },
    },
    {
        "label": "CAM-CREEK-CROSSING",
        "name": "Creek crossing (wildlife corridor)",
        "lat": 30.497, "lon": -99.723,
        "placement_context": "trail",
        "camera_model": "Bushnell Core DS",
        "installed_date": date(2026, 1, 15),
        "species": {
            "white_tailed_deer": {
                "photos": 67, "events": 22, "conf": 0.90,
                "buck": 19, "doe": 48,
                "hourly": hourly((5, 10, 2), (17, 21, 3)),
                "first_seen": datetime(2026, 2, 5, 6, 33, 41),
                "last_seen":  datetime(2026, 3, 30, 19, 12, 55),
            },
            "coyote": {
                "photos": 21, "events": 14, "conf": 0.86,
                "hourly": hourly((19, 24, 2), (0, 6, 2)),
                "first_seen": datetime(2026, 2, 8, 22, 44, 3),
                "last_seen":  datetime(2026, 3, 29, 4, 17, 22),
            },
            "feral_hog": {
                "photos": 31, "events": 8, "conf": 0.84,
                "hourly": hourly((21, 24, 3), (0, 5, 3)),
                "first_seen": datetime(2026, 2, 19, 23, 51, 12),
                "last_seen":  datetime(2026, 3, 26, 2, 33, 48),
            },
            "raccoon": {
                "photos": 12, "events": 7, "conf": 0.89,
                "hourly": hourly((22, 24, 2), (0, 4, 2)),
                "first_seen": datetime(2026, 2, 12, 23, 20, 31),
                "last_seen":  datetime(2026, 3, 29, 3, 14, 18),
            },
        },
    },
]


def main():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Rename + reshape the property row
    cur.execute("""
        UPDATE properties
        SET name=%s, county=%s, state=%s, acreage=%s, boundary_geojson=%s,
            updated_at=NOW()
        WHERE id=%s
    """, (PROPERTY_NAME, PROPERTY_COUNTY, PROPERTY_STATE, PROPERTY_ACREAGE,
          PROPERTY_BOUNDARY, PROPERTY_ID))
    if cur.rowcount == 0:
        raise SystemExit(f"No property with id={PROPERTY_ID}; "
                         "make sure the property exists before seeding.")
    print(f"Updated property id={PROPERTY_ID} -> {PROPERTY_NAME}")

    # 2. FK-safe cleanup of prior data (idempotent re-seed)
    cleanups = [
        ("coverage_scores", "DELETE FROM coverage_scores WHERE property_id=%s"),
        ("share_cards", "DELETE FROM share_cards WHERE property_id=%s"),
        ("detection_summaries (via seasons)",
         "DELETE FROM detection_summaries WHERE season_id IN (SELECT id FROM seasons WHERE property_id=%s)"),
        ("detection_summaries (via cameras)",
         "DELETE FROM detection_summaries WHERE camera_id IN (SELECT id FROM cameras WHERE property_id=%s)"),
        ("processing_jobs", "DELETE FROM processing_jobs WHERE property_id=%s"),
        ("uploads", "DELETE FROM uploads WHERE property_id=%s"),
        ("seasons", "DELETE FROM seasons WHERE property_id=%s"),
        ("cameras", "DELETE FROM cameras WHERE property_id=%s"),
    ]
    for label, sql in cleanups:
        cur.execute(sql, (PROPERTY_ID,))
        if cur.rowcount:
            print(f"  cleaned {cur.rowcount} prior {label}")

    # 3. Season
    cur.execute("""
        INSERT INTO seasons (property_id, name, start_date, end_date, created_at)
        VALUES (%s, %s, %s, %s, NOW()) RETURNING id
    """, (PROPERTY_ID, SEASON_NAME, SEASON_START, SEASON_END))
    season_id = cur.fetchone()[0]
    print(f"  created season id={season_id} ({SEASON_NAME})")

    # 4. Cameras + detection summaries
    tot_photos = 0
    tot_events = 0
    species_totals = {}
    for cam in CAMERAS:
        cur.execute("""
            INSERT INTO cameras (property_id, camera_label, name, lat, lon,
                                 placement_context, camera_model, installed_date,
                                 is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            RETURNING id
        """, (PROPERTY_ID, cam["label"], cam["name"], cam["lat"], cam["lon"],
              cam["placement_context"], cam["camera_model"], cam["installed_date"]))
        cam_id = cur.fetchone()[0]

        for species_key, stats in cam["species"].items():
            h24 = stats["hourly"]
            peak = h24.index(max(h24)) if max(h24) > 0 else None
            cur.execute("""
                INSERT INTO detection_summaries
                    (season_id, camera_id, species_key,
                     total_photos, independent_events, avg_confidence,
                     first_seen, last_seen, buck_count, doe_count,
                     peak_hour, hourly_distribution, created_at)
                VALUES (%s,%s,%s, %s,%s,%s, %s,%s, %s,%s, %s,%s, NOW())
            """, (season_id, cam_id, species_key,
                  stats["photos"], stats["events"], stats["conf"],
                  stats["first_seen"], stats["last_seen"],
                  stats.get("buck", 0), stats.get("doe", 0),
                  peak, json.dumps(h24)))
            tot_photos += stats["photos"]
            tot_events += stats["events"]
            species_totals[species_key] = species_totals.get(species_key, 0) + stats["photos"]

        label = cam.get("label", "?")
        nsp = len(cam.get("species", {}))
        print(f"  camera {label}: {nsp} species")

    conn.commit()
    cur.close(); conn.close()

    print()
    print("=" * 64)
    print(f"SEEDED: {PROPERTY_NAME} ({PROPERTY_ACREAGE:,.0f} acres, {PROPERTY_COUNTY} Co, {PROPERTY_STATE})")
    print(f"  Season:        {SEASON_NAME} ({SEASON_START} - {SEASON_END})")
    print(f"  Cameras:       {len(CAMERAS)}")
    print(f"  Photos:        {tot_photos:,}")
    print(f"  Events:        {tot_events:,} (30-min independence window)")
    print(f"  Species:       {len(species_totals)}")
    for sp, cnt in sorted(species_totals.items(), key=lambda x: -x[1]):
        print(f"    {sp:<25} {cnt:>5} photos")
    print("=" * 64)


if __name__ == "__main__":
    main()
