"""Seed Strecker-side neighboring-lease cameras for the DetectionIngest bridge.

Creates the "data from hunter cameras on adjacent property" signal that the
Nature Exposure Report shows as supplementary coverage under "Coverage
sources". Per the strategic spec: no visible Strecker↔Basal connection in
the UI; the bridge surfaces the data under a neutral "neighboring cameras"
label with proximity-confidence scoring.

Model:
  - One Strecker user ("ballenger@example.com" — hypothetical hunting-lease
    member) owns "North Ridge Hunting Lease".
  - That lease is a property adjacent to Edwards Plateau Ranch (id=1).
    NOT assigned to any LenderClient (Strecker-side, no lender).
  - Two cameras on that lease, positioned ~0.6 km and ~1.4 km from the
    Edwards Plateau boundary.
  - Detection data spans the same Spring 2026 window.

Idempotent: removes any prior hunter user with the synthetic email + their
property + cascade before re-seeding.

Usage:
    docker exec strecker-worker python3 /app/demo/seed/seed_strecker_neighbors.py
"""
import json, os, sys
from datetime import datetime, date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from config import settings
import psycopg2


HUNTER_EMAIL = "ballenger@example.com"
HUNTER_NAME = "Ballenger Hunting Partners"

# North-adjacent lease. Edwards Plateau Ranch polygon is
# (-99.77 .. -99.69, 30.46 .. 30.53). This lease sits just north,
# 30.535–30.57 latitude, overlapping in longitude.
LEASE_PROPERTY = {
    "name": "North Ridge Hunting Lease",
    "county": "Kimble", "state": "TX",
    "acreage": 1200, "crop_type": None,  # no crop — it's just hunting land
    "boundary": [
        [-99.74, 30.535], [-99.74, 30.570],
        [-99.68, 30.570], [-99.68, 30.535],
        [-99.74, 30.535],
    ],
}

SEASON = {
    "name": "Spring 2026",
    "start": date(2026, 2, 1), "end": date(2026, 3, 31),
}


def hourly(*slots):
    out = [0] * 24
    for start, end, w in slots:
        for h in range(start, end):
            out[h % 24] += w
    return out


# Cameras positioned to straddle the proximity window:
#   - CAM-NR-EAST: ~0.6 km from Edwards Plateau north boundary (high confidence)
#   - CAM-NR-WEST: ~1.4 km further north (lower confidence but in range)
CAMERAS = [
    {
        "label": "CAM-NR-EAST",
        "name": "North Ridge east fenceline",
        "lat": 30.541, "lon": -99.712,  # ~0.6 km N of Edwards Plateau N edge (30.53)
        "placement_context": "trail",
        "camera_model": "Reconyx HP2X",
        "installed_date": date(2026, 1, 22),
        "species": {
            "feral_hog": {
                "photos": 62, "events": 18, "conf": 0.88,
                "hourly": hourly((20, 24, 4), (0, 5, 4)),
                "first_seen": datetime(2026, 2, 6, 22, 18, 11),
                "last_seen":  datetime(2026, 3, 29, 3, 47, 28),
            },
            "white_tailed_deer": {
                "photos": 94, "events": 31, "conf": 0.91,
                "buck": 29, "doe": 65,
                "hourly": hourly((5, 9, 3), (17, 21, 4)),
                "first_seen": datetime(2026, 2, 4, 6, 41, 33),
                "last_seen":  datetime(2026, 3, 30, 19, 8, 44),
            },
        },
    },
    {
        "label": "CAM-NR-WEST",
        "name": "North Ridge creek bottom",
        "lat": 30.556, "lon": -99.725,  # ~1.4 km N of Edwards Plateau N edge
        "placement_context": "water",
        "camera_model": "Bushnell Core DS",
        "installed_date": date(2026, 1, 22),
        "species": {
            "feral_hog": {
                "photos": 29, "events": 8, "conf": 0.85,
                "hourly": hourly((21, 24, 3), (0, 4, 3)),
                "first_seen": datetime(2026, 2, 12, 22, 55, 3),
                "last_seen":  datetime(2026, 3, 26, 2, 31, 19),
            },
            "coyote": {
                "photos": 19, "events": 11, "conf": 0.86,
                "hourly": hourly((20, 24, 2), (0, 5, 2)),
                "first_seen": datetime(2026, 2, 9, 22, 17, 44),
                "last_seen":  datetime(2026, 3, 28, 4, 22, 18),
            },
        },
    },
]


def main():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    # Idempotent cleanup: remove prior hunter user + cascade.
    cur.execute("SELECT id FROM users WHERE email=%s", (HUNTER_EMAIL,))
    prior = cur.fetchone()
    if prior:
        uid = prior[0]
        # FK-safe order mirroring seed_lender_portfolio.py
        cur.execute("""
            DELETE FROM detection_summaries WHERE season_id IN
                (SELECT id FROM seasons WHERE property_id IN
                    (SELECT id FROM properties WHERE user_id=%s))
        """, (uid,))
        cur.execute("""
            DELETE FROM detection_summaries WHERE camera_id IN
                (SELECT id FROM cameras WHERE property_id IN
                    (SELECT id FROM properties WHERE user_id=%s))
        """, (uid,))
        cur.execute("DELETE FROM coverage_scores WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM share_cards WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM processing_jobs WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM uploads WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM seasons WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM cameras WHERE property_id IN (SELECT id FROM properties WHERE user_id=%s)", (uid,))
        cur.execute("DELETE FROM properties WHERE user_id=%s", (uid,))
        cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        print(f"  cleaned prior hunter user id={uid} and cascade")

    cur.execute("""
        INSERT INTO users (email, password_hash, display_name, created_at, updated_at)
        VALUES (%s, %s, %s, NOW(), NOW())
        RETURNING id
    """, (HUNTER_EMAIL, "!unset!", HUNTER_NAME))
    hunter_id = cur.fetchone()[0]
    print(f"Created hunter user id={hunter_id} ({HUNTER_NAME})")

    boundary_geojson = json.dumps({
        "type": "Feature",
        "properties": {"name": LEASE_PROPERTY["name"]},
        "geometry": {"type": "Polygon",
                     "coordinates": [LEASE_PROPERTY["boundary"]]},
    })
    cur.execute("""
        INSERT INTO properties (user_id, name, county, state, acreage,
                                boundary_geojson, lender_client_id,
                                crop_type, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, NOW(), NOW())
        RETURNING id
    """, (hunter_id, LEASE_PROPERTY["name"], LEASE_PROPERTY["county"],
          LEASE_PROPERTY["state"], LEASE_PROPERTY["acreage"],
          boundary_geojson, LEASE_PROPERTY["crop_type"]))
    lease_id = cur.fetchone()[0]
    print(f"Created lease property id={lease_id} ({LEASE_PROPERTY['name']}) — Strecker-only, no lender")

    cur.execute("""
        INSERT INTO seasons (property_id, name, start_date, end_date, created_at)
        VALUES (%s, %s, %s, %s, NOW()) RETURNING id
    """, (lease_id, SEASON["name"], SEASON["start"], SEASON["end"]))
    season_id = cur.fetchone()[0]

    for cam in CAMERAS:
        cur.execute("""
            INSERT INTO cameras (property_id, camera_label, name, lat, lon,
                                 placement_context, camera_model, installed_date,
                                 is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
            RETURNING id
        """, (lease_id, cam["label"], cam["name"], cam["lat"], cam["lon"],
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
        sp_list = ", ".join(cam["species"].keys())
        print(f"  Camera {cam['label']} ({cam['lat']}, {cam['lon']}) — {sp_list}")

    conn.commit()
    cur.close(); conn.close()

    print()
    print("=" * 64)
    print(f"Strecker neighbor seed complete.")
    print(f"  North Ridge Hunting Lease: 1200ac, Kimble Co, TX")
    print(f"  2 cameras positioned 0.6-1.4 km N of Edwards Plateau Ranch boundary")
    print(f"  Visible as Supplementary coverage on /lender/fcct/parcel/1")
    print("=" * 64)


if __name__ == "__main__":
    main()
