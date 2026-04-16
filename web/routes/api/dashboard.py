"""Dashboard API endpoints for the Basal Informatics web app.

Provides aggregated detection data for property dashboards:
summary stats, activity patterns, camera leaderboards, and map data.
"""

import json

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func

from config import settings
from db.models import db, Property, Camera, Season, DetectionSummary, CoverageScore
from strecker.coverage import calculate_coverage

dashboard_api_bp = Blueprint("dashboard_api", __name__, url_prefix="/api")

# ---------------------------------------------------------------------------
# Common-name mapping
# ---------------------------------------------------------------------------

COMMON_NAMES = {
    "white_tailed_deer": "White-tailed Deer",
    "feral_hog": "Feral Hog",
    "turkey": "Wild Turkey",
    "raccoon": "Raccoon",
    "armadillo": "Nine-banded Armadillo",
    "coyote": "Coyote",
    "bobcat": "Bobcat",
    "cottontail_rabbit": "Eastern Cottontail",
    "axis_deer": "Axis Deer",
    "opossum": "Virginia Opossum",
    "red_fox": "Red Fox",
    "gray_fox": "Gray Fox",
}

# Activity-pattern hour sets
NIGHT_HOURS = {0, 1, 2, 3, 4, 21, 22, 23}
DAY_HOURS = set(range(7, 18))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_property(property_id):
    """Return a Property owned by current_user, or None."""
    prop = Property.query.get(property_id)
    if prop and prop.user_id == current_user.id:
        return prop
    return None


def _get_season(season_id, property_id):
    """Return a Season belonging to the given property, or None."""
    return Season.query.filter_by(id=season_id, property_id=property_id).first()


def _parse_hourly(text):
    """Parse hourly_distribution JSON text into a list of 24 ints."""
    if not text:
        return [0] * 24
    try:
        data = json.loads(text)
        if isinstance(data, list) and len(data) == 24:
            return [int(v) for v in data]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return [0] * 24


def _classify_pattern(hourly):
    """Classify activity pattern and return (pattern, night_pct, day_pct)."""
    total = sum(hourly)
    if total == 0:
        return "Crepuscular", 0, 0
    night = sum(hourly[h] for h in NIGHT_HOURS)
    day = sum(hourly[h] for h in DAY_HOURS)
    night_pct = round(night * 100 / total)
    day_pct = round(day * 100 / total)
    if night_pct > 65:
        pattern = "Nocturnal"
    elif day_pct > 65:
        pattern = "Diurnal"
    else:
        pattern = "Crepuscular"
    return pattern, night_pct, day_pct


def _camera_ids_for_property(property_id):
    """Return set of camera IDs belonging to a property."""
    rows = db.session.query(Camera.id).filter_by(property_id=property_id).all()
    return {r[0] for r in rows}


def _detection_query(property_id, season_id):
    """Base query for DetectionSummary rows scoped to property cameras + season."""
    camera_ids = _camera_ids_for_property(property_id)
    if not camera_ids:
        return DetectionSummary.query.filter(False)  # empty result
    return DetectionSummary.query.filter(
        DetectionSummary.season_id == season_id,
        DetectionSummary.camera_id.in_(camera_ids),
    )


# ---------------------------------------------------------------------------
# 1. Summary
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/summary", methods=["GET"]
)
@login_required
def dashboard_summary(pid):
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    detections = _detection_query(pid, season_id).all()

    # Aggregate stats
    total_photos = sum(d.total_photos or 0 for d in detections)
    total_events = sum(d.independent_events or 0 for d in detections)
    species_keys = set(d.species_key for d in detections)
    camera_ids = set(d.camera_id for d in detections)

    days_monitored = 0
    if season.start_date and season.end_date:
        days_monitored = (season.end_date - season.start_date).days

    # Per-species aggregation
    species_map = {}
    for d in detections:
        key = d.species_key
        if key not in species_map:
            species_map[key] = {
                "species_key": key,
                "common_name": COMMON_NAMES.get(key, key.replace("_", " ").title()),
                "total_events": 0,
                "total_photos": 0,
                "camera_ids": set(),
                "confidence_sum": 0.0,
                "confidence_count": 0,
                "peak_hour": None,
                "peak_hour_max": 0,
                "buck_count": 0,
                "doe_count": 0,
                "_hourly_totals": [0] * 24,
            }
        s = species_map[key]
        s["total_events"] += d.independent_events or 0
        s["total_photos"] += d.total_photos or 0
        s["camera_ids"].add(d.camera_id)
        if d.avg_confidence is not None:
            s["confidence_sum"] += d.avg_confidence
            s["confidence_count"] += 1
        s["buck_count"] += d.buck_count or 0
        s["doe_count"] += d.doe_count or 0
        # Accumulate hourly for peak_hour recalculation
        hourly = _parse_hourly(d.hourly_distribution)
        for i in range(24):
            s["_hourly_totals"][i] += hourly[i]

    species_list = []
    for s in species_map.values():
        hourly = s.pop("_hourly_totals")
        peak = max(range(24), key=lambda h: hourly[h]) if any(hourly) else None
        avg_conf = round(s.pop("confidence_sum") / s.pop("confidence_count"), 2) if s["confidence_count"] else None
        # Remove internal keys
        s.pop("confidence_count", None)
        s["camera_count"] = len(s.pop("camera_ids"))
        s["avg_confidence"] = avg_conf
        s["peak_hour"] = peak
        species_list.append(s)

    species_list.sort(key=lambda x: x["total_events"], reverse=True)

    return jsonify({
        "property": {
            "name": prop.name,
            "acreage": prop.acreage,
            "county": prop.county,
            "state": prop.state,
        },
        "season": {
            "name": season.name,
            "start_date": season.start_date.isoformat() if season.start_date else None,
            "end_date": season.end_date.isoformat() if season.end_date else None,
        },
        "stats": {
            "total_photos": total_photos,
            "total_events": total_events,
            "species_count": len(species_keys),
            "camera_count": len(camera_ids),
            "days_monitored": days_monitored,
        },
        "species": species_list,
    })


# ---------------------------------------------------------------------------
# 2. Activity patterns
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/activity", methods=["GET"]
)
@login_required
def dashboard_activity(pid):
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    detections = _detection_query(pid, season_id).all()

    # Aggregate hourly per species
    species_hourly = {}
    for d in detections:
        key = d.species_key
        if key not in species_hourly:
            species_hourly[key] = [0] * 24
        hourly = _parse_hourly(d.hourly_distribution)
        for i in range(24):
            species_hourly[key][i] += hourly[i]

    result = []
    for key, hourly in species_hourly.items():
        pattern, night_pct, day_pct = _classify_pattern(hourly)
        result.append({
            "species_key": key,
            "hourly": hourly,
            "pattern": pattern,
            "night_pct": night_pct,
            "day_pct": day_pct,
        })

    return jsonify(result)


# ---------------------------------------------------------------------------
# 3. Camera leaderboard
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/cameras", methods=["GET"]
)
@login_required
def dashboard_cameras(pid):
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    detections = _detection_query(pid, season_id).all()

    # Group by camera
    cam_data = {}
    for d in detections:
        cid = d.camera_id
        if cid not in cam_data:
            cam_data[cid] = {
                "total_events": 0,
                "species": {},
            }
        cam_data[cid]["total_events"] += d.independent_events or 0
        key = d.species_key
        cam_data[cid]["species"][key] = (
            cam_data[cid]["species"].get(key, 0) + (d.independent_events or 0)
        )

    # Build response with camera details
    cameras = []
    for cid, data in cam_data.items():
        cam = Camera.query.get(cid)
        if not cam:
            continue
        top_species = max(data["species"], key=data["species"].get) if data["species"] else None
        cameras.append({
            "id": cid,
            "camera_label": cam.camera_label,
            "name": cam.name,
            "lat": cam.lat,
            "lon": cam.lon,
            "placement_context": cam.placement_context,
            "total_events": data["total_events"],
            "species_count": len(data["species"]),
            "top_species": top_species,
        })

    cameras.sort(key=lambda x: x["total_events"], reverse=True)
    return jsonify(cameras)


# ---------------------------------------------------------------------------
# 4. Map data
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/map-data", methods=["GET"]
)
@login_required
def dashboard_map_data(pid):
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    detections = _detection_query(pid, season_id).all()

    # Group detections by camera
    cam_detections = {}
    for d in detections:
        cam_detections.setdefault(d.camera_id, []).append(d)

    # Build camera list
    all_cameras = Camera.query.filter_by(property_id=pid).all()
    camera_list = []
    for cam in all_cameras:
        dets = cam_detections.get(cam.id, [])
        total_events = sum(d.independent_events or 0 for d in dets)
        species = [
            {"key": d.species_key, "events": d.independent_events or 0}
            for d in dets
        ]
        species.sort(key=lambda x: x["events"], reverse=True)
        camera_list.append({
            "id": cam.id,
            "label": cam.camera_label,
            "name": cam.name,
            "lat": cam.lat,
            "lon": cam.lon,
            "placement_context": cam.placement_context,
            "total_events": total_events,
            "species": species,
        })

    return jsonify({
        "boundary_geojson": prop.boundary_geojson,
        "cameras": camera_list,
    })


# ---------------------------------------------------------------------------
# 5. Seasons list
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/seasons", methods=["GET"]
)
@login_required
def list_seasons(pid):
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    seasons = Season.query.filter_by(property_id=pid).order_by(
        Season.start_date.desc()
    ).all()

    return jsonify([
        {
            "id": s.id,
            "name": s.name,
            "start_date": s.start_date.isoformat() if s.start_date else None,
            "end_date": s.end_date.isoformat() if s.end_date else None,
        }
        for s in seasons
    ])


# ---------------------------------------------------------------------------
# 6. Year-over-Year comparison
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/yoy", methods=["GET"]
)
@login_required
def dashboard_yoy(pid):
    """Return year-over-year species comparison across all seasons."""
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    # Fetch all seasons for this property, ordered by start_date
    seasons = Season.query.filter_by(property_id=pid).order_by(
        Season.start_date.asc()
    ).all()

    camera_ids = _camera_ids_for_property(pid)
    if not camera_ids:
        return jsonify({"error": "No cameras found"}), 404

    # Collect detection data per season
    seasons_with_data = []
    season_species = {}  # season_id -> {species_key -> {events, cameras, confidence}}

    for s in seasons:
        detections = DetectionSummary.query.filter(
            DetectionSummary.season_id == s.id,
            DetectionSummary.camera_id.in_(camera_ids),
        ).all()

        if not detections:
            continue

        seasons_with_data.append(s)
        agg = {}
        for d in detections:
            key = d.species_key
            if key not in agg:
                agg[key] = {
                    "events": 0,
                    "camera_ids": set(),
                    "confidence_sum": 0.0,
                    "confidence_count": 0,
                }
            agg[key]["events"] += d.independent_events or 0
            agg[key]["camera_ids"].add(d.camera_id)
            if d.avg_confidence is not None:
                agg[key]["confidence_sum"] += d.avg_confidence
                agg[key]["confidence_count"] += 1

        season_species[s.id] = agg

    # Need at least 2 seasons with data
    if len(seasons_with_data) < 2:
        return jsonify({"error": "Need 2+ seasons with data for comparison"}), 400

    # Build season list
    season_list = [{"id": s.id, "name": s.name} for s in seasons_with_data]

    # Collect all species keys across all seasons
    all_species = set()
    for agg in season_species.values():
        all_species.update(agg.keys())

    # Build species comparison
    species_list = []
    for sp_key in sorted(all_species):
        season_data = []
        for s in seasons_with_data:
            agg = season_species[s.id].get(sp_key)
            if agg:
                avg_conf = (
                    round(agg["confidence_sum"] / agg["confidence_count"], 2)
                    if agg["confidence_count"] > 0 else None
                )
                season_data.append({
                    "season_id": s.id,
                    "events": agg["events"],
                    "cameras": len(agg["camera_ids"]),
                    "confidence": avg_conf,
                })
            else:
                season_data.append({
                    "season_id": s.id,
                    "events": 0,
                    "cameras": 0,
                    "confidence": None,
                })

        # Calculate trend: % change from first to last season
        first_events = season_data[0]["events"]
        last_events = season_data[-1]["events"]
        if first_events > 0:
            trend_pct = round((last_events - first_events) / first_events * 100, 1)
        elif last_events > 0:
            trend_pct = 100.0
        else:
            trend_pct = 0.0

        species_list.append({
            "species_key": sp_key,
            "common_name": COMMON_NAMES.get(sp_key, sp_key.replace("_", " ").title()),
            "seasons": season_data,
            "trend_pct": trend_pct,
        })

    # Sort by absolute trend magnitude (most changed first)
    species_list.sort(key=lambda x: abs(x["trend_pct"]), reverse=True)

    return jsonify({
        "seasons": season_list,
        "species": species_list,
    })


# ---------------------------------------------------------------------------
# 7. Coverage score
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/coverage", methods=["GET"]
)
@login_required
def dashboard_coverage(pid):
    """Calculate and return the coverage score for a property/season."""
    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    # Get cameras for this property
    cameras = Camera.query.filter_by(property_id=pid).all()

    # Calculate days_monitored from DetectionSummary first_seen/last_seen
    camera_ids = _camera_ids_for_property(pid)
    days_monitored = 0
    if camera_ids:
        first_seen = db.session.query(
            func.min(DetectionSummary.first_seen)
        ).filter(
            DetectionSummary.season_id == season_id,
            DetectionSummary.camera_id.in_(camera_ids),
        ).scalar()

        last_seen = db.session.query(
            func.max(DetectionSummary.last_seen)
        ).filter(
            DetectionSummary.season_id == season_id,
            DetectionSummary.camera_id.in_(camera_ids),
        ).scalar()

        if first_seen and last_seen:
            days_monitored = (last_seen - first_seen).days
        elif season.start_date and season.end_date:
            days_monitored = (season.end_date - season.start_date).days

    result = calculate_coverage(
        cameras=cameras,
        property_acreage=prop.acreage or 0,
        boundary_geojson=prop.boundary_geojson,
        days_monitored=days_monitored,
    )

    # Persist to CoverageScore model
    try:
        existing = CoverageScore.query.filter_by(
            property_id=pid, season_id=season_id
        ).first()

        if existing:
            existing.overall_score = result["overall_score"]
            existing.density_score = result["density_score"]
            existing.diversity_score = result["diversity_score"]
            existing.distribution_score = result["distribution_score"]
            existing.temporal_score = result["temporal_score"]
            existing.grade = result["grade"]
            existing.recommendations = json.dumps(result["recommendations"])
        else:
            score = CoverageScore(
                property_id=pid,
                season_id=season_id,
                overall_score=result["overall_score"],
                density_score=result["density_score"],
                diversity_score=result["diversity_score"],
                distribution_score=result["distribution_score"],
                temporal_score=result["temporal_score"],
                grade=result["grade"],
                recommendations=json.dumps(result["recommendations"]),
            )
            db.session.add(score)

        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(result)


@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/photos", methods=["GET"]
)
@login_required
def dashboard_photos(pid):
    """Return photo listings from the sorted output directory.

    Query params:
        species  — filter by species_key (optional)
        camera   — filter by camera label prefix (optional)
        page     — page number, default 1
        per_page — items per page, default 40
    """
    import re
    from pathlib import Path

    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    species_filter = request.args.get("species", "")
    camera_filter = request.args.get("camera", "")
    search_query = request.args.get("q", "").strip().lower()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 40, type=int)

    sorted_dir = (
        Path(__file__).parent.parent.parent.parent / "demo" / "output" / "sorted"
    )
    if not sorted_dir.exists():
        return jsonify({"photos": [], "total": 0, "page": 1, "pages": 0})

    species_dirs = [
        d for d in sorted_dir.iterdir()
        if d.is_dir() and (not species_filter or d.name == species_filter)
    ]

    photos = []
    fname_re = re.compile(
        r"^(CAM-\w+)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(\d+)\.jpg$",
        re.IGNORECASE,
    )

    for sp_dir in sorted(species_dirs):
        sp_key = sp_dir.name
        common = COMMON_NAMES.get(sp_key, sp_key.replace("_", " ").title())
        for img in sorted(sp_dir.glob("*.jpg")):
            m = fname_re.match(img.name)
            if not m:
                continue
            cam = m.group(1)
            if camera_filter and not cam.startswith(camera_filter):
                continue
            photos.append({
                "filename": img.name,
                "species_key": sp_key,
                "common_name": common,
                "camera": cam,
                "date": f"{m.group(2)}-{m.group(3)}-{m.group(4)}",
                "time": f"{m.group(5)}:{m.group(6)}:{m.group(7)}",
                "burst_idx": int(m.group(8)),
                "url": f"/photos/{sp_key}/{img.name}",
            })

    photos.sort(key=lambda p: (p["date"], p["time"]), reverse=True)

    # Apply search query across species name, camera, date
    if search_query:
        photos = [
            p for p in photos
            if search_query in p["common_name"].lower()
            or search_query in p["camera"].lower()
            or search_query in p["date"]
            or search_query in p["species_key"].lower()
        ]

    total = len(photos)
    pages = (total + per_page - 1) // per_page if per_page else 1
    start = (page - 1) * per_page
    paginated = photos[start : start + per_page]

    return jsonify({
        "photos": paginated,
        "total": total,
        "page": page,
        "pages": pages,
        "species_list": sorted(set(p["species_key"] for p in photos)),
    })


# ---------------------------------------------------------------------------
# 9. Population estimates (REM density per species, with CI + caveats)
# ---------------------------------------------------------------------------

@dashboard_api_bp.route(
    "/properties/<int:pid>/dashboard/population", methods=["GET"]
)
@login_required
def dashboard_population(pid):
    """Per-species REM density estimates with bootstrap 95% CIs and
    plain-language caveats / recommendation flags.

    Camera-days for each (camera, species) pair = season length, since
    we don't track per-camera deployment dates yet. When that lands,
    swap to the per-camera active-day count.
    """
    from risk.population import (
        CameraSurveyEffort,
        estimate_for_property,
    )

    prop = _get_user_property(pid)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if not season_id:
        return jsonify({"error": "season_id query parameter required"}), 400

    season = _get_season(season_id, pid)
    if not season:
        return jsonify({"error": "Season not found"}), 404

    season_days = 0
    if season.start_date and season.end_date:
        season_days = max(1, (season.end_date - season.start_date).days)

    # Pull the cameras + their placement_context for caveat generation.
    cameras = {c.id: c for c in
               Camera.query.filter_by(property_id=pid).all()}

    # Build {species_key: [CameraSurveyEffort, ...]} from DetectionSummary.
    detections = _detection_query(pid, season_id).all()
    by_species = {}
    for d in detections:
        cam = cameras.get(d.camera_id)
        if cam is None:
            continue
        eff = CameraSurveyEffort(
            camera_id=d.camera_id,
            camera_days=float(season_days),
            detections=int(d.independent_events or 0),
            placement_context=cam.placement_context,
        )
        by_species.setdefault(d.species_key, []).append(eff)

    estimates = estimate_for_property(by_species)

    return jsonify({
        "property": {
            "id": prop.id,
            "name": prop.name,
            "acreage": prop.acreage,
        },
        "season": {
            "id": season.id,
            "name": season.name,
            "days": season_days,
        },
        "method": {
            "estimator": "Random Encounter Model (Rowcliffe et al. 2008)",
            "ci": "Bootstrap 95% (1000 iterations over cameras + parametric "
                  "perturbation of daily travel distance)",
            "camera_radius_m": settings.CAMERA_DETECTION_RADIUS_M,
            "camera_angle_rad": settings.CAMERA_DETECTION_ANGLE_RAD,
        },
        "estimates": [
            {
                "species_key": e.species_key,
                "common_name": COMMON_NAMES.get(
                    e.species_key, e.species_key.replace("_", " ").title()),
                "detection_rate_per_camera_day": (
                    round(e.detection_rate, 4) if e.detection_rate is not None
                    else None
                ),
                "density_animals_per_km2": (
                    round(e.density_mean, 2) if e.density_mean is not None
                    else None
                ),
                "density_ci_low": (
                    round(e.density_ci_low, 2) if e.density_ci_low is not None
                    else None
                ),
                "density_ci_high": (
                    round(e.density_ci_high, 2) if e.density_ci_high is not None
                    else None
                ),
                "n_cameras": e.n_cameras,
                "total_camera_days": e.total_camera_days,
                "total_detections": e.total_detections,
                "recommendation": e.recommendation,
                "caveats": e.caveats,
                "method_notes": e.method_notes,
                "bootstrap_n": e.bootstrap_n,
            }
            for e in estimates
        ],
    })
