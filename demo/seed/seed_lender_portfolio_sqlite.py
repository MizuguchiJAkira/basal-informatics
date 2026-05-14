"""SQLite-friendly lender-portfolio seed (YC demo).

The upstream ``demo/seed/seed_lender_portfolio.py`` uses ``psycopg2`` +
Postgres-specific SQL (``ON CONFLICT``, ``RETURNING``, ``NOW()``,
``JSONB``). The local demo runs on SQLite (``sqlite:///basal.db``), so
this parallel seed uses SQLAlchemy models through the app context and
sticks to portable ORM operations.

Minimum viable demo state:
  1. Create LenderClient slug="acme" (Acme Agricultural Credit).
  2. Attach the existing Edwards Plateau Ranch (property_id=1) to
     Acme Ag and set crop_type="sorghum".
  3. Create Riverbend Farm (650 ac corn, Brazos Co TX) with:
     - 4 cameras (two feeder, one random-anchor for IPW, one trail)
     - 1 Season (Spring 2026)
     - Detection summaries loaded from a feral-hog-heavy template so
       the portfolio shows a Severe tier for Riverbend (matches the
       landing page "Riverbend Farm 83.7 score" worked example).

Idempotent: re-running drops prior Riverbend data + re-inserts, and
upserts the Acme Ag lender client. Edwards Plateau's existing detection
data is untouched.

Usage (from repo root):
    python3 demo/seed/seed_lender_portfolio_sqlite.py
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger("seed_lender_portfolio_sqlite")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))
# Ensure the app uses the right DB (default is SQLite).
os.environ.setdefault("FLASK_APP", "web.app")


def main() -> None:
    from web.app import create_app
    from db.models import (
        Camera, DetectionSummary, LenderClient, Property, Season, User, db,
    )

    app = create_app(demo=True, site="basal")
    with app.app_context():
        # ── 1. LenderClient: upsert Acme Agricultural Credit ──────
        lender = LenderClient.query.filter_by(slug="acme").first()
        if not lender:
            lender = LenderClient(
                name="Acme Agricultural Credit",
                slug="acme",
                parent_org="Farm Credit System",
                state="TX",
                hq_address="Waco, TX",
                contact_email="portfolio@acme.example.coop",
                plan_tier="portfolio_pilot",
                per_parcel_rate_usd=None,
                active=True,
            )
            db.session.add(lender)
            db.session.flush()
            logger.info("created LenderClient id=%d (Acme Ag)", lender.id)
        else:
            logger.info("LenderClient Acme Ag already exists (id=%d)", lender.id)

        # ── 2. Attach Edwards Plateau Ranch to Acme Ag ───────────────────
        ep = Property.query.filter_by(id=1, name="Edwards Plateau Ranch").first()
        if ep:
            ep.lender_client_id = lender.id
            if hasattr(ep, "crop_type"):
                ep.crop_type = "sorghum"
            logger.info("attached Edwards Plateau Ranch to Acme Ag")
        else:
            logger.warning("Edwards Plateau Ranch (id=1) not found — skip attach")

        # ── 3. Create Riverbend Farm (drop + re-insert for idempotency) ──
        # Find any existing Riverbend rows to wipe.
        riverbend = Property.query.filter_by(name="Riverbend Farm").first()
        if riverbend:
            # Cascade cleanup: detection_summaries → cameras → seasons → property
            for cam in riverbend.cameras:
                DetectionSummary.query.filter_by(camera_id=cam.id).delete()
            Camera.query.filter_by(property_id=riverbend.id).delete()
            Season.query.filter_by(property_id=riverbend.id).delete()
            db.session.delete(riverbend)
            db.session.flush()
            logger.info("dropped prior Riverbend Farm state")

        # Need an owner user.
        owner = User.query.filter_by(email="owner@basal.eco").first()
        if not owner:
            owner = User.query.first()
        if not owner:
            logger.warning("no user in DB — creating a placeholder demo user")
            owner = User(
                email="demo-owner@basal.eco",
                name="Demo Owner",
                password_hash="!",  # invalid hash; demo mode bypasses login
            )
            db.session.add(owner)
            db.session.flush()

        # Approximate 650-acre rectangular boundary in rural NE Brazos
        # County TX (near Kurten — open farmland + mixed pasture). Placed
        # NORTH of Old Reliance Road so the road forms the southern edge
        # of the parcel rather than bisecting it. ~1.0 mi N-S × ~1.0 mi
        # E-W ≈ 650 ac.
        RIVERBEND_BOUNDARY_GEOJSON = (
            '{"type":"Polygon","coordinates":[[['
            '-96.2780,30.7450],[-96.2600,30.7450],'
            '[-96.2600,30.7590],[-96.2780,30.7590],'
            '[-96.2780,30.7450]]]}'
        )
        riverbend = Property(
            user_id=owner.id,
            name="Riverbend Farm",
            lender_client_id=lender.id,
        )
        for attr, val in (
            ("state", "TX"),
            ("county", "Brazos"),
            ("acreage", 650.0),
            ("crop_type", "corn"),
            ("boundary_geojson", RIVERBEND_BOUNDARY_GEOJSON),
        ):
            if hasattr(riverbend, attr):
                setattr(riverbend, attr, val)
        db.session.add(riverbend)
        db.session.flush()
        logger.info("created Riverbend Farm id=%d (650 ac, boundary set)", riverbend.id)

        # 10 cameras across the 650-ac parcel in NE Brazos County rural
        # farmland (~65 ac/camera — typical feral-hog monitoring density).
        # Mix of biased (feeder/water/food-plot/trail) and random-anchor
        # placements so the Kolowski-Forrester 2017 IPW correction has
        # unbiased reference cameras.
        cam_configs = [
            # All cameras sit INSIDE the polygon (30.745 – 30.759 N,
            # -96.278 to -96.260 W). Spread across feeder / water /
            # food-plot / trail / random placements.
            # Feeders — concentrate hog activity
            ("CAM-RB-F01", "East Feeder",        30.7510, -96.2620, "feeder"),
            ("CAM-RB-F02", "Creek Feeder",       30.7490, -96.2720, "feeder"),
            ("CAM-RB-F03", "North Feeder",       30.7560, -96.2670, "feeder"),
            # Water — hog attractant, especially summer
            ("CAM-RB-W01", "Stock Pond",         30.7520, -96.2680, "water"),
            # Food plot
            ("CAM-RB-P01", "Oat Plot",           30.7490, -96.2640, "food_plot"),
            # Trails (biased but less intensively than feeders)
            ("CAM-RB-T01", "Hog Trail North",    30.7570, -96.2740, "trail"),
            ("CAM-RB-T02", "Hog Trail South",    30.7470, -96.2700, "trail"),
            ("CAM-RB-T03", "Fenceline Trail",    30.7480, -96.2620, "trail"),
            # Random anchors — critical for IPW bias correction
            ("CAM-RB-RAND-01", "Random Anchor #1", 30.7540, -96.2650, "random"),
            ("CAM-RB-RAND-02", "Random Anchor #2", 30.7460, -96.2680, "random"),
        ]
        cam_rows = []
        for label, name, lat, lon, ctx in cam_configs:
            cam = Camera(
                property_id=riverbend.id,
                camera_label=label,
                name=name,
                lat=lat,
                lon=lon,
                placement_context=ctx,
                is_active=True,
                installed_date=date(2026, 2, 1),
            )
            db.session.add(cam)
            db.session.flush()
            cam_rows.append(cam)
        logger.info("created %d cameras on Riverbend Farm", len(cam_rows))

        # Season: Spring 2026 (Feb 1 → Apr 15, 74 days)
        season = Season(
            property_id=riverbend.id,
            name="Spring 2026",
            start_date=date(2026, 2, 1),
            end_date=date(2026, 4, 15),
        )
        db.session.add(season)
        db.session.flush()

        # ── Detection summaries: build a feral-hog-heavy profile so
        #    the tier lands on Severe for Riverbend ─────────────────
        # Hog-heavy on feeders, light on random + trail. Deer/raccoon
        # backing numbers for realism. Hourly activity concentrated at
        # dusk + night for hog + raccoon, midday for deer.
        def _hourly_hog():
            # Crepuscular-nocturnal: 0–4h moderate, 18–23h peak.
            return [15, 12, 10, 8, 5, 3, 1, 1, 1, 1, 1, 2, 2, 3, 4, 6, 8, 11, 18, 22, 25, 22, 20, 18]

        def _hourly_deer():
            # Crepuscular: 5–8h peak, 17–20h peak, suppressed midday.
            return [2, 1, 1, 1, 2, 8, 15, 22, 18, 10, 5, 3, 2, 3, 5, 8, 12, 20, 25, 18, 10, 5, 3, 2]

        def _hourly_raccoon():
            # Nocturnal: peak 20–04.
            return [15, 18, 16, 12, 8, 3, 1, 1, 0, 0, 0, 0, 1, 1, 1, 2, 3, 4, 6, 10, 16, 20, 22, 20]

        # Event counts scaled to target SEVERE tier (>=10 animals/km²) under
        # Mayer-Brisbin 2009 across 10 cameras × 73-day survey. Feeders +
        # water + food-plot get the heaviest hog activity (realistic — these
        # are where hogs concentrate). Random anchors get very low hog rates
        # because they're placed by GPS grid, NOT on sign. Trails sit in
        # between. The bias-adjusted IPW rate pulls the whole-parcel density
        # estimate to the 12-16 animals/km² range.
        #
        # Camera index map:
        #  0  CAM-RB-F01  feeder  (East Feeder)        — hog-heavy
        #  1  CAM-RB-F02  feeder  (Creek Feeder)       — hog-heavy
        #  2  CAM-RB-F03  feeder  (North Feeder)       — hog-heavy
        #  3  CAM-RB-W01  water   (Stock Pond)         — hog-heavy (attractant)
        #  4  CAM-RB-P01  food_plot (Oat Plot)         — hog-heavy
        #  5  CAM-RB-T01  trail   (Hog Trail North)    — moderate
        #  6  CAM-RB-T02  trail   (Hog Trail South)    — moderate
        #  7  CAM-RB-T03  trail   (Fenceline Trail)    — moderate
        #  8  CAM-RB-RAND-01 random (unbiased anchor)  — low hog
        #  9  CAM-RB-RAND-02 random (unbiased anchor)  — low hog
        #
        # Format: (camera_index, species_key, total_photos, events, hourly_fn)
        synth_rows = [
            # --- Feeders (0, 1, 2) — the tier-driving cameras ---
            (0, "feral_hog",        2950, 498, _hourly_hog),
            (0, "white_tailed_deer", 780, 180, _hourly_deer),
            (0, "raccoon",           350, 110, _hourly_raccoon),
            (1, "feral_hog",        2780, 472, _hourly_hog),
            (1, "white_tailed_deer", 620, 160, _hourly_deer),
            (1, "coyote",            220,  65, _hourly_deer),
            (2, "feral_hog",        2610, 446, _hourly_hog),
            (2, "white_tailed_deer", 560, 148, _hourly_deer),
            (2, "raccoon",           210,  74, _hourly_raccoon),
            # --- Water (3) — summer hog concentration ---
            (3, "feral_hog",        2320, 398, _hourly_hog),
            (3, "white_tailed_deer", 510, 138, _hourly_deer),
            (3, "raccoon",           280,  92, _hourly_raccoon),
            # --- Food plot (4) — corn-planted, hog magnet ---
            (4, "feral_hog",        2140, 368, _hourly_hog),
            (4, "white_tailed_deer", 690, 175, _hourly_deer),
            (4, "turkey",            140,  48, _hourly_deer),
            # --- Trails (5, 6, 7) — moderate hog activity ---
            (5, "feral_hog",         820, 178, _hourly_hog),
            (5, "white_tailed_deer", 310, 115, _hourly_deer),
            (5, "coyote",            180,  58, _hourly_deer),
            (6, "feral_hog",         720, 156, _hourly_hog),
            (6, "white_tailed_deer", 270,  96, _hourly_deer),
            (6, "bobcat",             35,  14, _hourly_deer),
            (7, "feral_hog",         680, 144, _hourly_hog),
            (7, "white_tailed_deer", 240,  86, _hourly_deer),
            (7, "coyote",            120,  42, _hourly_deer),
            # --- Random anchors (8, 9) — low hog, honest baseline ---
            (8, "feral_hog",         480, 140, _hourly_hog),
            (8, "white_tailed_deer", 195,  72, _hourly_deer),
            (8, "turkey",             85,  32, _hourly_deer),
            (9, "feral_hog",         420, 124, _hourly_hog),
            (9, "white_tailed_deer", 175,  68, _hourly_deer),
            (9, "raccoon",            60,  24, _hourly_raccoon),
        ]
        ds_rows = []
        for cam_idx, species, total, events, hourly_fn in synth_rows:
            hourly = hourly_fn()
            peak_hour = hourly.index(max(hourly))
            ds = DetectionSummary(
                season_id=season.id,
                camera_id=cam_rows[cam_idx].id,
                species_key=species,
                total_photos=total,
                independent_events=events,
                first_seen=datetime(2026, 2, 3, 20, 0),
                last_seen=datetime(2026, 4, 12, 5, 30),
                peak_hour=peak_hour,
                avg_confidence=0.87,
            )
            # The model may or may not have hourly_histogram / buck_count / etc.
            if hasattr(ds, "hourly_histogram"):
                ds.hourly_histogram = hourly
            ds_rows.append(ds)
        db.session.add_all(ds_rows)
        db.session.flush()
        logger.info(
            "created %d detection summaries on Riverbend (feral-hog-heavy)",
            len(ds_rows),
        )

        # ══════════════════════════════════════════════════════════════
        # Supplementary citizen-science neighbors
        # ══════════════════════════════════════════════════════════════
        # Three adjacent landowners sitting within 2 km of Riverbend's
        # boundary. Their cameras populate the "SUPPLEMENTARY — NEIGHBORING
        # COVERAGE" section of the Nature Exposure Report. This is the
        # "Basal weaponizes citizen-science trail-cam networks" story:
        # neighboring Strecker-or-equivalent hunter users extend per-parcel
        # coverage without adding survey cost to the lender.
        #
        # Per-proximity strategic spec in risk/proximity.py:
        #   - Neighboring data is SUPPLEMENTARY; does NOT fold into REM
        #     density on the primary parcel (avoids double-counting).
        #   - Does surface species contributions + proximity confidence
        #     as corroborating signal.

        neighbor_specs = [
            {
                "name": "Hickory Grove Farm",
                "owner_email": "hickory-grove@basal-demo.test",
                "county": "Brazos",
                "acreage": 280.0,
                # Positioned NORTH of Riverbend (0.5–0.8 km from N boundary)
                "cameras": [
                    ("CAM-HG-01", "North Pasture Feeder", 30.7640, -96.2720, "feeder"),
                    ("CAM-HG-02", "Creek Crossing",       30.7660, -96.2660, "trail"),
                ],
                # Light hog activity — neighboring parcel, less pressure.
                "detections": [
                    (0, "feral_hog",        280,  82),
                    (0, "white_tailed_deer", 95,  38),
                    (1, "feral_hog",        210,  66),
                    (1, "white_tailed_deer", 110, 42),
                ],
            },
            {
                "name": "Elm Ridge Property",
                "owner_email": "elm-ridge@basal-demo.test",
                "county": "Brazos",
                "acreage": 420.0,
                # Positioned EAST of Riverbend (0.8–1.2 km from E boundary)
                "cameras": [
                    ("CAM-ER-01", "East Edge Feeder",     30.7540, -96.2520, "feeder"),
                    ("CAM-ER-02", "Oak Motte Trail",      30.7510, -96.2480, "trail"),
                ],
                "detections": [
                    (0, "feral_hog",        320,  94),
                    (0, "white_tailed_deer", 80,  32),
                    (1, "feral_hog",        180,  52),
                    (1, "coyote",            55,  22),
                ],
            },
            {
                "name": "Rocking K Ranch",
                "owner_email": "rocking-k@basal-demo.test",
                "county": "Brazos",
                "acreage": 1100.0,
                # Positioned SOUTH of Riverbend, across Old Reliance Road
                # (0.7–1.0 km from S boundary)
                "cameras": [
                    ("CAM-RK-01", "Fenceline North",      30.7380, -96.2760, "feeder"),
                    ("CAM-RK-02", "Brush Trail",          30.7400, -96.2820, "trail"),
                ],
                "detections": [
                    (0, "feral_hog",        410, 120),
                    (0, "white_tailed_deer", 145, 52),
                    (1, "feral_hog",        240,  78),
                    (1, "white_tailed_deer", 90,  38),
                ],
            },
        ]

        for spec in neighbor_specs:
            # Drop any prior neighbor state for idempotency.
            prior = Property.query.filter_by(name=spec["name"]).first()
            if prior:
                for cam in prior.cameras:
                    DetectionSummary.query.filter_by(camera_id=cam.id).delete()
                Camera.query.filter_by(property_id=prior.id).delete()
                Season.query.filter_by(property_id=prior.id).delete()
                db.session.delete(prior)
                db.session.flush()

            # Owner user (separate from Acme Ag lender — these are citizen
            # contributors, not borrowers).
            nbr_owner = User.query.filter_by(email=spec["owner_email"]).first()
            if not nbr_owner:
                nbr_owner = User(
                    email=spec["owner_email"],
                    display_name=spec["name"] + " owner",
                    password_hash="!",
                )
                db.session.add(nbr_owner)
                db.session.flush()

            nbr_prop = Property(
                user_id=nbr_owner.id,
                name=spec["name"],
                # NO lender_client_id — these aren't in Acme Ag's book.
            )
            for attr, val in (
                ("state", "TX"),
                ("county", spec["county"]),
                ("acreage", spec["acreage"]),
            ):
                if hasattr(nbr_prop, attr):
                    setattr(nbr_prop, attr, val)
            db.session.add(nbr_prop)
            db.session.flush()

            nbr_cams = []
            for label, name, lat, lon, ctx in spec["cameras"]:
                c = Camera(
                    property_id=nbr_prop.id,
                    camera_label=label,
                    name=name,
                    lat=lat, lon=lon,
                    placement_context=ctx,
                    is_active=True,
                    installed_date=date(2026, 2, 1),
                )
                db.session.add(c)
                db.session.flush()
                nbr_cams.append(c)

            nbr_season = Season(
                property_id=nbr_prop.id,
                name="Spring 2026",
                start_date=date(2026, 2, 1),
                end_date=date(2026, 4, 15),
            )
            db.session.add(nbr_season)
            db.session.flush()

            for cam_idx, species, photos, events in spec["detections"]:
                ds = DetectionSummary(
                    season_id=nbr_season.id,
                    camera_id=nbr_cams[cam_idx].id,
                    species_key=species,
                    total_photos=photos,
                    independent_events=events,
                    first_seen=datetime(2026, 2, 10, 5, 30),
                    last_seen=datetime(2026, 4, 12, 22, 15),
                    avg_confidence=0.83,
                )
                db.session.add(ds)

            logger.info(
                "seeded neighbor %s (%d cams, %d detections)",
                spec["name"],
                len(nbr_cams),
                len(spec["detections"]),
            )

        db.session.commit()
        logger.info("seed committed")

        # ── Summary ───────────────────────────────────────────────────
        n_parcels = Property.query.filter_by(lender_client_id=lender.id).count()
        n_neighbors = sum(1 for s in neighbor_specs)
        logger.info(
            "Acme Ag portfolio: %d parcels · %d citizen-science neighbors seeded",
            n_parcels, n_neighbors,
        )


if __name__ == "__main__":
    main()
