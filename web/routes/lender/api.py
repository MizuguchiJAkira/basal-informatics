"""JSON API endpoints for the lender surface.

Two endpoints today:

  * ``GET  /api/<slug>/parcel/<id>/exposure``
        Machine-readable exposure record. Same data as the HTML
        parcel report, JSON-serialized. For lender-side portfolio
        importers and downstream integrations.

  * ``POST /api/<slug>/parcel/<id>/valuation/override``
        Set or clear the underwriter override on a parcel's risk
        band. Writes to ``parcel_valuation_status`` and appends a
        row to ``valuation_override_history``.

Both are CSRF-exempted at app-init time
(see ``web/app.py``); JSON clients authenticate via session, not
form cookie. The override endpoint also enforces is_owner directly
(defense-in-depth on top of ``lender_access_required``) so that a
``DEMO_MODE=True`` deploy can't leak write access.
"""

import threading as _threading
import time as _time
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user

from config import settings
from db.models import LenderClient, Property, Season

from .blueprint import lender_bp
from .helpers import (
    _compute_parcel_exposures,
    _hog_history,
    _neighboring_coverage,
    lender_access_required,
)


# ---------------------------------------------------------------------------
# Stage 7 underwriter override — write path.
#
# Tiny in-process rate limiter. For an endpoint that should see fewer
# than 10 calls/user/day under normal use, a per-worker in-memory dict
# is sufficient to stop accidents (misconfigured client, infinite-loop
# bug). It does not stop a determined adversary spreading N×workers
# requests; for that, plug Flask-Limiter against Redis. Documented as
# a known limitation rather than papered over.
# ---------------------------------------------------------------------------

_OVERRIDE_RATE_WINDOW_SEC = 60.0
_OVERRIDE_RATE_MAX_CALLS = 12     # per user per minute per worker
_override_rate_lock = _threading.Lock()
_override_rate_log: dict[int, list[float]] = {}


def _override_rate_check(user_id: int) -> bool:
    """Return True if the user is under the override-write rate cap."""
    now = _time.monotonic()
    with _override_rate_lock:
        events = _override_rate_log.setdefault(user_id, [])
        cutoff = now - _OVERRIDE_RATE_WINDOW_SEC
        # Drop expired events. List grows at most max_calls per window.
        events[:] = [t for t in events if t >= cutoff]
        if len(events) >= _OVERRIDE_RATE_MAX_CALLS:
            return False
        events.append(now)
        return True


# ---------------------------------------------------------------------------
# Exposure JSON
# ---------------------------------------------------------------------------

@lender_bp.route("/api/<lender_slug>/parcel/<int:parcel_id>/exposure")
@lender_access_required
def parcel_exposure_json(lender_slug, parcel_id):
    """Machine-readable exposure record for downstream integrations.

    Same data as the HTML parcel report, JSON-serialized. Intended for
    lender-side portfolio imports.
    """
    lender = LenderClient.query.filter_by(
        slug=lender_slug, active=True,
    ).first()
    if not lender:
        return jsonify({"error": "Lender not found"}), 404
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        return jsonify({"error": "Parcel not found"}), 404

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
    hog_history = _hog_history(parcel)
    history_json = [
        {
            "season_id": h["season"].id,
            "season_name": h["season"].name,
            "period_start": (
                h["season"].start_date.isoformat()
                if h["season"].start_date else None
            ),
            "period_end": (
                h["season"].end_date.isoformat()
                if h["season"].end_date else None
            ),
            "tier": h["hog_exposure"].tier if h["hog_exposure"] else None,
            "score_0_100": (
                round(h["hog_exposure"].score_0_100, 1)
                if h["hog_exposure"]
                and h["hog_exposure"].score_0_100 is not None else None
            ),
            "density_animals_per_km2": (
                round(h["hog_exposure"].density_animals_per_km2, 2)
                if h["hog_exposure"]
                and h["hog_exposure"].density_animals_per_km2 is not None
                else None
            ),
            "density_ci_low": (
                round(h["hog_exposure"].density_ci_low, 2)
                if h["hog_exposure"]
                and h["hog_exposure"].density_ci_low is not None else None
            ),
            "density_ci_high": (
                round(h["hog_exposure"].density_ci_high, 2)
                if h["hog_exposure"]
                and h["hog_exposure"].density_ci_high is not None else None
            ),
            "detection_rate_per_camera_day": (
                round(h["hog_exposure"].detection_rate_per_camera_day, 4)
                if h["hog_exposure"]
                and h["hog_exposure"].detection_rate_per_camera_day is not None
                else None
            ),
            "detection_rate_adjusted_per_camera_day": (
                round(h["hog_exposure"].detection_rate_adjusted_per_camera_day, 4)
                if h["hog_exposure"]
                and h["hog_exposure"].detection_rate_adjusted_per_camera_day is not None
                else None
            ),
        }
        for h in hog_history
    ]
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
            "start_date": (
                season.start_date.isoformat() if season.start_date else None
            ),
            "end_date": (
                season.end_date.isoformat() if season.end_date else None
            ),
        },
        "method": {
            "estimator": "Random Encounter Model (Rowcliffe et al. 2008)",
            "ci": ("Bootstrap 95% over cameras + truncated-normal v "
                   "perturbation"),
            "exposure": ("Feral Hog Exposure Score "
                         "(Mayer & Brisbin 2009 bins)"),
            "damage_coefficient_usd_per_hog_year": settings.__dict__.get(
                "DEFAULT_PER_HOG_ANNUAL_USD", 405.0),
        },
        "exposures": [
            {
                "species_key": e.species_key,
                # --- Pipeline-native outputs (camera-trap data → REM) ---
                "pipeline": {
                    "tier": e.tier,
                    "score_0_100": (
                        round(e.score_0_100, 1)
                        if e.score_0_100 is not None else None
                    ),
                    "density_animals_per_km2": (
                        round(e.density_animals_per_km2, 2)
                        if e.density_animals_per_km2 is not None else None
                    ),
                    "density_ci_low": (
                        round(e.density_ci_low, 2)
                        if e.density_ci_low is not None else None
                    ),
                    "density_ci_high": (
                        round(e.density_ci_high, 2)
                        if e.density_ci_high is not None else None
                    ),
                    "detection_rate_per_camera_day": (
                        round(e.detection_rate_per_camera_day, 4)
                        if e.detection_rate_per_camera_day is not None
                        else None
                    ),
                    "detection_rate_adjusted_per_camera_day": (
                        round(e.detection_rate_adjusted_per_camera_day, 4)
                        if e.detection_rate_adjusted_per_camera_day is not None
                        else None
                    ),
                    "recommendation": e.recommendation,
                    "caveats": e.caveats,
                    "method_notes": e.method_notes,
                    # Continuous-monitoring trend across every season
                    # surveyed on this parcel. Only attached to the
                    # feral_hog entry at v1 since that's the only
                    # species with a tier classifier.
                    "history": (
                        history_json if e.species_key == "feral_hog" else []
                    ),
                },
                # --- Supplementary modeled projection (third-party loss data) ---
                # Explicitly nested to signal to downstream importers that
                # these are NOT pipeline outputs. Scaled from Anderson et al.
                # 2016 per-hog damage figures and APHIS Wildlife Services
                # state-level reporting, with a crop-specific modifier.
                "supplementary_projection": {
                    "label": "MODELED PROJECTION",
                    "disclaimer": (
                        "Not a pipeline output. Derived from "
                        "third-party loss data (Anderson et al. 2016 "
                        "per-hog damage figures × parcel area × "
                        "crop modifier). Intended as context for "
                        "loan-review committees that have not yet "
                        "built their own damage model; a committee "
                        "with an internal model should consume the "
                        "pipeline outputs above instead."
                    ),
                    "annual_damage_usd": e.dollar_projection_annual_usd,
                    "annual_damage_ci_low_usd":
                        e.dollar_projection_ci_low_usd,
                    "annual_damage_ci_high_usd":
                        e.dollar_projection_ci_high_usd,
                    "crop_modifier": e.crop_modifier,
                    "per_hog_annual_usd": e.per_hog_annual_usd,
                    "source": (
                        "Anderson et al. 2016; APHIS Wildlife Services "
                        "annual Program Data Reports"
                    ),
                } if e.dollar_projection_annual_usd is not None else None,
            }
            for e in exposures
        ],
        "stats": stats,
    })


# ---------------------------------------------------------------------------
# Stage 7 underwriter override — POST endpoint.
#
# UI for this surface is deferred (v1.1); the data path exists now so a
# lender pilot can override an indicative band manually via the API while
# the dashboard is in flight. Override sets the band to the supplied
# value and stamps the time + acting user; clearing it (POST with body
# ``{"clear": true}``) restores the computed band as the effective one.
# ---------------------------------------------------------------------------

@lender_bp.route(
    "/api/<lender_slug>/parcel/<int:parcel_id>/valuation/override",
    methods=["POST"],
)
@lender_access_required
def parcel_valuation_override(lender_slug, parcel_id):
    """Set or clear the underwriter override on a parcel's risk band."""
    from db.models import (
        ParcelValuationStatus, ValuationOverrideHistory, db as _db,
    )

    # Defense-in-depth: ``lender_access_required`` lets any authenticated
    # user through when DEMO_MODE is set, which is correct for reads but
    # too permissive for a write that lands in the audit trail. Require
    # is_owner unconditionally for the write path. Real LenderClient-
    # membership gating lands when User.lender_client_id ships.
    if not getattr(current_user, "is_owner", False):
        return jsonify({"error": "forbidden"}), 403

    # Rate-limit. Stops accidental spam (loop bug, misconfigured client).
    if not _override_rate_check(current_user.id):
        return jsonify({
            "error": "rate limit exceeded",
            "limit": f"{_OVERRIDE_RATE_MAX_CALLS} per "
                     f"{int(_OVERRIDE_RATE_WINDOW_SEC)}s per user",
        }), 429

    lender = LenderClient.query.filter_by(
        slug=lender_slug, active=True,
    ).first()
    if not lender:
        return jsonify({"error": "lender not found"}), 404
    parcel = Property.query.get(parcel_id)
    if not parcel or parcel.lender_client_id != lender.id:
        return jsonify({"error": "parcel not found"}), 404

    body = request.get_json(silent=True) or {}

    status = (
        ParcelValuationStatus.query
        .filter_by(parcel_id=parcel.id).first()
    )
    if not status:
        return jsonify(
            {"error": "no valuation status computed yet for this parcel"},
        ), 409

    # Capture the prior state BEFORE we mutate, for the history row.
    prev_band = status.underwriter_override
    new_notes = None

    if body.get("clear"):
        status.underwriter_override = None
        status.underwriter_notes = None
        status.override_at = None
        status.override_by_user_id = None
    else:
        band = (body.get("band") or "").strip().lower()
        if band not in ("low", "moderate", "elevated", "high"):
            return jsonify(
                {"error": "band must be one of low|moderate|elevated|high"},
            ), 400
        new_notes = (body.get("notes") or "").strip() or None
        status.underwriter_override = band
        status.underwriter_notes = new_notes
        status.override_at = datetime.utcnow()
        status.override_by_user_id = (
            current_user.id if current_user.is_authenticated else None
        )

    # Append-only audit log. One row per change; never updated.
    _db.session.add(
        ValuationOverrideHistory(
            parcel_valuation_status_id=status.id,
            prev_band=prev_band,
            new_band=status.underwriter_override,
            notes=new_notes,
            set_by_user_id=(
                current_user.id if current_user.is_authenticated else None
            ),
            set_at=datetime.utcnow(),
        )
    )
    _db.session.commit()
    return jsonify({
        "parcel_id": parcel.parcel_id,
        "underwriter_override": status.underwriter_override,
        "underwriter_notes": status.underwriter_notes,
        "override_at": (
            status.override_at.isoformat()
            if status.override_at else None
        ),
    })
