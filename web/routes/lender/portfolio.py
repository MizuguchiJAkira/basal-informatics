"""Portfolio-level routes — index + per-lender portfolio table.

These are the surfaces a loan officer hits to navigate to a parcel
report. No per-parcel detail logic; that lives in
``parcel_report.py``.
"""

from flask import abort, render_template

from db.models import LenderClient, Property, Season
from risk.exposure import TIER_ORDER

from .blueprint import lender_bp
from .helpers import _compute_parcel_exposures, lender_access_required


@lender_bp.route("/")
@lender_access_required
def index():
    """Lender home — landing page. Redirect to their portfolio if exactly
    one LenderClient exists; otherwise list all."""
    lenders = LenderClient.query.filter_by(active=True).order_by(
        LenderClient.name).all()
    if len(lenders) == 1:
        from flask import redirect, url_for
        return redirect(url_for(
            "lender.portfolio", lender_slug=lenders[0].slug,
        ))
    return render_template("lender/index.html", lenders=lenders)


@lender_bp.route("/<lender_slug>/")
@lender_access_required
def portfolio(lender_slug):
    """Portfolio view — all parcels assigned to one lender with their
    most recent exposure assessment.
    """
    lender = LenderClient.query.filter_by(
        slug=lender_slug, active=True,
    ).first()
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
                "hog_detection_rate": None,
                "total_events": 0,
                "total_cameras": p.cameras.count(),
                "season_days": 0,
            })
            continue
        exposures, stats = _compute_parcel_exposures(p, latest_season)
        hog = next(
            (e for e in exposures if e.species_key == "feral_hog"), None,
        )
        rows.append({
            "parcel": p,
            "season": latest_season,
            "hog_tier": hog.tier if hog else "No detections",
            "hog_score": hog.score_0_100 if hog else None,
            "hog_density": hog.density_animals_per_km2 if hog else None,
            "hog_detection_rate": (
                hog.detection_rate_per_camera_day if hog else None
            ),
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
