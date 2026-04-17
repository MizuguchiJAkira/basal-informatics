"""Lender-facing routes — Basal Informatics Nature Exposure Reports.

These are the pages a Farm Credit loan officer or ag bank's collateral
reviewer sees. Design intent is compliance-forward:
  - No hero video, no teal consumer accent, no individual-animal tracking
  - Monochrome palette (slate/gray) with tier-specific risk colors
    (green / amber / orange / red) used only for exposure levels
  - Dense, information-first layout; every number has a method note
  - Downloadable PDF report (planned)

Mounted under ``/lender/`` on the ``site="basal"`` Flask app only — the
Strecker hunter-facing app never registers this blueprint.

Access control: requires ``is_owner=True`` at v1 (the same check Basal's
existing owner routes use). In production this splits further into
LenderClient-scoped access — each lender sees only their own parcels.
Deferred until we have more than one lender.
"""
from datetime import date
from functools import wraps

from flask import Blueprint, abort, render_template, request, jsonify
from flask_login import current_user, login_required

from config import settings
from db.models import (Camera, DetectionSummary, LenderClient, Property,
                       Season, db)
from risk.exposure import (TIER_INFO_ONLY, TIER_ORDER, exposure_for_species)
from risk.population import CameraSurveyEffort, estimate_for_property
from risk.proximity import (NEIGHBOR_RADIUS_KM, SOURCE_NEIGHBORING,
                            SOURCE_ON_PARCEL, classify_cameras)

lender_bp = Blueprint(
    "lender", __name__,
    url_prefix="/lender",
    template_folder="../templates/lender",
)


# ---------------------------------------------------------------------------
# Access control — v1: owner-only; v2 will key by LenderClient membership
# ---------------------------------------------------------------------------

def lender_access_required(f):
    """Gate access to lender routes.

    V1: owner (is_owner=True) OR DEMO_MODE. Post-pilot this becomes a
    LenderClient membership check via User.lender_client_id.
    """
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        from flask import current_app
        if current_app.config.get("DEMO_MODE"):
            return f(*args, **kwargs)
        if not getattr(current_user, "is_owner", False):
            abort(404)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Helpers — density + exposure in one pass
# ---------------------------------------------------------------------------

def _compute_parcel_exposures(parcel: Property, season: Season):
    """Run REM + exposure scoring for every species on a parcel+season.

    Returns (species_exposures, stats) where:
      species_exposures: List[ExposureResult] sorted with feral_hog first,
                         then by descending score/density.
      stats: {"total_events", "total_photos", "n_cameras", "n_species",
              "season_days", "primary_tier"}

    This mirrors the dashboard_population API but is rendered server-side
    so the PDF export can share the same code path.
    """
    if not season.start_date or not season.end_date:
        return [], {"season_days": 0, "n_cameras": 0, "n_species": 0,
                    "total_events": 0, "total_photos": 0,
                    "primary_tier": None}

    season_days = max(1, (season.end_date - season.start_date).days)
    cameras = {c.id: c for c in parcel.cameras.all()}
    cam_ids = set(cameras.keys())
    if not cam_ids:
        return [], {"season_days": season_days, "n_cameras": 0, "n_species": 0,
                    "total_events": 0, "total_photos": 0,
                    "primary_tier": None}

    detections = DetectionSummary.query.filter(
        DetectionSummary.season_id == season.id,
        DetectionSummary.camera_id.in_(cam_ids),
    ).all()
    if not detections:
        return [], {"season_days": season_days, "n_cameras": len(cam_ids),
                    "n_species": 0, "total_events": 0, "total_photos": 0,
                    "primary_tier": None}

    total_events = sum(d.independent_events or 0 for d in detections)
    total_photos = sum(d.total_photos or 0 for d in detections)

    efforts_by_species = {}
    for d in detections:
        cam = cameras.get(d.camera_id)
        if not cam:
            continue
        efforts_by_species.setdefault(d.species_key, []).append(
            CameraSurveyEffort(
                camera_id=d.camera_id,
                camera_days=float(season_days),
                detections=int(d.independent_events or 0),
                placement_context=cam.placement_context,
            )
        )

    density_estimates = estimate_for_property(efforts_by_species)

    exposures = []
    for de in density_estimates:
        e = exposure_for_species(
            species_key=de.species_key,
            density_mean=de.density_mean,
            density_ci_low=de.density_ci_low,
            density_ci_high=de.density_ci_high,
            parcel_acreage=parcel.acreage,
            crop_type=parcel.crop_type,
            recommendation=de.recommendation,
            caveats=de.caveats,
            method_notes=de.method_notes,
        )
        exposures.append(e)

    # Feral hog first (headline), then by descending score / density.
    def _key(e):
        primary = 0 if e.species_key == "feral_hog" else 1
        neg_score = -(e.score_0_100 if e.score_0_100 is not None else
                      (e.density_animals_per_km2 or 0))
        return (primary, neg_score)
    exposures.sort(key=_key)

    # Primary tier = the hog tier (if present) else Informational.
    hog_expo = next((e for e in exposures if e.species_key == "feral_hog"), None)
    primary_tier = hog_expo.tier if hog_expo else TIER_INFO_ONLY

    stats = {
        "season_days": season_days,
        "n_cameras": len(cam_ids),
        "n_species": len({d.species_key for d in detections}),
        "total_events": total_events,
        "total_photos": total_photos,
        "primary_tier": primary_tier,
    }
    return exposures, stats


def _neighboring_coverage(parcel: Property, season: Season,
                          cutoff_km: float = NEIGHBOR_RADIUS_KM):
    """Find Strecker / off-parcel cameras within ``cutoff_km`` of the parcel
    boundary and report their detection contributions.

    This is the DetectionIngest bridge: Strecker hunter users on neighboring
    hunting leases contribute supplementary ecological signal for parcels
    with sparse on-parcel coverage. Per strategic spec:
      - No visible link between Strecker and Basal in the UI
      - Report distinguishes own cameras vs neighboring + proximity confidence
      - Neighboring data is SUPPLEMENTARY; does NOT fold into REM density

    Returns:
        {
          "on_parcel_cameras": [<Camera>, ...],
          "neighbors": [
            {
              "camera": <Camera>,
              "distance_km": float,
              "proximity_confidence": float,
              "species_contributions": [{"species_key", "events", "photos"}, ...],
            },
            ...
          ],
          "cutoff_km": float,
        }
    """
    if not parcel.boundary_geojson:
        return {"on_parcel_cameras": list(parcel.cameras.all()),
                "neighbors": [], "cutoff_km": cutoff_km}

    # Pull ALL cameras on properties OTHER than the target parcel.
    # Bounded query: we're on a small-scale pilot so full-table scan is fine.
    # At production scale, pre-filter by lat/lon bbox around the parcel
    # centroid to limit the point-in-polygon / distance work.
    candidates = (Camera.query
                  .filter(Camera.property_id != parcel.id)
                  .filter(Camera.lat.isnot(None), Camera.lon.isnot(None))
                  .all())

    classifications = classify_cameras(candidates, parcel, cutoff_km=cutoff_km)

    on_parcel = list(parcel.cameras.all())
    neighbors = []
    nbr_classifications = [c for c in classifications
                           if c.source == SOURCE_NEIGHBORING]

    if not nbr_classifications or not season:
        return {"on_parcel_cameras": on_parcel,
                "neighbors": [],
                "cutoff_km": cutoff_km}

    # Pull detections for those cameras in the same season so we can report
    # supplementary event counts per species.
    nbr_cam_ids = [c.camera_id for c in nbr_classifications]
    det_rows = DetectionSummary.query.filter(
        DetectionSummary.season_id == season.id,
        DetectionSummary.camera_id.in_(nbr_cam_ids),
    ).all() if nbr_cam_ids else []

    by_cam = {}
    for d in det_rows:
        by_cam.setdefault(d.camera_id, []).append({
            "species_key": d.species_key,
            "events": int(d.independent_events or 0),
            "photos": int(d.total_photos or 0),
        })

    cam_by_id = {c.id: c for c in candidates}
    for cls in nbr_classifications:
        cam = cam_by_id.get(cls.camera_id)
        if not cam:
            continue
        neighbors.append({
            "camera": cam,
            "distance_km": cls.distance_km,
            "proximity_confidence": cls.proximity_confidence,
            "species_contributions": by_cam.get(cam.id, []),
        })

    return {
        "on_parcel_cameras": on_parcel,
        "neighbors": neighbors,
        "cutoff_km": cutoff_km,
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@lender_bp.route("/")
@lender_access_required
def index():
    """Lender home — landing page. Redirect to their portfolio if exactly
    one LenderClient exists; otherwise list all."""
    lenders = LenderClient.query.filter_by(active=True).order_by(
        LenderClient.name).all()
    if len(lenders) == 1:
        from flask import redirect, url_for
        return redirect(url_for("lender.portfolio", lender_slug=lenders[0].slug))
    return render_template("lender/index.html", lenders=lenders)


@lender_bp.route("/<lender_slug>/")
@lender_access_required
def portfolio(lender_slug):
    """Portfolio view — all parcels assigned to one lender with their
    most recent exposure assessment.
    """
    lender = LenderClient.query.filter_by(slug=lender_slug, active=True).first()
    if not lender:
        abort(404)

    parcels = lender.parcels.order_by(Property.name).all()

    # For each parcel, compute the latest-season exposure summary.
    rows = []
    for p in parcels:
        latest_season = (Season.query
                         .filter_by(property_id=p.id)
                         .order_by(Season.end_date.desc(), Season.id.desc())
                         .first())
        if not latest_season:
            rows.append({
                "parcel": p,
                "season": None,
                "hog_tier": "Pending",
                "hog_score": None,
                "hog_density": None,
                "total_events": 0,
                "total_cameras": p.cameras.count(),
                "season_days": 0,
            })
            continue
        exposures, stats = _compute_parcel_exposures(p, latest_season)
        hog = next((e for e in exposures if e.species_key == "feral_hog"), None)
        rows.append({
            "parcel": p,
            "season": latest_season,
            "hog_tier": hog.tier if hog else "No detections",
            "hog_score": hog.score_0_100 if hog else None,
            "hog_density": hog.density_animals_per_km2 if hog else None,
            "total_events": stats["total_events"],
            "total_cameras": stats["n_cameras"],
            "season_days": stats["season_days"],
        })

    # Sort rows: Severe -> Low, then Pending/other last. Density desc as
    # tiebreaker within a tier.
    tier_rank = {t: i for i, t in enumerate(TIER_ORDER)}  # Low=0, Severe=3
    def _sort_key(r):
        tier = r["hog_tier"]
        if tier in tier_rank:
            # Tiers sort first (is_pending=0), descending by rank.
            return (0, -tier_rank[tier], -(r["hog_density"] or 0))
        # Pending / no-detections / unknown go to the bottom.
        return (1, 0, 0)
    rows.sort(key=_sort_key)

    # Portfolio-level tallies for the header.
    tier_counts = {t: 0 for t in TIER_ORDER}
    for r in rows:
        if r["hog_tier"] in tier_counts:
            tier_counts[r["hog_tier"]] += 1

    return render_template(
        "lender/portfolio.html",
        lender=lender,
        rows=rows,
        tier_counts=tier_counts,
        tier_order=TIER_ORDER,
    )


@lender_bp.route("/<lender_slug>/parcel/<int:parcel_id>")
@lender_access_required
def parcel_report(lender_slug, parcel_id):
    """Nature Exposure Report for one parcel."""
    lender = LenderClient.query.filter_by(slug=lender_slug, active=True).first()
    if not lender:
        abort(404)
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        abort(404)

    # Optional season_id override; default to latest.
    season_id = request.args.get("season_id", type=int)
    if season_id:
        season = Season.query.filter_by(id=season_id, property_id=parcel.id).first()
    else:
        season = (Season.query
                  .filter_by(property_id=parcel.id)
                  .order_by(Season.end_date.desc(), Season.id.desc())
                  .first())

    exposures, stats = ([], {"season_days": 0, "n_cameras": 0,
                             "n_species": 0, "total_events": 0,
                             "total_photos": 0, "primary_tier": None})
    if season:
        exposures, stats = _compute_parcel_exposures(parcel, season)

    coverage = _neighboring_coverage(parcel, season)

    return render_template(
        "lender/parcel_report.html",
        lender=lender,
        parcel=parcel,
        season=season,
        exposures=exposures,
        stats=stats,
        coverage=coverage,
        today=date.today(),
    )


@lender_bp.route("/api/<lender_slug>/parcel/<int:parcel_id>/exposure")
@lender_access_required
def parcel_exposure_json(lender_slug, parcel_id):
    """Machine-readable exposure record for downstream integrations.

    Same data as the HTML parcel report, JSON-serialized. Intended for
    lender-side portfolio imports.
    """
    lender = LenderClient.query.filter_by(slug=lender_slug, active=True).first()
    if not lender:
        return jsonify({"error": "Lender not found"}), 404
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        return jsonify({"error": "Parcel not found"}), 404

    season_id = request.args.get("season_id", type=int)
    if season_id:
        season = Season.query.filter_by(id=season_id, property_id=parcel.id).first()
    else:
        season = (Season.query
                  .filter_by(property_id=parcel.id)
                  .order_by(Season.end_date.desc(), Season.id.desc())
                  .first())

    if not season:
        return jsonify({
            "lender": {"slug": lender.slug, "name": lender.name},
            "parcel": {"id": parcel.id, "parcel_id": parcel.parcel_id,
                       "name": parcel.name, "acreage": parcel.acreage,
                       "state": parcel.state, "county": parcel.county,
                       "crop_type": parcel.crop_type},
            "season": None,
            "exposures": [],
            "stats": {},
        })

    exposures, stats = _compute_parcel_exposures(parcel, season)
    coverage = _neighboring_coverage(parcel, season)
    return jsonify({
        "lender": {"slug": lender.slug, "name": lender.name},
        "parcel": {
            "id": parcel.id,
            "parcel_id": parcel.parcel_id,
            "name": parcel.name,
            "acreage": parcel.acreage,
            "state": parcel.state,
            "county": parcel.county,
            "crop_type": parcel.crop_type,
        },
        "coverage": {
            "on_parcel_camera_count": len(coverage["on_parcel_cameras"]),
            "neighbor_camera_count": len(coverage["neighbors"]),
            "cutoff_km": coverage["cutoff_km"],
            "neighbors": [
                {
                    "camera_label": n["camera"].camera_label,
                    "camera_name": n["camera"].name,
                    "distance_km": n["distance_km"],
                    "proximity_confidence": n["proximity_confidence"],
                    "species_contributions": n["species_contributions"],
                }
                for n in coverage["neighbors"]
            ],
        },
        "season": {
            "id": season.id,
            "name": season.name,
            "start_date": season.start_date.isoformat() if season.start_date else None,
            "end_date": season.end_date.isoformat() if season.end_date else None,
        },
        "method": {
            "estimator": "Random Encounter Model (Rowcliffe et al. 2008)",
            "ci": "Bootstrap 95% over cameras + truncated-normal v perturbation",
            "exposure": "Feral Hog Exposure Score (Mayer & Brisbin 2009 bins)",
            "damage_coefficient_usd_per_hog_year": settings.__dict__.get(
                "DEFAULT_PER_HOG_ANNUAL_USD", 405.0),
        },
        "exposures": [
            {
                "species_key": e.species_key,
                "tier": e.tier,
                "score_0_100": round(e.score_0_100, 1) if e.score_0_100 is not None else None,
                "density_animals_per_km2": round(e.density_animals_per_km2, 2) if e.density_animals_per_km2 is not None else None,
                "density_ci_low": round(e.density_ci_low, 2) if e.density_ci_low is not None else None,
                "density_ci_high": round(e.density_ci_high, 2) if e.density_ci_high is not None else None,
                "dollar_projection_annual_usd": e.dollar_projection_annual_usd,
                "dollar_projection_ci_low_usd": e.dollar_projection_ci_low_usd,
                "dollar_projection_ci_high_usd": e.dollar_projection_ci_high_usd,
                "crop_modifier": e.crop_modifier,
                "recommendation": e.recommendation,
                "caveats": e.caveats,
                "method_notes": e.method_notes,
            }
            for e in exposures
        ],
        "stats": stats,
    })
