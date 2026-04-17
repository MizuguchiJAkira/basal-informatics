"""Seed a full lender portfolio: Farm Credit of Central Texas with 5 parcels
spanning the exposure-tier range. Drives the YC-partner demo.

Parcels (by intent):
  1. Edwards Plateau Ranch      2,340 ac sorghum   Elevated  (existing, rewired)
  2. Riverbend Farm               650 ac corn      Severe    (new)
  3. Highland Meadow Ranch      4,800 ac pasture   Low       (new)
  4. Oak Ridge Orchards           180 ac mixed     Moderate  (new)
  5. Prairie Creek Property     3,200 ac rangeland pending   (new, no season)

Also:
  - Elevates jonahakiracheng@gmail.com to is_owner=True so the /lender/
    route auth check passes under DEMO_MODE=0.
  - Creates one owner user per new parcel so realism holds
    (a lender's portfolio spans multiple landowners).

Idempotent: re-running wipes prior lender+portfolio state for FCCT and
re-seeds. Does NOT delete the hunter-only property setup that
seed_dashboard.py builds — parcels 2-5 are net-new.

Usage inside the worker container:
    docker exec strecker-worker python3 /app/demo/seed/seed_lender_portfolio.py

Local:
    DATABASE_URL=... python3 demo/seed/seed_lender_portfolio.py
"""
import json, os, sys
from datetime import datetime, date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from config import settings
import psycopg2
from psycopg2.extras import Json as _PgJson

LENDER = {
    "name": "Farm Credit of Central Texas",
    "slug": "fcct",
    "parent_org": "Farm Credit System",
    "state": "TX",
    "hq_address": "2001 Brazos St, Austin, TX 78702",
    "contact_email": "portfolio@fcct.example.com",
    "plan_tier": "per_parcel",
    "per_parcel_rate_usd": 1500.00,
}

OWNER_EMAIL = "jonahakiracheng@gmail.com"


def hourly(*slots):
    out = [0] * 24
    for start, end, w in slots:
        for h in range(start, end):
            out[h % 24] += w
    return out


# ---------------------------------------------------------------------------
# Additional demo parcels. Each becomes one Property owned by its own User.
# ---------------------------------------------------------------------------

PARCELS = [
    {
        "owner_email": "riverbend@example.com",
        "owner_name":  "Riverbend Farm LLC",
        "property": {
            "name": "Riverbend Farm",
            "county": "Brazos", "state": "TX",
            "acreage": 650, "crop_type": "corn",
            "boundary": [[-96.52,30.57],[-96.52,30.62],[-96.46,30.62],[-96.46,30.57],[-96.52,30.57]],
        },
        "season": {
            "name": "Spring 2026", "start": date(2026, 2, 1), "end": date(2026, 3, 31),
        },
        # Heavy hog pressure on a small corn parcel. Density >10/km² => Severe.
        "cameras": [
            {
                "label": "CAM-RB-CORN-01", "name": "Corn field north edge",
                "lat": 30.595, "lon": -96.505, "placement_context": "food_plot",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 20),
                "species": {
                    "feral_hog": {"photos": 312, "events": 78, "conf": 0.93,
                                  "hourly": hourly((20,24,6),(0,6,6)),
                                  "first_seen": datetime(2026,2,2,22,10,3),
                                  "last_seen":  datetime(2026,3,30,4,2,15)},
                    "white_tailed_deer": {"photos": 28, "events": 9, "conf": 0.88,
                                          "buck": 4, "doe": 24,
                                          "hourly": hourly((6,9,2),(18,21,2)),
                                          "first_seen": datetime(2026,2,8,7,1,14),
                                          "last_seen":  datetime(2026,3,22,19,34,2)},
                },
            },
            {
                "label": "CAM-RB-CORN-02", "name": "Corn field water crossing",
                "lat": 30.584, "lon": -96.495, "placement_context": "water",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 20),
                "species": {
                    "feral_hog": {"photos": 248, "events": 71, "conf": 0.90,
                                  "hourly": hourly((21,24,6),(0,7,6)),
                                  "first_seen": datetime(2026,2,3,23,44,8),
                                  "last_seen":  datetime(2026,3,31,5,12,33)},
                    "raccoon": {"photos": 36, "events": 18, "conf": 0.87,
                                "hourly": hourly((22,24,3),(0,4,3)),
                                "first_seen": datetime(2026,2,9,22,18,41),
                                "last_seen":  datetime(2026,3,28,2,44,22)},
                },
            },
        ],
    },
    {
        "owner_email": "highland@example.com",
        "owner_name":  "Highland Meadow Ranch",
        "property": {
            "name": "Highland Meadow Ranch",
            "county": "Real", "state": "TX",
            "acreage": 4800, "crop_type": "pasture",
            "boundary": [[-99.82,29.86],[-99.82,29.94],[-99.72,29.94],[-99.72,29.86],[-99.82,29.86]],
        },
        "season": {
            "name": "Spring 2026", "start": date(2026, 2, 1), "end": date(2026, 3, 31),
        },
        # Light hog activity on a big pasture parcel. <2/km² => Low.
        "cameras": [
            {
                "label": "CAM-HM-NORTH", "name": "North pasture windmill",
                "lat": 29.915, "lon": -99.799, "placement_context": "water",
                "camera_model": "Bushnell Core DS", "installed_date": date(2026, 1, 18),
                "species": {
                    "white_tailed_deer": {"photos": 185, "events": 52, "conf": 0.92,
                                          "buck": 58, "doe": 127,
                                          "hourly": hourly((5,10,3),(17,21,4)),
                                          "first_seen": datetime(2026,2,4,6,22,0),
                                          "last_seen":  datetime(2026,3,30,19,28,41)},
                    "feral_hog": {"photos": 8, "events": 3, "conf": 0.83,
                                  "hourly": hourly((22,24,2),(0,4,2)),
                                  "first_seen": datetime(2026,2,24,23,11,20),
                                  "last_seen":  datetime(2026,3,19,2,55,5)},
                    "coyote": {"photos": 31, "events": 19, "conf": 0.87,
                               "hourly": hourly((20,24,2),(0,6,2)),
                               "first_seen": datetime(2026,2,6,21,33,11),
                               "last_seen":  datetime(2026,3,27,5,2,17)},
                },
            },
            {
                "label": "CAM-HM-SOUTH", "name": "South pasture gate",
                "lat": 29.872, "lon": -99.745, "placement_context": "random",
                "camera_model": "Bushnell Core DS", "installed_date": date(2026, 1, 18),
                "species": {
                    "white_tailed_deer": {"photos": 122, "events": 38, "conf": 0.90,
                                          "buck": 34, "doe": 88,
                                          "hourly": hourly((6,10,3),(18,21,3)),
                                          "first_seen": datetime(2026,2,7,7,4,12),
                                          "last_seen":  datetime(2026,3,29,19,45,8)},
                    "feral_hog": {"photos": 5, "events": 2, "conf": 0.85,
                                  "hourly": hourly((23,24,1),(0,3,1)),
                                  "first_seen": datetime(2026,3,2,1,22,11),
                                  "last_seen":  datetime(2026,3,25,2,15,44)},
                },
            },
        ],
    },
    {
        "owner_email": "oakridge@example.com",
        "owner_name":  "Oak Ridge Orchards",
        "property": {
            "name": "Oak Ridge Orchards",
            "county": "Gillespie", "state": "TX",
            "acreage": 180, "crop_type": "peanut",  # peanut = high crop modifier
            "boundary": [[-98.99,30.28],[-98.99,30.31],[-98.95,30.31],[-98.95,30.28],[-98.99,30.28]],
        },
        "season": {
            "name": "Spring 2026", "start": date(2026, 2, 1), "end": date(2026, 3, 31),
        },
        # Moderate hog density on a small peanut parcel -> dollar projection
        # scales because of the 1.4x crop modifier even at moderate density.
        "cameras": [
            {
                "label": "CAM-OR-EAST", "name": "East orchard edge",
                "lat": 30.298, "lon": -98.967, "placement_context": "trail",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 19),
                "species": {
                    "feral_hog": {"photos": 47, "events": 15, "conf": 0.89,
                                  "hourly": hourly((20,24,4),(0,5,4)),
                                  "first_seen": datetime(2026,2,5,23,4,22),
                                  "last_seen":  datetime(2026,3,28,3,55,9)},
                    "raccoon": {"photos": 22, "events": 11, "conf": 0.88,
                                "hourly": hourly((21,24,3),(0,4,3)),
                                "first_seen": datetime(2026,2,9,22,18,0),
                                "last_seen":  datetime(2026,3,29,2,22,18)},
                },
            },
        ],
    },
    {
        "owner_email": "prairie@example.com",
        "owner_name":  "Prairie Creek Property",
        "property": {
            "name": "Prairie Creek Property",
            "county": "Menard", "state": "TX",
            "acreage": 3200, "crop_type": "rangeland",
            "boundary": [[-99.83,30.86],[-99.83,30.92],[-99.75,30.92],[-99.75,30.86],[-99.83,30.86]],
        },
        # Intentionally NO season -> parcel shows as "pending" in the portfolio.
        # This gives the demo a narrative beat: "here's one that just signed up,
        # no data in yet, survey in progress."
        "season": None,
        "cameras": [],
    },
]


def main():
    conn = psycopg2.connect(settings.DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()

    # 1. Promote the demo user to owner so /lender/ auth check passes.
    cur.execute("UPDATE users SET is_owner=TRUE WHERE email=%s", (OWNER_EMAIL,))
    print(f"Promoted {OWNER_EMAIL} to is_owner=TRUE (affected: {cur.rowcount})")

    # 2. Upsert the LenderClient.
    cur.execute("""
        INSERT INTO lender_clients
            (name, slug, parent_org, state, hq_address, contact_email,
             plan_tier, per_parcel_rate_usd, active, created_at, updated_at)
        VALUES (%(name)s, %(slug)s, %(parent_org)s, %(state)s, %(hq_address)s,
                %(contact_email)s, %(plan_tier)s, %(per_parcel_rate_usd)s,
                TRUE, NOW(), NOW())
        ON CONFLICT (slug) DO UPDATE
        SET name = EXCLUDED.name,
            parent_org = EXCLUDED.parent_org,
            state = EXCLUDED.state,
            hq_address = EXCLUDED.hq_address,
            contact_email = EXCLUDED.contact_email,
            plan_tier = EXCLUDED.plan_tier,
            per_parcel_rate_usd = EXCLUDED.per_parcel_rate_usd,
            active = TRUE,
            updated_at = NOW()
        RETURNING id
    """, LENDER)
    lender_id = cur.fetchone()[0]
    print(f"Upserted LenderClient id={lender_id} ({LENDER['name']})")

    # 3. Assign existing Edwards Plateau Ranch (id=1) to this lender + set crop.
    cur.execute("""
        UPDATE properties
        SET lender_client_id=%s, crop_type=%s, updated_at=NOW()
        WHERE id=1 AND name='Edwards Plateau Ranch'
    """, (lender_id, "sorghum"))
    if cur.rowcount:
        print(f"  Attached Edwards Plateau Ranch (id=1) to lender, crop=sorghum")

    # 4. Wipe + recreate the net-new parcels idempotently.
    #    They're identified by the synthetic owner emails we created.
    emails = [p["owner_email"] for p in PARCELS]
    cur.execute(
        "SELECT id FROM users WHERE email = ANY(%s)", (emails,))
    existing_user_ids = [r[0] for r in cur.fetchall()]
    if existing_user_ids:
        # Cascade-safe: uploads -> processing_jobs -> detection_summaries ->
        # coverage_scores -> share_cards -> seasons -> cameras -> properties -> users
        cur.execute("""
            DELETE FROM detection_summaries WHERE season_id IN
                (SELECT id FROM seasons WHERE property_id IN
                    (SELECT id FROM properties WHERE user_id = ANY(%s)))
        """, (existing_user_ids,))
        cur.execute("""
            DELETE FROM detection_summaries WHERE camera_id IN
                (SELECT id FROM cameras WHERE property_id IN
                    (SELECT id FROM properties WHERE user_id = ANY(%s)))
        """, (existing_user_ids,))
        cur.execute("DELETE FROM coverage_scores WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM share_cards WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM processing_jobs WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM uploads WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM seasons WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM cameras WHERE property_id IN (SELECT id FROM properties WHERE user_id = ANY(%s))", (existing_user_ids,))
        cur.execute("DELETE FROM properties WHERE user_id = ANY(%s)", (existing_user_ids,))
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (existing_user_ids,))
        print(f"  cleaned {len(existing_user_ids)} prior demo users + cascade")

    # 5. Create the 4 net-new parcels.
    for p in PARCELS:
        owner_email = p["owner_email"]
        owner_name = p["owner_name"]
        prop_data = p["property"]

        # Placeholder user — password never used (reports aren't landowner-login-gated).
        cur.execute("""
            INSERT INTO users (email, password_hash, display_name, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (owner_email, "!unset!", owner_name))
        user_id = cur.fetchone()[0]

        boundary_geojson = json.dumps({
            "type": "Feature",
            "properties": {"name": prop_data["name"]},
            "geometry": {"type": "Polygon", "coordinates": [prop_data["boundary"]]},
        })

        cur.execute("""
            INSERT INTO properties (user_id, name, county, state, acreage,
                                    boundary_geojson, lender_client_id,
                                    crop_type, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (user_id, prop_data["name"], prop_data["county"], prop_data["state"],
              prop_data["acreage"], boundary_geojson, lender_id, prop_data["crop_type"]))
        property_id = cur.fetchone()[0]

        if p["season"] is None:
            print(f"  Created {prop_data['name']} (id={property_id}) — pending (no season)")
            continue

        cur.execute("""
            INSERT INTO seasons (property_id, name, start_date, end_date, created_at)
            VALUES (%s, %s, %s, %s, NOW()) RETURNING id
        """, (property_id, p["season"]["name"], p["season"]["start"], p["season"]["end"]))
        season_id = cur.fetchone()[0]

        for cam in p["cameras"]:
            cur.execute("""
                INSERT INTO cameras (property_id, camera_label, name, lat, lon,
                                     placement_context, camera_model, installed_date,
                                     is_active, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
                RETURNING id
            """, (property_id, cam["label"], cam["name"], cam["lat"], cam["lon"],
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

        print(f"  Created {prop_data['name']} (id={property_id}) "
              f"— {len(p['cameras'])} camera(s), crop={prop_data['crop_type']}")

    conn.commit()

    # Summary
    cur.execute("""
        SELECT p.name, p.acreage, p.crop_type
        FROM properties p WHERE p.lender_client_id=%s
        ORDER BY p.name
    """, (lender_id,))
    portfolio = cur.fetchall()
    cur.close()
    conn.close()

    print()
    print("=" * 64)
    print(f"{LENDER['name']} portfolio: {len(portfolio)} parcels")
    for name, acreage, crop in portfolio:
        print(f"  {name:<32} {acreage:>6.0f} ac   {crop or 'unspec':<12}")
    print("=" * 64)
    print()
    print(f"Visit: /lender/{LENDER['slug']}/")


if __name__ == "__main__":
    main()
