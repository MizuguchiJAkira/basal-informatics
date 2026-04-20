"""API routes for Property and Camera CRUD.

All endpoints return JSON and require authentication.
Ownership is verified on every request (property.user_id == current_user.id).
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from db.models import db, Property, Camera, Upload, ProcessingJob

properties_api_bp = Blueprint("properties_api", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _property_json(prop):
    """Serialize a Property to dict."""
    return {
        "id": prop.id,
        "name": prop.name,
        "county": prop.county,
        "state": prop.state,
        "acreage": prop.acreage,
        "boundary_geojson": prop.boundary_geojson,
        "created_at": prop.created_at.isoformat() if prop.created_at else None,
        "updated_at": prop.updated_at.isoformat() if prop.updated_at else None,
    }


def _camera_json(cam):
    """Serialize a Camera to dict."""
    return {
        "id": cam.id,
        "property_id": cam.property_id,
        "camera_label": cam.camera_label,
        "name": cam.name,
        "lat": cam.lat,
        "lon": cam.lon,
        "placement_context": cam.placement_context,
        "camera_model": cam.camera_model,
        "installed_date": cam.installed_date.isoformat() if cam.installed_date else None,
        "is_active": cam.is_active,
        "created_at": cam.created_at.isoformat() if cam.created_at else None,
        "updated_at": cam.updated_at.isoformat() if cam.updated_at else None,
    }


def _get_user_property(property_id):
    """Get a property owned by current_user, or None."""
    prop = Property.query.get(property_id)
    if prop and prop.user_id == current_user.id:
        return prop
    return None


# ---------------------------------------------------------------------------
# Property endpoints
# ---------------------------------------------------------------------------

@properties_api_bp.route("/properties", methods=["GET"])
@login_required
def list_properties():
    """List all properties owned by the current user."""
    props = Property.query.filter_by(user_id=current_user.id).all()
    return jsonify([_property_json(p) for p in props])


@properties_api_bp.route("/properties", methods=["POST"])
@login_required
def create_property():
    """Create a new property."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > 200:
        return jsonify({"error": "name must be <= 200 characters"}), 400

    # state is a VARCHAR(2) USPS/ISO code. The UI dropdown already
    # sends codes, but a direct API caller might send the display label
    # ("Texas") — catch that explicitly rather than letting Postgres
    # raise StringDataRightTruncation and 500.
    state = data.get("state")
    if state is not None:
        state = str(state).strip().upper()
        if state == "":
            state = None
        elif len(state) != 2:
            return jsonify({
                "error": (f"state must be a 2-letter code (got "
                          f"{state!r}, {len(state)} chars)")
            }), 400

    county = data.get("county")
    if county is not None:
        county = str(county).strip()
        if len(county) > 100:
            return jsonify({"error": "county must be <= 100 characters"}), 400

    acreage = data.get("acreage")
    if acreage is not None:
        try:
            acreage = float(acreage)
        except (TypeError, ValueError):
            return jsonify({"error": "acreage must be a number"}), 400

    prop = Property(
        user_id=current_user.id,
        name=name,
        county=county,
        state=state,
        acreage=acreage,
        boundary_geojson=data.get("boundary_geojson"),
    )
    db.session.add(prop)
    db.session.commit()

    return jsonify(_property_json(prop)), 201


@properties_api_bp.route("/properties/<int:property_id>", methods=["GET"])
@login_required
def get_property(property_id):
    """Get a single property with its cameras."""
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    result = _property_json(prop)
    result["cameras"] = [_camera_json(c) for c in prop.cameras.all()]
    return jsonify(result)


@properties_api_bp.route("/properties/<int:property_id>", methods=["PUT"])
@login_required
def update_property(property_id):
    """Update an existing property."""
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    for field in ("name", "county", "state", "acreage", "boundary_geojson"):
        if field in data:
            setattr(prop, field, data[field])

    db.session.commit()
    return jsonify(_property_json(prop))


@properties_api_bp.route("/properties/<int:property_id>", methods=["DELETE"])
@login_required
def delete_property(property_id):
    """Delete a property and its cameras."""
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    # Cascade: the data graph under a property is
    # ProcessingJob → Upload → Camera → Property. SQLAlchemy doesn't
    # cascade automatically across these (the foreign keys are RESTRICT
    # by default), so delete children in dependency order.
    upload_ids = [u.id for u in Upload.query.filter_by(property_id=prop.id).all()]
    if upload_ids:
        ProcessingJob.query.filter(
            ProcessingJob.upload_id.in_(upload_ids)
        ).delete(synchronize_session=False)
    ProcessingJob.query.filter_by(property_id=prop.id).delete(
        synchronize_session=False
    )
    Upload.query.filter_by(property_id=prop.id).delete(synchronize_session=False)
    Camera.query.filter_by(property_id=prop.id).delete(synchronize_session=False)
    db.session.delete(prop)
    db.session.commit()

    return jsonify({"message": "Property deleted"}), 200


# ---------------------------------------------------------------------------
# Camera endpoints
# ---------------------------------------------------------------------------

@properties_api_bp.route("/properties/<int:property_id>/cameras", methods=["GET"])
@login_required
def list_cameras(property_id):
    """List cameras for a property."""
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    cameras = Camera.query.filter_by(property_id=prop.id).all()
    return jsonify([_camera_json(c) for c in cameras])


@properties_api_bp.route("/properties/<int:property_id>/cameras", methods=["POST"])
@login_required
def create_camera(property_id):
    """Create a camera on a property."""
    prop = _get_user_property(property_id)
    if not prop:
        return jsonify({"error": "Property not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    # Accept lat/lon (canonical) OR latitude/longitude (the spelling
    # used by most GPS libraries and what a reasonable API caller
    # will try first). Silently falling through would cause a camera
    # to save with null coordinates even though the client sent them.
    lat = data.get("lat", data.get("latitude"))
    lon = data.get("lon", data.get("longitude"))
    if lat is not None:
        try:
            lat = float(lat)
        except (TypeError, ValueError):
            return jsonify({"error": "lat must be a number"}), 400
        if not -90 <= lat <= 90:
            return jsonify({"error": "lat must be in [-90, 90]"}), 400
    if lon is not None:
        try:
            lon = float(lon)
        except (TypeError, ValueError):
            return jsonify({"error": "lon must be a number"}), 400
        if not -180 <= lon <= 180:
            return jsonify({"error": "lon must be in [-180, 180]"}), 400

    cam = Camera(
        property_id=prop.id,
        camera_label=data.get("camera_label"),
        name=data.get("name"),
        lat=lat,
        lon=lon,
        placement_context=data.get("placement_context"),
        camera_model=data.get("camera_model"),
    )
    db.session.add(cam)
    db.session.commit()

    return jsonify(_camera_json(cam)), 201


@properties_api_bp.route("/cameras/<int:camera_id>", methods=["PUT"])
@login_required
def update_camera(camera_id):
    """Update a camera."""
    cam = Camera.query.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    # Verify ownership through property
    prop = Property.query.get(cam.property_id)
    if not prop or prop.user_id != current_user.id:
        return jsonify({"error": "Camera not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    # Canonicalize lat/lon aliases before the generic setattr loop.
    if "latitude" in data and "lat" not in data:
        data["lat"] = data.pop("latitude")
    if "longitude" in data and "lon" not in data:
        data["lon"] = data.pop("longitude")

    for field in (
        "camera_label", "name", "lat", "lon",
        "placement_context", "camera_model", "is_active",
    ):
        if field in data:
            setattr(cam, field, data[field])

    db.session.commit()
    return jsonify(_camera_json(cam))


@properties_api_bp.route("/cameras/<int:camera_id>", methods=["DELETE"])
@login_required
def delete_camera(camera_id):
    """Delete a camera."""
    cam = Camera.query.get(camera_id)
    if not cam:
        return jsonify({"error": "Camera not found"}), 404

    # Verify ownership through property
    prop = Property.query.get(cam.property_id)
    if not prop or prop.user_id != current_user.id:
        return jsonify({"error": "Camera not found"}), 404

    db.session.delete(cam)
    db.session.commit()

    return jsonify({"message": "Camera deleted"}), 200
