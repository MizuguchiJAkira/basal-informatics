"""Flask application factory and configuration."""

import os
import sys

from flask import Flask
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.models import db


def _seed_strecker_demo(hunter, db, Property, Camera, Season, Upload,
                        DetectionSummary, datetime, timedelta, date):
    """Seed Strecker demo: property, cameras, season, and detection summaries
    parsed from the demo manifest CSV."""
    import csv
    import json
    from pathlib import Path
    from collections import defaultdict

    # Ranch parcel boundary (rough polygon enclosing camera positions)
    ranch_boundary = json.dumps({
        "type": "Feature",
        "properties": {"name": "Edwards Plateau Ranch"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [-99.77, 30.46],
                [-99.77, 30.53],
                [-99.69, 30.53],
                [-99.69, 30.46],
                [-99.77, 30.46],
            ]]
        }
    })

    prop = Property(
        user_id=hunter.id,
        name="Edwards Plateau Ranch",
        county="Kimble",
        state="TX",
        acreage=2340,
        boundary_geojson=ranch_boundary,
    )
    db.session.add(prop)
    db.session.flush()

    season = Season(
        property_id=prop.id,
        name="Fall 2025",
        start_date=date(2025, 9, 1),
        end_date=date(2026, 2, 28),
    )
    db.session.add(season)
    db.session.flush()

    cam_configs = [
        ("CAM-F01", "South Feeder", 30.48, -99.72, "feeder"),
        ("CAM-F02", "North Feeder", 30.51, -99.74, "feeder"),
        ("CAM-T01", "Creek Crossing", 30.49, -99.71, "trail"),
        ("CAM-T02", "Ridge Trail", 30.50, -99.73, "trail"),
        ("CAM-W01", "Stock Tank", 30.47, -99.70, "water"),
        ("CAM-P01", "Oat Plot", 30.52, -99.75, "food_plot"),
    ]
    cam_id_map = {}  # camera_label -> db id
    for label, name, lat, lon, ctx in cam_configs:
        cam = Camera(
            property_id=prop.id,
            camera_label=label,
            name=name,
            lat=lat,
            lon=lon,
            placement_context=ctx,
            is_active=True,
            installed_date=date(2025, 9, 1),
        )
        db.session.add(cam)
        db.session.flush()
        cam_id_map[label] = cam.id

    # Parse manifest.csv to build DetectionSummary records
    manifest_path = (
        Path(__file__).parent.parent / "demo" / "output" / "sorted" / "manifest.csv"
    )

    # Aggregate per (camera_label, species)
    agg = defaultdict(lambda: {
        "total_photos": 0,
        "events": set(),
        "confidence_sum": 0.0,
        "confidence_count": 0,
        "first_seen": None,
        "last_seen": None,
        "hourly": [0] * 24,
        "buck_count": 0,
        "doe_count": 0,
    })

    if manifest_path.exists():
        with open(manifest_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cam_label = row.get("camera_id", "")
                species = row.get("species", "")
                if not cam_label or not species or cam_label not in cam_id_map:
                    continue

                key = (cam_label, species)
                bucket = agg[key]
                bucket["total_photos"] += 1

                event_id = row.get("independent_event_id", "")
                if event_id:
                    bucket["events"].add(event_id)

                conf = float(row.get("confidence", 0) or 0)
                if conf > 0:
                    bucket["confidence_sum"] += conf
                    bucket["confidence_count"] += 1

                ts_str = row.get("timestamp", "")
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if bucket["first_seen"] is None or ts < bucket["first_seen"]:
                            bucket["first_seen"] = ts
                        if bucket["last_seen"] is None or ts > bucket["last_seen"]:
                            bucket["last_seen"] = ts
                        bucket["hourly"][ts.hour] += 1
                    except (ValueError, TypeError):
                        pass

                antler = row.get("antler_classification", "")
                if antler == "antlered":
                    bucket["buck_count"] += 1
                elif antler == "not_antlered":
                    bucket["doe_count"] += 1

    total_photos = 0
    for (cam_label, species), bucket in agg.items():
        cam_db_id = cam_id_map.get(cam_label)
        if not cam_db_id:
            continue

        avg_conf = (
            round(bucket["confidence_sum"] / bucket["confidence_count"], 3)
            if bucket["confidence_count"] > 0 else None
        )
        peak_hour = bucket["hourly"].index(max(bucket["hourly"])) if any(bucket["hourly"]) else None

        ds = DetectionSummary(
            season_id=season.id,
            camera_id=cam_db_id,
            species_key=species,
            total_photos=bucket["total_photos"],
            independent_events=len(bucket["events"]),
            avg_confidence=avg_conf,
            first_seen=bucket["first_seen"],
            last_seen=bucket["last_seen"],
            buck_count=bucket["buck_count"],
            doe_count=bucket["doe_count"],
            peak_hour=peak_hour,
            hourly_distribution=json.dumps(bucket["hourly"]),
        )
        db.session.add(ds)
        total_photos += bucket["total_photos"]

    upload = Upload(
        property_id=prop.id,
        user_id=hunter.id,
        season_id=season.id,
        status="complete",
        photo_count=total_photos,
        uploaded_at=datetime.utcnow() - timedelta(days=3),
        processed_at=datetime.utcnow() - timedelta(days=3),
    )
    db.session.add(upload)
    db.session.commit()


def create_app(demo: bool = False, site: str = "strecker") -> Flask:
    """Create and configure the Flask application.

    Args:
        demo: If True, use in-memory SQLite instead of PostGIS.
        site: "strecker" (hunter-facing) or "basal" (owner/insurer-facing).
    """
    app = Flask(__name__)
    app.config["SITE"] = site

    # Core config
    from config import settings

    app.config["SECRET_KEY"] = settings.SECRET_KEY
    app.config["SQLALCHEMY_DATABASE_URI"] = settings.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    # Pooling only applies to non-SQLite backends (Postgres/MySQL).
    if not settings.DATABASE_URL.startswith("sqlite"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = settings.SQLALCHEMY_ENGINE_OPTIONS
    app.config["DEMO_MODE"] = demo
    app.config["SITE"] = site

    # Initialize extensions
    csrf = CSRFProtect(app)
    db.init_app(app)

    # Store csrf on app for blueprint exemptions
    app.csrf = csrf

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "info"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        from db.models import User
        return User.query.get(int(user_id))

    # ── Auth is shared by both sites ──
    from web.routes.auth import auth_bp
    app.register_blueprint(auth_bp)

    if site == "strecker":
        # Hunter-facing blueprints only
        from web.routes.feedback import feedback_bp
        from web.routes.upload import upload_bp
        from web.routes.results import results_bp
        from web.routes.properties import properties_bp
        from web.routes.api.properties import properties_api_bp
        from web.routes.api.uploads import uploads_api_bp
        from web.routes.api.dashboard import dashboard_api_bp
        from web.routes.api.share import share_api_bp
        from web.routes.api.reid import reid_api_bp
        # Pre-signed upload flow — lives primarily on the basal (lender)
        # site but the hunter upload UI uses the /api/properties alias,
        # so we also register it here. Same handlers, same storage.
        from web.routes.api.parcel_uploads import (
            parcel_uploads_bp as _pu_bp,
            property_uploads_bp as _pp_bp,
        )
        # Tokenized (passwordless) upload flow — share a link to a
        # landowner, they upload without an account. Register on both
        # sites so the link works regardless of which host resolves.
        from web.routes.api.token_uploads import (
            token_uploads_bp as _tu_bp,
            upload_tokens_bp as _ut_bp,
        )

        app.register_blueprint(feedback_bp)
        app.register_blueprint(upload_bp)
        app.register_blueprint(results_bp)
        app.register_blueprint(properties_bp)
        app.register_blueprint(properties_api_bp)
        app.register_blueprint(uploads_api_bp)
        app.register_blueprint(dashboard_api_bp)
        app.register_blueprint(share_api_bp)
        app.register_blueprint(reid_api_bp)
        app.register_blueprint(_pu_bp)
        app.register_blueprint(_pp_bp)
        app.register_blueprint(_tu_bp)
        app.register_blueprint(_ut_bp)

        # Exempt JSON API endpoints from CSRF (they use auth tokens, not cookies)
        for bp in (properties_api_bp, uploads_api_bp, dashboard_api_bp,
                   share_api_bp, reid_api_bp, _pu_bp, _pp_bp,
                   _tu_bp, _ut_bp):
            csrf.exempt(bp)

    elif site == "basal":
        # Basal Informatics — insurer + lender-facing blueprints only
        from web.routes.demo import demo_bp
        from web.routes.owner import owner_bp
        from web.routes.api.owner import owner_api_bp
        from web.routes.lender import lender_bp
        from web.routes.api.parcel_uploads import (
            parcel_uploads_bp, property_uploads_bp,
        )
        from web.routes.api.token_uploads import (
            token_uploads_bp, upload_tokens_bp,
        )

        app.register_blueprint(demo_bp)
        app.register_blueprint(owner_bp)
        app.register_blueprint(owner_api_bp)
        app.register_blueprint(lender_bp)
        app.register_blueprint(parcel_uploads_bp)
        # Hunter-side alias — same handlers, /api/properties/... URL shape
        app.register_blueprint(property_uploads_bp)
        # Tokenized upload flow
        app.register_blueprint(token_uploads_bp)
        app.register_blueprint(upload_tokens_bp)

        # Exempt JSON API endpoints from CSRF (auth via session/token, not cookie)
        csrf.exempt(owner_api_bp)
        csrf.exempt(parcel_uploads_bp)
        csrf.exempt(property_uploads_bp)
        csrf.exempt(token_uploads_bp)
        csrf.exempt(upload_tokens_bp)
        # Lender routes are server-rendered HTML with CSRF on forms only;
        # the JSON exposure endpoint under /lender/api/ is read-only GET.

    # ── Static brand context based on site ──
    is_basal = (site == "basal")

    @app.context_processor
    def inject_brand():
        return {
            "brand_name": "Basal Informatics" if is_basal else "Strecker",
            "brand_tagline": (
                "Ground-truth ecological data for nature-risk assessment"
                if is_basal else
                "Trail cam intelligence for land managers"
            ),
            "brand_domain": "basalinformatics.com" if is_basal else "strecker.app",
            "is_basal_site": is_basal,
        }

    # Auto-login demo user on first request (demo mode only)
    if demo:
        @app.before_request
        def auto_login_demo():
            from flask_login import current_user, login_user
            if current_user.is_authenticated:
                return
            from db.models import User
            if site == "strecker":
                user = User.query.filter_by(email="demo@strecker.app").first()
            else:
                user = User.query.filter_by(email="owner@basal.eco").first()
            if user:
                login_user(user)

    # Friendly error pages so a YC partner / loan-review committee
    # member never sees a Flask traceback or unstyled "Not Found"
    # page if something hiccups during the demo.
    from flask import render_template as _render_template
    import uuid as _uuid

    _ERROR_COPY = {
        404: ("Not found",
              "The parcel, report, or page you tried to open isn\u2019t in this "
              "portfolio. The seed data may have been refreshed and the URL is "
              "stale; head to the portfolio and pick a parcel from the list."),
        403: ("Access denied",
              "This view is gated to authorized lender / owner accounts. If "
              "you reached this from a partner-shared link, sign in with the "
              "credentials in your invitation email."),
        500: ("Something broke on our end",
              "An unexpected error occurred. The team has been notified. "
              "Try the portfolio link below; the rest of the dashboard should "
              "be unaffected."),
    }

    def _err_handler(code):
        def _h(_e):
            headline, body = _ERROR_COPY.get(code,
                ("Unexpected error", "Try the portfolio link below."))
            req_id = _uuid.uuid4().hex[:8]
            return _render_template(
                "errors/error.html",
                code=code, headline=headline, body=body, request_id=req_id,
            ), code
        return _h

    for code in (403, 404, 500):
        app.register_error_handler(code, _err_handler(code))

    @app.route("/health")
    def health():
        # Touch the DB on every health check (every 30s per .do/app.yaml)
        # so the SQLAlchemy connection pool stays warm. Without this the
        # first real request after an idle period pays the connection-
        # open cost (~1-3s) before responding — visible as a "freeze"
        # at the top of the demo recording.
        from sqlalchemy import text
        db_ok = True
        try:
            db.session.execute(text("SELECT 1")).scalar()
        except Exception:
            db_ok = False
        return {"status": "ok", "demo": demo, "site": site, "db": db_ok}

    @app.route("/")
    def index():
        from flask import redirect, render_template
        if site == "basal":
            # Editorial landing for the Basal Informatics brand. Pure
            # marketing — hero, pipeline diagram, sample parcel, pricing.
            # The operating dashboards live at /lender/** and /owner/**.
            return render_template("basal/landing.html")
        return render_template("home.html")

    @app.route("/photos/<species>/<filename>")
    def serve_photo(species, filename):
        """Serve trail cam photos with IR/night-vision styling.

        Real photos get a trail cam overlay (green IR tint, noise, camera
        stamp).  Empty placeholder files get a fully synthetic image.
        """
        from pathlib import Path
        from flask import send_file, abort
        import re, io, random

        try:
            from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageFilter
        except ImportError:
            abort(404)

        # Try demo sorted photos first, then uploaded photos
        photo_dir = Path(__file__).parent.parent / "demo" / "output" / "sorted" / species
        photo_path = photo_dir / filename
        if not photo_path.exists():
            # Check uploads directory (real user uploads)
            uploads_base = Path(settings.UPLOAD_DIR)
            # Search all job output dirs for this photo
            for job_dir in uploads_base.iterdir() if uploads_base.exists() else []:
                candidate = job_dir / "output" / "sorted" / species / filename
                if candidate.exists():
                    photo_path = candidate
                    break
            else:
                abort(404)

        # Parse filename for camera/date/time metadata
        m = re.match(
            r"^(CAM-\w+)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_\d+\.jpg$",
            filename, re.IGNORECASE,
        )
        cam = m.group(1) if m else "CAM"
        date_str = f"{m.group(2)}-{m.group(3)}-{m.group(4)}" if m else ""
        time_str = f"{m.group(5)}:{m.group(6)}:{m.group(7)}" if m else ""
        hour = int(m.group(5)) if m else 12

        try:
            font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 16)
            font_xs = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
        except (OSError, IOError):
            font_sm = ImageFont.load_default()
            font_xs = font_sm

        has_content = photo_path.stat().st_size > 0

        if has_content:
            # ── Real photo → apply trail cam effects ──
            img = Image.open(photo_path).convert("RGB")
            img = img.resize((640, 480), Image.LANCZOS)

            # Night mode: green-channel IR look
            if hour < 6 or hour >= 19:
                # Convert to grayscale, then tint green (IR night vision)
                gray = img.convert("L")
                import numpy as np
                arr = np.array(gray)
                rgb = np.stack([
                    (arr * 0.3).astype(np.uint8),   # R dim
                    (arr * 0.85).astype(np.uint8),   # G bright
                    (arr * 0.25).astype(np.uint8),   # B dim
                ], axis=-1)
                img = Image.fromarray(rgb)
            else:
                # Daytime: desaturate slightly, warm tint
                enhancer = ImageEnhance.Color(img)
                img = enhancer.enhance(0.7)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.15)

            # Add slight grain noise
            random.seed(hash(filename))
            draw = ImageDraw.Draw(img)
            for _ in range(1500):
                x, y = random.randint(0, 639), random.randint(0, 479)
                v = random.randint(-20, 20)
                px = img.getpixel((x, y))
                c = tuple(max(0, min(255, px[i] + v)) for i in range(3))
                draw.point((x, y), fill=c)

            # Slight vignette (darken edges)
            vignette = Image.new("L", (640, 480), 0)
            vdraw = ImageDraw.Draw(vignette)
            for i in range(30):
                alpha = int(255 * (1 - i / 30) * 0.4)
                vdraw.rectangle([i, i, 639 - i, 479 - i], outline=alpha)
            from PIL import ImageChops
            vignette = vignette.filter(ImageFilter.GaussianBlur(15))
            # Darken image where vignette is dark
            img_arr = __import__('numpy').array(img).astype(float)
            vig_arr = __import__('numpy').array(vignette).astype(float) / 255.0
            # Invert: vignette mask is bright at edges (darken there)
            vig_arr = 1.0 - (1.0 - vig_arr) * 0.5
            for ch in range(3):
                img_arr[:, :, ch] *= vig_arr
            img = Image.fromarray(img_arr.clip(0, 255).astype('uint8'))

        else:
            # ── Empty file → fully synthetic placeholder ──
            common = species.replace("_", " ").title()
            if hour < 5 or hour >= 20:
                bg_color = (15, 23, 35)
                text_color = (120, 160, 120)
            elif hour < 7 or hour >= 17:
                bg_color = (35, 45, 30)
                text_color = (180, 200, 150)
            else:
                bg_color = (60, 75, 50)
                text_color = (220, 230, 200)

            img = Image.new("RGB", (640, 480), bg_color)
            draw = ImageDraw.Draw(img)
            random.seed(hash(filename))
            for _ in range(800):
                x, y = random.randint(0, 639), random.randint(0, 479)
                v = random.randint(-15, 15)
                c = tuple(max(0, min(255, bg_color[i] + v)) for i in range(3))
                draw.point((x, y), fill=c)
            try:
                font_lg = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 36)
            except (OSError, IOError):
                font_lg = ImageFont.load_default()
            draw.text((320, 220), common, fill=text_color, font=font_lg, anchor="mm")

        # ── Camera overlay stamp (both real & synthetic) ──
        draw = ImageDraw.Draw(img)
        # Semi-transparent bar at bottom
        bar = Image.new("RGBA", (640, 32), (0, 0, 0, 140))
        img.paste(Image.new("RGB", (640, 32), (0, 0, 0)), (0, 448),
                  mask=bar.split()[3])
        overlay_color = (220, 220, 220)
        draw.text((12, 452), f"{cam}  {date_str} {time_str}",
                  fill=overlay_color, font=font_sm)

        # Temperature (simulated)
        random.seed(hash(filename) + 1)
        temp_f = random.randint(38, 95) if hour >= 6 and hour < 19 else random.randint(28, 65)
        draw.text((628, 452), f"{temp_f}°F", fill=overlay_color,
                  font=font_xs, anchor="rt")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")

    # Create tables — gated by a Postgres advisory lock so only one gunicorn
    # worker does schema work at a time (avoids create_all/ALTER deadlocks).
    with app.app_context():
        dialect = db.engine.dialect.name
        got_lock = False
        if dialect == "postgresql":
            try:
                row = db.session.execute(
                    db.text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": 0x5712EC_BA5A_1},  # arbitrary app-scoped key
                ).scalar()
                got_lock = bool(row)
            except Exception:
                db.session.rollback()
                got_lock = False
        else:
            got_lock = True  # SQLite: single writer anyway

        if got_lock:
            try:
                db.create_all()

                # Additive column migrations — each wrapped so pre-existing
                # columns don't abort the boot. Works on SQLite and Postgres.
                _additive_migrations = [
                    "ALTER TABLE users ADD COLUMN is_owner BOOLEAN DEFAULT 0",
                    "ALTER TABLE processing_jobs ADD COLUMN property_id INTEGER",
                    "ALTER TABLE processing_jobs ADD COLUMN upload_id INTEGER",
                    # Basal-side additions (lender pivot). Nullable; hunter-side ignores.
                    "ALTER TABLE properties ADD COLUMN lender_client_id INTEGER",
                    "ALTER TABLE properties ADD COLUMN crop_type VARCHAR(40)",
                    # SpeciesNet taxonomic chains (e.g.
                    # "mammalia;cetartiodactyla;suidae;sus;scrofa") exceed the
                    # original 80-char species_key cap and cause aggregation
                    # inserts to fail with StringDataRightTruncation. Widen.
                    "ALTER TABLE detection_summaries ALTER COLUMN species_key TYPE VARCHAR(200)",
                ]
                for stmt in _additive_migrations:
                    try:
                        db.session.execute(db.text(stmt))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()  # column already exists
            finally:
                if dialect == "postgresql":
                    try:
                        db.session.execute(
                            db.text("SELECT pg_advisory_unlock(:k)"),
                            {"k": 0x5712EC_BA5A_1},
                        )
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

        # Seed demo accounts and data
        if demo:
            from db.models import User, Property, Camera, Season, Upload, DetectionSummary
            from datetime import datetime, timedelta, date

            if site == "basal":
                owner = User.query.filter_by(email="owner@basal.eco").first()
                if not owner:
                    owner = User(
                        email="owner@basal.eco",
                        display_name="Basal Informatics",
                        is_owner=True,
                    )
                    owner.set_password("owner123")
                    db.session.add(owner)
                    db.session.commit()
                elif not owner.is_owner:
                    owner.is_owner = True
                    db.session.commit()

            elif site == "strecker":
                hunter = User.query.filter_by(email="demo@strecker.app").first()
                if not hunter:
                    hunter = User(
                        email="demo@strecker.app",
                        display_name="Demo Hunter",
                    )
                    hunter.set_password("demo123")
                    db.session.add(hunter)
                    db.session.commit()

                # Seed a demo property if none exist
                if Property.query.filter_by(user_id=hunter.id).count() == 0:
                    _seed_strecker_demo(hunter, db, Property, Camera, Season,
                                        Upload, DetectionSummary, datetime,
                                        timedelta, date)

    return app
