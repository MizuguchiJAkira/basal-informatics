"""Shared helpers for the lender route modules.

Three flavors live here, all framework-agnostic where possible:

  * ``lender_access_required`` — the gate decorator the route modules
    apply to every handler.
  * Density / exposure compute helpers — ``_compute_parcel_exposures``,
    ``_neighboring_coverage``, ``_hog_hourly_activity``,
    ``_hog_history``. Pure functions of ``Property`` + ``Season``;
    no Flask coupling.
  * Report-shape helpers — ``_aggregate_accuracy_reports``,
    ``_confidence_grade``, ``_build_exec_summary``. Take the outputs
    of the compute helpers and return dicts the templates expect.

Tests import some of these directly (``_hog_history`` is reached by
``tests/test_invariants.py``); keep the names stable, or update both
sides together.
"""

import json
from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from config import settings
from db.models import (Camera, DetectionSummary, ProcessingJob, Property,
                       Season)
from risk.exposure import (TIER_INFO_ONLY, exposure_for_species)
from risk.population import CameraSurveyEffort, estimate_for_property
from risk.proximity import (NEIGHBOR_RADIUS_KM, SOURCE_NEIGHBORING,
                            classify_cameras)


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
            detection_rate_per_camera_day=de.detection_rate,
            detection_rate_adjusted_per_camera_day=de.detection_rate_adjusted,
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

    # Pull detections for neighbor cameras across any season whose date
    # range overlaps the target parcel's survey window. Neighbor cameras
    # belong to different properties, so their DetectionSummary rows
    # reference different season_id values even when the calendar window
    # is the same. Matching on date overlap (not season_id) is the correct
    # semantics for "data collected during this parcel's survey period."
    nbr_cam_ids = [c.camera_id for c in nbr_classifications]
    if nbr_cam_ids and season.start_date and season.end_date:
        det_rows = (DetectionSummary.query
                    .join(Season, Season.id == DetectionSummary.season_id)
                    .filter(DetectionSummary.camera_id.in_(nbr_cam_ids))
                    .filter(Season.start_date <= season.end_date)
                    .filter(Season.end_date >= season.start_date)
                    .all())
    else:
        det_rows = []

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
# Continuous-monitoring trend
# ---------------------------------------------------------------------------

def _hog_hourly_activity(parcel, season) -> list:
    """Aggregate hog hourly-distribution arrays across all cameras in
    this parcel+season. Returns a 24-element list of event counts
    (index 0 = midnight-1am, index 23 = 11pm-midnight).

    Drives the temporal-activity sparkline on the parcel report.
    Peaks during 20:00-04:00 are the ecological signature of
    nocturnal hog behavior — an immediately-readable credibility
    signal for a reviewer.
    """
    if not season or not season.id:
        return [0] * 24
    rows = (DetectionSummary.query
            .join(Camera, Camera.id == DetectionSummary.camera_id)
            .filter(Camera.property_id == parcel.id)
            .filter(DetectionSummary.season_id == season.id)
            .filter(DetectionSummary.species_key == "feral_hog")
            .all())
    totals = [0] * 24
    for r in rows:
        h24 = r.hourly_distribution or []
        if isinstance(h24, str):
            try:
                h24 = json.loads(h24)
            except (ValueError, TypeError):
                h24 = []
        for i, v in enumerate(h24[:24]):
            try:
                totals[i] += int(v)
            except (TypeError, ValueError):
                pass
    return totals


def _hog_history(parcel) -> list:
    """Compute hog exposure across every season on this parcel, oldest
    first. Drives the trend widget on the parcel report and the
    `pipeline.history` array in the JSON API.

    Each entry: {season, hog_exposure, stats}. `hog_exposure` is the
    feral_hog ExposureResult (or None if no hog detections that
    season); `season` is the SQLAlchemy Season row; `stats` is the
    same dict shape _compute_parcel_exposures returns.
    """
    seasons = (Season.query
               .filter_by(property_id=parcel.id)
               .filter(Season.start_date.isnot(None))
               .filter(Season.end_date.isnot(None))
               .order_by(Season.start_date.asc(), Season.id.asc())
               .all())
    out = []
    for s in seasons:
        sx, sst = _compute_parcel_exposures(parcel, s)
        hog = next((e for e in sx if e.species_key == "feral_hog"), None)
        out.append({"season": s, "hog_exposure": hog, "stats": sst})
    return out


# ---------------------------------------------------------------------------
# Accuracy aggregation (from filename-labeled uploads)
# ---------------------------------------------------------------------------

def _aggregate_accuracy_reports(parcel):
    """Aggregate classifier accuracy telemetry across every completed
    ProcessingJob for this parcel that carried hunter-labeled photos.

    Each ProcessingJob.accuracy_report_json is produced by
    strecker/filename_labels.py::build_accuracy_report when an uploaded
    ZIP contains filenames like "CF Pig 2025-05-19 Goldilocks MH.JPG"
    (ground-truth species tokens). Jobs without labeled photos leave
    the column NULL and are ignored here.

    When a parcel accumulates multiple labeled-upload jobs (different
    survey windows, different hunters), we sum the scalar counters and
    merge the per_species buckets: labeled/matched/missed add, and
    confused_as dicts merge key-by-key.

    Returns None when no job on this parcel has accuracy data — the
    template uses this to skip the section entirely.
    """
    jobs = (ProcessingJob.query
            .filter(ProcessingJob.property_id == parcel.id)
            .filter(ProcessingJob.accuracy_report_json.isnot(None))
            .all())
    if not jobs:
        return None

    totals = {"n_total": 0, "n_labeled": 0, "n_matched": 0,
              "n_missed": 0, "n_confused": 0}
    per_species = {}
    n_jobs = 0

    for pj in jobs:
        raw = pj.accuracy_report_json
        if not raw:
            continue
        try:
            rep = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        if not isinstance(rep, dict):
            continue
        n_jobs += 1
        for k in totals:
            totals[k] += int(rep.get(k) or 0)
        for sp, bucket in (rep.get("per_species") or {}).items():
            if not isinstance(bucket, dict):
                continue
            agg = per_species.setdefault(
                sp,
                {"labeled": 0, "matched": 0, "missed": 0, "confused_as": {}},
            )
            agg["labeled"] += int(bucket.get("labeled") or 0)
            agg["matched"] += int(bucket.get("matched") or 0)
            agg["missed"] += int(bucket.get("missed") or 0)
            for other, n in (bucket.get("confused_as") or {}).items():
                agg["confused_as"][other] = (
                    agg["confused_as"].get(other, 0) + int(n or 0)
                )

    if n_jobs == 0 or totals["n_labeled"] == 0:
        return None

    # Stable display order: most-labeled species first, then alpha.
    per_species_rows = []
    for sp, agg in sorted(per_species.items(),
                          key=lambda kv: (-kv[1]["labeled"], kv[0])):
        confused_parts = [
            f"{other.replace('_', ' ')} ×{n}"
            for other, n in sorted(
                agg["confused_as"].items(), key=lambda kv: (-kv[1], kv[0])
            )
            if n > 0
        ]
        per_species_rows.append({
            "species_key": sp,
            "species_label": sp.replace("_", " ").title(),
            "labeled": agg["labeled"],
            "matched": agg["matched"],
            "missed": agg["missed"],
            "confused_as": ", ".join(confused_parts) if confused_parts else "—",
        })

    pct = (100.0 * totals["n_matched"] / totals["n_labeled"]
           if totals["n_labeled"] else 0.0)

    return {
        "n_jobs": n_jobs,
        "n_total": totals["n_total"],
        "n_labeled": totals["n_labeled"],
        "n_matched": totals["n_matched"],
        "n_missed": totals["n_missed"],
        "n_confused": totals["n_confused"],
        "pct_matched": pct,
        "per_species": per_species_rows,
    }


# ---------------------------------------------------------------------------
# Report-shape helpers
# ---------------------------------------------------------------------------

def _confidence_grade(exposures, stats) -> dict:
    """Assign a data-quality grade (A/B/C/D) and list the gaps driving it.

    Mirrors the confidence.py PDF section. The grade is a simple
    rubric over four evidence dimensions; each dimension scores
    ✓ (2pt), ~ (1pt), or ✗ (0pt). Total out of 8.

      A = 7-8, B = 5-6, C = 3-4, D = 0-2.

    Rubric:
      - Camera-days: >=200 = ✓, >=100 = ~, else ✗ (settings threshold)
      - Detections (hog): >=100 = ✓, >=20 = ~, else ✗
      - Placement diversity: random anchor AND >=2 contexts = ✓,
                             random-only or contexts-only = ~,
                             none = ✗
      - CI tightness: CI upper/lower <= 1.5 = ✓, <= 3.0 = ~, else ✗
    """
    hog = next((e for e in exposures if e.species_key == "feral_hog"), None)
    cam_days = stats.get("season_days", 0) * stats.get("n_cameras", 0)
    events = stats.get("total_events", 0)

    def _row(label, score, detail):
        mark = "✓" if score == 2 else ("~" if score == 1 else "✗")
        return {"label": label, "score": score, "mark": mark, "detail": detail}

    rows = []

    # Camera-days
    if cam_days >= 200:
        rows.append(_row("Camera-days", 2,
                         f"{cam_days} camera-days across the survey."))
    elif cam_days >= settings.MIN_CAMERA_DAYS_FOR_DENSITY:
        rows.append(_row("Camera-days", 1,
                         f"{cam_days} camera-days (above "
                         f"{settings.MIN_CAMERA_DAYS_FOR_DENSITY}-day floor, "
                         f"below decision-grade)."))
    else:
        rows.append(_row("Camera-days", 0,
                         f"{cam_days} camera-days (below "
                         f"{settings.MIN_CAMERA_DAYS_FOR_DENSITY}-day floor)."))

    # Detections — use hog count specifically for the hog tier call
    if events >= 100:
        rows.append(_row("Detection count", 2,
                         f"{events} independent events across species."))
    elif events >= settings.MIN_DETECTIONS_FOR_DENSITY:
        rows.append(_row("Detection count", 1,
                         f"{events} events (above "
                         f"{settings.MIN_DETECTIONS_FOR_DENSITY}-event floor)."))
    else:
        rows.append(_row("Detection count", 0,
                         f"{events} events (below "
                         f"{settings.MIN_DETECTIONS_FOR_DENSITY}-event floor)."))

    # Placement diversity: how many distinct placement contexts AND random anchor?
    # exposures don't carry context; pull from stats if we stashed it. Fall back
    # to scanning parcel.cameras via the template-exposed hog_caveats.
    # Simpler: infer from hog caveats.
    hog_caveats = (hog.caveats if hog else []) or []
    no_random = any("no random-placement" in c.lower() for c in hog_caveats)
    if hog and hog.detection_rate_adjusted_per_camera_day is not None and not no_random:
        rows.append(_row("Placement diversity", 2,
                         "Random-placement anchor present; IPW correction "
                         "validated against an unbiased reference."))
    elif hog and hog.detection_rate_adjusted_per_camera_day is not None:
        rows.append(_row("Placement diversity", 1,
                         "IPW correction applied but no random-placement "
                         "anchor in this deployment."))
    else:
        rows.append(_row("Placement diversity", 0,
                         "No placement-context bias correction applied."))

    # CI tightness
    if hog and hog.density_ci_low and hog.density_ci_high and hog.density_ci_low > 0:
        ratio = hog.density_ci_high / hog.density_ci_low
        if ratio <= 1.5:
            rows.append(_row("CI tightness", 2,
                             f"Density CI ratio {ratio:.2f} (decision-grade)."))
        elif ratio <= 3.0:
            rows.append(_row("CI tightness", 1,
                             f"Density CI ratio {ratio:.2f} (supplementary "
                             f"survey would tighten this)."))
        else:
            rows.append(_row("CI tightness", 0,
                             f"Density CI ratio {ratio:.2f} — wide; "
                             f"additional cameras or survey days needed."))
    else:
        rows.append(_row("CI tightness", 0,
                         "CI not computable (insufficient data)."))

    total = sum(r["score"] for r in rows)
    grade = "A" if total >= 7 else ("B" if total >= 5 else
             ("C" if total >= 3 else "D"))
    return {"grade": grade, "score": total, "max": 8, "rows": rows}


def _build_exec_summary(parcel, season, exposures, hog_history) -> dict:
    """Return {headline, bullets: [str,...]} — the committee-readable
    one-glance findings block at the top of the parcel report.

    The headline is the hog tier + density + CI. Bullets cover the
    trend (if any prior season exists), the recommendation, and any
    hard caveats (e.g. no-random-placement anchor).
    """
    hog = next((e for e in exposures if e.species_key == "feral_hog"), None)
    if not hog:
        return {
            "headline": "No feral hog detections this survey period.",
            "bullets": [],
        }

    pieces = []
    if hog.density_animals_per_km2 is not None:
        headline = (
            f"Feral Hog Exposure: {hog.tier} — "
            f"{hog.density_animals_per_km2:.2f} animals/km² "
            f"(95% CI {hog.density_ci_low:.2f}–{hog.density_ci_high:.2f})."
        )
    else:
        headline = f"Feral Hog Exposure: {hog.tier} — density not estimated."

    # Trend bullet
    if hog_history and len(hog_history) >= 2:
        first = hog_history[0].get("hog_exposure")
        last = hog_history[-1].get("hog_exposure")
        if (first and last
                and first.density_animals_per_km2 is not None
                and last.density_animals_per_km2 is not None
                and first.density_animals_per_km2 > 0):
            delta = last.density_animals_per_km2 - first.density_animals_per_km2
            pct = delta / first.density_animals_per_km2 * 100
            tier_note = (f"; tier {first.tier} → {last.tier}"
                         if first.tier != last.tier else "")
            pieces.append(
                f"Density {'+' if delta >= 0 else ''}{delta:.2f}/km² "
                f"({pct:+.0f}%) since {hog_history[0]['season'].name}{tier_note}."
            )

    # Recommendation
    if hog.recommendation == "sufficient_for_decision":
        pieces.append("Confidence interval within decision-grade width; "
                      "data sufficient for collateral review.")
    elif hog.recommendation == "recommend_supplementary_survey":
        pieces.append("Confidence interval exceeds decision-grade width "
                      "(>1.5× ratio); supplementary survey recommended.")
    else:
        pieces.append("Sample size below density-estimate threshold; "
                      "extend survey period or add cameras.")

    # Key caveat
    hard_caveats = [c for c in (hog.caveats or [])
                    if "no random-placement" in c.lower()
                    or "ess" in c.lower() and "below" in c.lower()]
    if hard_caveats:
        pieces.append(hard_caveats[0])

    return {"headline": headline, "bullets": pieces}
