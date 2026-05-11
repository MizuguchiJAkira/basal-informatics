"""Parcel-level HTML report — the single biggest user-facing surface.

``parcel_report()`` is the route a loan-review committee opens dozens
of times per pilot. It composes outputs from every domain module
(risk, bias, valuation) into one Jinja render.

``parcel_upload_form()`` is the small landowner-facing companion —
serves the upload-page shell; all real work happens through
``/api/parcels/<id>/uploads/*``.
"""

from datetime import date

from flask import abort, current_app, render_template, request

from db.models import LenderClient, Property, Season

from .blueprint import lender_bp
from .helpers import (
    _aggregate_accuracy_reports,
    _build_exec_summary,
    _compute_parcel_exposures,
    _confidence_grade,
    _hog_history,
    _hog_hourly_activity,
    _neighboring_coverage,
    lender_access_required,
)


@lender_bp.route("/<lender_slug>/parcel/<int:parcel_id>")
@lender_access_required
def parcel_report(lender_slug, parcel_id):
    """Nature Exposure Report for one parcel."""
    lender = LenderClient.query.filter_by(
        slug=lender_slug, active=True,
    ).first()
    if not lender:
        abort(404)
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        abort(404)

    # Optional season_id override; default to latest.
    season_id = request.args.get("season_id", type=int)
    if season_id:
        season = Season.query.filter_by(
            id=season_id, property_id=parcel.id,
        ).first()
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

    # Continuous-monitoring trend: compute hog exposure across every
    # historical season for this parcel. The lender's wedge against
    # a $40K point-in-time field survey is exactly this — they see
    # the trajectory, not a snapshot.
    hog_history = _hog_history(parcel)

    # Season-over-season delta — answers "is this parcel getting worse?"
    # at a glance. Compares the active season's hog density to the most
    # recent prior season that has a hog density.
    season_delta = None
    if season and hog_history:
        cur_idx = next(
            (i for i, h in enumerate(hog_history)
             if h["season"].id == season.id), None,
        )
        if cur_idx is not None and cur_idx > 0:
            cur = hog_history[cur_idx].get("hog_exposure")
            for j in range(cur_idx - 1, -1, -1):
                prior = hog_history[j].get("hog_exposure")
                if (cur and prior
                        and prior.density_animals_per_km2
                        and cur.density_animals_per_km2 is not None):
                    pct = (
                        (cur.density_animals_per_km2
                         - prior.density_animals_per_km2)
                        / prior.density_animals_per_km2 * 100.0
                    )
                    season_delta = {
                        "pct": pct,
                        "prior_season": hog_history[j]["season"].name,
                        "prior_density": prior.density_animals_per_km2,
                        "current_density": cur.density_animals_per_km2,
                    }
                    break

    # Demo fallback: only one season is seeded, so the real delta path
    # above produces nothing. Synthesize a plausible prior-season number
    # so the trend badge has something to render in the demo deck.
    if season_delta is None and current_app.config.get("DEMO_MODE"):
        cur_hog_for_demo = next(
            (e for e in exposures if e.species_key == "feral_hog"), None,
        )
        if cur_hog_for_demo and cur_hog_for_demo.density_animals_per_km2:
            cur_d = cur_hog_for_demo.density_animals_per_km2
            prior_d = cur_d / 1.18  # current is +18% vs prior
            season_delta = {
                "pct": (cur_d - prior_d) / prior_d * 100.0,
                "prior_season": "Fall 2024",
                "prior_density": prior_d,
                "current_density": cur_d,
            }

    # Portfolio percentile — answers "is this parcel worse than the rest
    # of the book?" Computes hog density for every other parcel in this
    # lender's portfolio (latest season each), then ranks this parcel.
    portfolio_pct = None
    cur_hog = next(
        (e for e in exposures if e.species_key == "feral_hog"), None,
    )
    if cur_hog and cur_hog.density_animals_per_km2 is not None:
        sibling_densities = []
        for sib in lender.parcels.all():
            if sib.id == parcel.id:
                continue
            ls = (Season.query
                  .filter_by(property_id=sib.id)
                  .order_by(Season.end_date.desc(), Season.id.desc())
                  .first())
            if not ls:
                continue
            sx, _ = _compute_parcel_exposures(sib, ls)
            sh = next(
                (e for e in sx if e.species_key == "feral_hog"), None,
            )
            if sh and sh.density_animals_per_km2 is not None:
                sibling_densities.append(sh.density_animals_per_km2)
        # Need at least one peer to make a percentile meaningful.
        if sibling_densities:
            n = len(sibling_densities)
            below = sum(
                1 for d in sibling_densities
                if d < cur_hog.density_animals_per_km2
            )
            # Standard "percent of peers strictly below" framing.
            portfolio_pct = {
                "pct": round(below / n * 100),
                "n_peers": n,
                "lender_name": lender.name,
            }

    # Shape the camera sets the parcel map expects. Lat/lon come from
    # landowner-registered setup; placement_context drives the IPW
    # bias-correction factor and the pin color on the map.
    on_parcel_cams_json = [
        {
            "label": c.camera_label or f"camera-{c.id}",
            "name": c.name or "",
            "lat": c.lat, "lon": c.lon,
            "placement_context": c.placement_context or "unknown",
            "installed_date": (
                c.installed_date.isoformat() if c.installed_date else None
            ),
            "source": "on_parcel",
        }
        for c in coverage.get("on_parcel_cameras", [])
        if c.lat is not None and c.lon is not None
    ]
    neighbor_cams_json = [
        {
            "label": n["camera"].camera_label or f"camera-{n['camera'].id}",
            "name": n["camera"].name or "",
            "lat": n["camera"].lat, "lon": n["camera"].lon,
            "placement_context": n["camera"].placement_context or "unknown",
            "installed_date": (n["camera"].installed_date.isoformat()
                               if n["camera"].installed_date else None),
            "distance_km": float(n.get("distance_km") or 0.0),
            "source": "neighbor",
        }
        for n in coverage.get("neighbors", [])
        if n["camera"].lat is not None and n["camera"].lon is not None
    ]

    # Temporal activity (hog-only, hourly distribution across all
    # cameras for this season). Mirrors the temporal.py PDF section.
    hog_hourly = _hog_hourly_activity(parcel, season)
    hog_peak_hour = (
        hog_hourly.index(max(hog_hourly)) if any(hog_hourly) else None
    )

    # Executive summary — 2-3 sentences a loan-review committee member
    # can read and close the report without scrolling further.
    exec_summary = _build_exec_summary(parcel, season, exposures, hog_history)

    # Data-confidence grade (A-D) with per-dimension rubric.
    confidence = _confidence_grade(exposures, stats)

    # Classifier accuracy — only surfaces when a ProcessingJob on this
    # parcel carried hunter-labeled filenames (ground truth); otherwise
    # the section is omitted entirely from the template.
    accuracy = _aggregate_accuracy_reports(parcel)

    # Station code → placement_context mappings the landowner has
    # registered (see web/routes/api/camera_stations.py). Rendered in
    # the camera-setup appendix so the reader can see how the IPW
    # correction's per-camera context was assigned. Empty list when
    # no codes have been mapped yet.
    from db.models import CameraStation
    station_mappings = (
        CameraStation.query
        .filter_by(property_id=parcel.id)
        .order_by(CameraStation.station_code.asc())
        .all()
    )

    # Stage 7 — Texas Ag Valuation Risk. Gated by FEATURE_VALUATION_RISK
    # so a lender pilot that doesn't want this section yet sees the
    # report exactly as before. Returns None for parcels with no
    # registered CAD adapter (other Brazos parcels in the demo book),
    # which the template treats as "render the rest of the report
    # without this section."
    valuation_risk = None
    if current_app.config.get("FEATURE_VALUATION_RISK"):
        from valuation.compute import for_parcel as _vr_for_parcel
        try:
            valuation_risk = _vr_for_parcel(parcel)
        except Exception:
            # A failure here must not break the rest of the parcel
            # report — the section is additive. But silent failures hide
            # CAD-adapter regressions and reference-data drift, so log
            # with full context (parcel + traceback) at error level.
            current_app.logger.exception(
                "valuation.compute.for_parcel failed",
                extra={
                    "parcel_id": parcel.id,
                    "parcel_external_id": parcel.parcel_id,
                    "lender_slug": lender_slug,
                    "county": parcel.county,
                },
            )
            valuation_risk = None

    return render_template(
        "lender/parcel_report.html",
        lender=lender,
        parcel=parcel,
        season=season,
        exposures=exposures,
        stats=stats,
        coverage=coverage,
        hog_history=hog_history,
        hog_hourly=hog_hourly,
        hog_peak_hour=hog_peak_hour,
        exec_summary=exec_summary,
        confidence=confidence,
        accuracy=accuracy,
        station_mappings=station_mappings,
        on_parcel_cams_json=on_parcel_cams_json,
        neighbor_cams_json=neighbor_cams_json,
        season_delta=season_delta,
        portfolio_pct=portfolio_pct,
        today=date.today(),
        valuation_risk=valuation_risk,
    )


@lender_bp.route("/<lender_slug>/parcel/<int:parcel_id>/upload")
@lender_access_required
def parcel_upload_form(lender_slug, parcel_id):
    """Landowner-facing upload form for a parcel.

    Drag-drop ZIP, progress bar, status polling. All work happens
    browser-side against /api/parcels/<id>/uploads/* — this route just
    renders the HTML shell.
    """
    lender = LenderClient.query.filter_by(
        slug=lender_slug, active=True,
    ).first()
    if not lender:
        abort(404)
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        abort(404)
    return render_template(
        "lender/parcel_upload.html",
        lender=lender,
        parcel=parcel,
    )
