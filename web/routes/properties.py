"""Property and camera HTML page routes.

GET /properties              — list all properties (index)
GET /properties/new          — property setup form + map
GET /properties/<id>/cameras — camera setup for a property
GET /properties/<id>/upload  — upload page for a property

All require @login_required.
"""

import json

from flask import Blueprint, render_template, abort
from flask_login import current_user, login_required

from db.models import Property, Upload

properties_bp = Blueprint(
    "properties", __name__, url_prefix="/properties"
)


@properties_bp.route("")
@login_required
def index():
    """Property list page."""
    props = Property.query.filter_by(user_id=current_user.id).all()

    # Attach camera count and last upload date to each property
    property_cards = []
    for p in props:
        camera_count = p.cameras.count()
        last_upload = (
            Upload.query
            .filter_by(property_id=p.id)
            .order_by(Upload.uploaded_at.desc())
            .first()
        )
        property_cards.append({
            "property": p,
            "camera_count": camera_count,
            "last_upload": last_upload,
        })

    return render_template("properties/index.html", property_cards=property_cards)


@properties_bp.route("/new")
@login_required
def new():
    """Property setup page with map."""
    return render_template("properties/setup.html")


@properties_bp.route("/<int:property_id>/cameras")
@login_required
def cameras(property_id):
    """Camera setup page for a property."""
    prop = Property.query.get(property_id)
    if not prop or prop.user_id != current_user.id:
        abort(404)

    cameras = prop.cameras.all()
    cameras_json = json.dumps([
        {
            "id": c.id,
            "camera_label": c.camera_label,
            "name": c.name,
            "lat": c.lat,
            "lon": c.lon,
            "placement_context": c.placement_context,
        }
        for c in cameras
    ])
    return render_template(
        "cameras/setup.html", property=prop, cameras_json=cameras_json
    )


@properties_bp.route("/<int:property_id>/upload")
@login_required
def upload(property_id):
    """Upload page for a property."""
    prop = Property.query.get(property_id)
    if not prop or prop.user_id != current_user.id:
        abort(404)
    return render_template("upload_new.html", property=prop)


@properties_bp.route("/<int:property_id>/upload-tokens")
@login_required
def upload_tokens(property_id):
    """Owner-facing page to mint and manage passwordless upload tokens.

    The page is a thin shell around the existing
    ``/api/properties/<pid>/upload-tokens`` JSON API — the mint form,
    the table of existing tokens, and the revoke action all call the
    API via fetch. This keeps token issuance in one place.
    """
    prop = Property.query.get(property_id)
    if not prop or prop.user_id != current_user.id:
        abort(404)
    return render_template("upload_tokens.html", property=prop)


@properties_bp.route("/<int:property_id>/dashboard")
@login_required
def dashboard(property_id):
    """Game Dashboard — scrollable single-page view."""
    prop = Property.query.get(property_id)
    if not prop or prop.user_id != current_user.id:
        abort(404)
    return render_template("dashboard/index.html", property=prop)


@properties_bp.route("/<int:property_id>/deer")
@login_required
def my_deer(property_id):
    """My Deer — individual deer tracking via re-ID."""
    prop = Property.query.get(property_id)
    if not prop or prop.user_id != current_user.id:
        abort(404)
    return render_template("deer/index.html", property=prop)
