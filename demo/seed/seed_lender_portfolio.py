"""Seed a full lender portfolio: Farm Credit of Central Texas with 5 parcels
spanning the exposure-tier range. Drives the YC-partner demo.

Parcels (by intent — post-IPW tier targets):
  1. Edwards Plateau Ranch      2,340 ac sorghum   Elevated  (existing + 1 random cam added here)
  2. Riverbend Farm               650 ac corn      Severe    (2 biased + 2 random cams)
  3. Highland Meadow Ranch      4,800 ac pasture   Low       (water + random)
  4. Oak Ridge Orchards           180 ac peanut    Moderate  (trail + random)
  5. Prairie Creek Property     3,200 ac rangeland pending   (no season)

Camera deployments include a "random" placement_context anchor on every
non-Pending parcel so the Kolowski 2017 IPW correction has an unbiased
reference. Without this, all-biased deployments deflate ~4-5× under the
literature-prior factor table and tier diversity collapses to Low.

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
        # A prior survey period seeds the continuous-monitoring trend
        # widget on the parcel report. Fall 2025 had Elevated-tier hog
        # pressure (~5.6/km², score 53); Spring 2026 escalated to Severe
        # (~13.5/km², score 84). The lender's loan-review committee sees
        # the trajectory, not just a snapshot — that's the wedge against
        # the $40K point-in-time field survey alternative.
        "prior_seasons": [
            {
                "name": "Fall 2025",
                "start": date(2025, 9, 1), "end": date(2025, 11, 30),
                "hog_events_by_camera": {
                    "CAM-RB-CORN-01": 50,
                    "CAM-RB-CORN-02": 46,
                    "CAM-RB-RAND-01": 62,
                    "CAM-RB-RAND-02": 72,
                },
            },
        ],
        # Heavy hog pressure on a small corn parcel. Density >10/km² => Severe.
        # Deployment design: 2 cameras at high-utility features (food_plot,
        # water) for hog detection, plus 2 cameras placed at random GPS
        # within the parcel for IPW bias-correction calibration. The
        # Kolowski 2017 inflation factors deflate the biased-cam rates;
        # the random cameras anchor the adjusted rate against a
        # placement-bias-free reference.
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
            {
                "label": "CAM-RB-RAND-01", "name": "Random GPS sample, southeast quadrant",
                "lat": 30.591, "lon": -96.474, "placement_context": "random",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 20),
                "species": {
                    "feral_hog": {"photos": 326, "events": 95, "conf": 0.91,
                                  "hourly": hourly((20,24,5),(0,6,5)),
                                  "first_seen": datetime(2026,2,2,21,55,10),
                                  "last_seen":  datetime(2026,3,30,5,40,18)},
                },
            },
            {
                "label": "CAM-RB-RAND-02", "name": "Random GPS sample, northwest quadrant",
                "lat": 30.612, "lon": -96.512, "placement_context": "random",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 20),
                "species": {
                    "feral_hog": {"photos": 384, "events": 110, "conf": 0.92,
                                  "hourly": hourly((21,24,5),(0,7,5)),
                                  "first_seen": datetime(2026,2,3,22,12,2),
                                  "last_seen":  datetime(2026,3,31,4,18,55)},
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
        # Trail camera + 1 random for IPW calibration.
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
            {
                "label": "CAM-OR-RAND-01", "name": "Random GPS sample, west block",
                "lat": 30.288, "lon": -98.982, "placement_context": "random",
                "camera_model": "Reconyx HP2X", "installed_date": date(2026, 1, 19),
                "species": {
                    "feral_hog": {"photos": 81, "events": 25, "conf": 0.88,
                                  "hourly": hourly((21,24,3),(0,5,3)),
                                  "first_seen": datetime(2026,2,6,23,18,40),
                                  "last_seen":  datetime(2026,3,29,4,2,11)},
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

    # 3a. Add a random-placement camera to Edwards Plateau so the IPW
    # bias correction has an unbiased anchor (otherwise all 3 existing
    # cameras are at feeder/trail and the literature-prior factors
    # deflate the rate ~5×, knocking the parcel from Elevated to Low).
    # Idempotent via the CAM-EP-RAND-* label prefix.
    cur.execute("""
        DELETE FROM detection_summaries
        WHERE camera_id IN (SELECT id FROM cameras
                            WHERE property_id=1
                              AND camera_label LIKE 'CAM-EP-RAND-%')
    """)
    cur.execute("""
        DELETE FROM cameras
        WHERE property_id=1 AND camera_label LIKE 'CAM-EP-RAND-%'
    """)
    cur.execute("""
        SELECT id FROM seasons WHERE property_id=1
        ORDER BY start_date DESC LIMIT 1
    """)
    row = cur.fetchone()
    if row:
        ep_season_id = row[0]
        cur.execute("""
            INSERT INTO cameras (property_id, camera_label, name, lat, lon,
                                 placement_context, camera_model, installed_date,
                                 is_active, created_at, updated_at)
            VALUES (1, 'CAM-EP-RAND-01', 'Random GPS sample, central plateau',
                    30.51, -99.74, 'random', 'Reconyx HP2X',
                    %s, TRUE, NOW(), NOW())
            RETURNING id
        """, (date(2026, 1, 18),))
        ep_rand_cam_id = cur.fetchone()[0]
        ep_h24 = hourly((20, 24, 5), (0, 6, 5))
        cur.execute("""
            INSERT INTO detection_summaries
                (season_id, camera_id, species_key,
                 total_photos, independent_events, avg_confidence,
                 first_seen, last_seen, buck_count, doe_count,
                 peak_hour, hourly_distribution, created_at)
            VALUES (%s,%s,'feral_hog', 348, 100, 0.91,
                    %s, %s, 0, 0, %s, %s, NOW())
        """, (ep_season_id, ep_rand_cam_id,
              datetime(2026, 2, 3, 21, 14, 22),
              datetime(2026, 3, 30, 5, 22, 8),
              ep_h24.index(max(ep_h24)),
              json.dumps(ep_h24)))
        print(f"  Added CAM-EP-RAND-01 to Edwards Plateau "
              f"(season={ep_season_id}, hog events=100)")

    # 4. UPSERT each parcel by owner_email + property name so the
    #    auto-increment id stays stable across reseeds. Camera + season
    #    + detection_summary rows DO get wiped and rebuilt per-property
    #    each run (so changes to the seed data take effect), but the
    #    parent property_id never changes — the demo URLs and recorded
    #    MP4 keep pointing at the same /lender/.../parcel/<N>.
    for p in PARCELS:
        owner_email = p["owner_email"]
        owner_name = p["owner_name"]
        prop_data = p["property"]

        cur.execute("""
            INSERT INTO users (email, password_hash, display_name, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (email) DO UPDATE
              SET display_name = EXCLUDED.display_name,
                  updated_at = NOW()
            RETURNING id
        """, (owner_email, "!unset!", owner_name))
        user_id = cur.fetchone()[0]

        boundary_geojson = json.dumps({
            "type": "Feature",
            "properties": {"name": prop_data["name"]},
            "geometry": {"type": "Polygon", "coordinates": [prop_data["boundary"]]},
        })

        # Properties has no UNIQUE constraint on (user_id, name) yet, so
        # do the upsert in two steps: SELECT existing, UPDATE or INSERT.
        cur.execute("""
            SELECT id FROM properties WHERE user_id=%s AND name=%s LIMIT 1
        """, (user_id, prop_data["name"]))
        row = cur.fetchone()
        if row:
            property_id = row[0]
            cur.execute("""
                UPDATE properties
                SET county=%s, state=%s, acreage=%s,
                    boundary_geojson=%s, lender_client_id=%s,
                    crop_type=%s, updated_at=NOW()
                WHERE id=%s
            """, (prop_data["county"], prop_data["state"], prop_data["acreage"],
                  boundary_geojson, lender_id, prop_data["crop_type"], property_id))
            # Wipe per-property leaf data so cameras/seasons rebuild cleanly.
            cur.execute("""
                DELETE FROM detection_summaries WHERE camera_id IN
                    (SELECT id FROM cameras WHERE property_id=%s)
            """, (property_id,))
            cur.execute("""
                DELETE FROM detection_summaries WHERE season_id IN
                    (SELECT id FROM seasons WHERE property_id=%s)
            """, (property_id,))
            cur.execute("DELETE FROM cameras WHERE property_id=%s", (property_id,))
            cur.execute("DELETE FROM seasons WHERE property_id=%s", (property_id,))
            print(f"  {prop_data['name']} (id={property_id}, refreshed)")
        else:
            cur.execute("""
                INSERT INTO properties (user_id, name, county, state, acreage,
                                        boundary_geojson, lender_client_id,
                                        crop_type, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                RETURNING id
            """, (user_id, prop_data["name"], prop_data["county"], prop_data["state"],
                  prop_data["acreage"], boundary_geojson, lender_id, prop_data["crop_type"]))
            property_id = cur.fetchone()[0]
            print(f"  {prop_data['name']} (id={property_id}, NEW — note this id for demo links)")

        if p["season"] is None:
            print(f"    \u2192 pending (no season seeded)")
            continue

        cur.execute("""
            INSERT INTO seasons (property_id, name, start_date, end_date, created_at)
            VALUES (%s, %s, %s, %s, NOW()) RETURNING id
        """, (property_id, p["season"]["name"], p["season"]["start"], p["season"]["end"]))
        season_id = cur.fetchone()[0]

        cam_ids_by_label = {}
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
            cam_ids_by_label[cam["label"]] = cam_id

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

        # Optional prior seasons — same cameras, different
        # detection_summaries rows. Drives the continuous-monitoring
        # trend widget on the parcel report.
        for prior in p.get("prior_seasons", []):
            cur.execute("""
                INSERT INTO seasons (property_id, name, start_date, end_date, created_at)
                VALUES (%s, %s, %s, %s, NOW()) RETURNING id
            """, (property_id, prior["name"], prior["start"], prior["end"]))
            prior_season_id = cur.fetchone()[0]
            prior_h24 = hourly((20, 24, 4), (0, 6, 4))
            for cam_label, hog_events in prior["hog_events_by_camera"].items():
                cam_id = cam_ids_by_label.get(cam_label)
                if cam_id is None:
                    continue
                # Approximate photos at ~4× events (consistent w/ Spring 2026
                # photo:event ratios on these cameras).
                photos = hog_events * 4
                first_dt = datetime.combine(prior["start"], datetime.min.time())
                last_dt = datetime.combine(prior["end"], datetime.min.time())
                cur.execute("""
                    INSERT INTO detection_summaries
                        (season_id, camera_id, species_key,
                         total_photos, independent_events, avg_confidence,
                         first_seen, last_seen, buck_count, doe_count,
                         peak_hour, hourly_distribution, created_at)
                    VALUES (%s,%s,'feral_hog', %s, %s, 0.91,
                            %s, %s, 0, 0, %s, %s, NOW())
                """, (prior_season_id, cam_id, photos, hog_events,
                      first_dt, last_dt,
                      prior_h24.index(max(prior_h24)),
                      json.dumps(prior_h24)))

        n_priors = len(p.get("prior_seasons", []))
        prior_note = f" + {n_priors} prior season(s)" if n_priors else ""
        print(f"    \u2192 {len(p['cameras'])} camera(s), crop={prop_data['crop_type']}{prior_note}")

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
