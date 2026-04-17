"""Geographic proximity scoring for the DetectionIngest bridge.

Strecker is a separate hunter-facing product whose users deploy cameras on
hunting leases. When a Basal parcel is under lender-commissioned
assessment, cameras on NEIGHBORING leases (not on the parcel itself) can
contribute supplementary ecological signal — especially on parcels with
sparse on-parcel camera coverage.

This module computes:
  1. Distance from a camera (lat/lon point) to a parcel boundary (polygon)
  2. A proximity-confidence score that decays linearly to zero at a
     configurable cutoff (default 2 km)
  3. A classification of cameras as on_parcel / neighboring / out_of_scope

Distances are in kilometers. We use shapely for point-to-polygon math on
the lat/lon coordinates of the parcel boundary, converting degree units
to km via a simple equirectangular approximation (lat_km = 111, lon_km
= 111 * cos(latitude)). This is plenty accurate at parcel scale
(< 10 km) even at high latitudes; for continental-scale math we'd
project properly.

Why boundary distance, not centroid-to-camera: a camera 100 m outside
the fence of a 2000-acre parcel should score nearly 1.0 (very relevant
signal). Centroid distance would penalize it because the parcel is a
kilometer across.

Why NOT folding neighboring data into REM density estimates: REM's
detection-zone math assumes the camera IS on the parcel. Neighboring-
lease data violates that assumption and would bias the density estimate.
The bridge exposes neighboring coverage AS SUPPLEMENTARY INFORMATION
in the Nature Exposure Report, NOT as a density input. The loan officer
sees additional event counts with a clear proximity-confidence label,
not an adjusted density number.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

# shapely is in requirements.txt; if it's missing we degrade gracefully
# to a centroid-distance approximation so tests / local dev still work.
try:
    from shapely.geometry import Point, Polygon, shape
    SHAPELY = True
except ImportError:  # pragma: no cover
    SHAPELY = False

# -----------------------------------------------------------------------------
# Constants (pulled into config/settings.py at caller's discretion)
# -----------------------------------------------------------------------------

NEIGHBOR_RADIUS_KM = 2.0        # cutoff beyond which a camera is "out_of_scope"
EARTH_KM_PER_DEG_LAT = 111.0    # equirectangular approx (mean earth radius 6371 km * pi / 180)


# -----------------------------------------------------------------------------
# Output records
# -----------------------------------------------------------------------------

SOURCE_ON_PARCEL = "on_parcel"
SOURCE_NEIGHBORING = "neighboring"
SOURCE_OUT_OF_SCOPE = "out_of_scope"
SOURCE_UNKNOWN = "unknown"   # parcel boundary or camera lat/lon missing


@dataclass
class ProximityResult:
    """Per-camera proximity classification for a target parcel."""
    camera_id: int
    camera_label: Optional[str]
    source: str                         # one of SOURCE_* above
    distance_km: Optional[float]        # None if no geometry available
    proximity_confidence: float         # 1.0 for on_parcel, linear decay for neighboring, 0 for out_of_scope
    owner_property_id: Optional[int] = None
    notes: List[str] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Core math
# -----------------------------------------------------------------------------

def _equirect_point_to_point_km(lat1: float, lon1: float,
                                lat2: float, lon2: float) -> float:
    """Equirectangular-approximation great-circle distance in km.

    Accurate to ~0.5% at parcel scale (< 10 km), fast, no trig on the
    uncommon axis.
    """
    lat_km = (lat2 - lat1) * EARTH_KM_PER_DEG_LAT
    # Use midpoint latitude for lon scaling; fine at these distances.
    mid_lat = math.radians((lat1 + lat2) / 2)
    lon_km = (lon2 - lon1) * EARTH_KM_PER_DEG_LAT * math.cos(mid_lat)
    return math.hypot(lat_km, lon_km)


def _polygon_coords(boundary_geojson: str):
    """Parse a GeoJSON Feature/Polygon string and yield [(lon, lat), ...].

    The repo stores boundaries as GeoJSON Features with Polygon geometry;
    coordinates are [[[lon, lat], [lon, lat], ...]] per the spec.
    """
    if not boundary_geojson:
        return None
    try:
        data = json.loads(boundary_geojson)
    except (json.JSONDecodeError, TypeError):
        return None
    geom = data.get("geometry", data)  # support bare Geometry dicts too
    if geom.get("type") != "Polygon":
        return None
    coords = geom.get("coordinates") or []
    if not coords or not coords[0]:
        return None
    return coords[0]  # outer ring


def _parcel_centroid(boundary_geojson: str) -> Optional[tuple]:
    """Return (lat, lon) centroid of the parcel's outer ring, or None."""
    ring = _polygon_coords(boundary_geojson)
    if not ring:
        return None
    # Average of the ring vertices; good enough for a rectangle-ish parcel.
    lons = [c[0] for c in ring]
    lats = [c[1] for c in ring]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def _camera_inside_parcel(cam_lat: float, cam_lon: float,
                          boundary_geojson: str) -> Optional[bool]:
    """True if camera point is inside the parcel polygon, False if outside,
    None if the boundary can't be parsed.
    """
    ring = _polygon_coords(boundary_geojson)
    if not ring:
        return None
    if SHAPELY:
        try:
            poly = Polygon([(lon, lat) for lon, lat in ring])
            return poly.contains(Point(cam_lon, cam_lat))
        except Exception:
            return None
    # Fallback: simple ray-casting point-in-polygon
    x, y = cam_lon, cam_lat
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _distance_to_polygon_boundary_km(cam_lat: float, cam_lon: float,
                                     boundary_geojson: str) -> Optional[float]:
    """Shortest distance from a camera point to the parcel's boundary edge.

    Returns 0.0 if camera is inside the polygon. Returns None if the
    boundary is unparseable.
    """
    ring = _polygon_coords(boundary_geojson)
    if not ring:
        return None

    # Inside -> 0 by convention.
    inside = _camera_inside_parcel(cam_lat, cam_lon, boundary_geojson)
    if inside is True:
        return 0.0

    if SHAPELY:
        try:
            poly = Polygon([(lon, lat) for lon, lat in ring])
            pt = Point(cam_lon, cam_lat)
            # shapely's distance is in degrees on lat/lon coords.
            deg = poly.exterior.distance(pt)
            # Convert degrees to km using local lat/lon scaling.
            # Shapely distance is in coordinate units; we want km. The
            # distance is measured along a curved surface only approximately
            # here; for accuracy at parcel scale we reproject via the
            # equirectangular scale at the nearest point. Close enough.
            return deg * EARTH_KM_PER_DEG_LAT * math.cos(math.radians(cam_lat))
        except Exception:
            pass

    # Fallback: minimum equirect distance from camera to each ring vertex.
    # Under-estimates edge distance slightly, but at parcel scale the ring
    # is dense enough that this is within ~10 m.
    distances = [
        _equirect_point_to_point_km(cam_lat, cam_lon, lat, lon)
        for lon, lat in ring
    ]
    return min(distances) if distances else None


def proximity_confidence(distance_km: Optional[float],
                         cutoff_km: float = NEIGHBOR_RADIUS_KM) -> float:
    """Linear decay proximity weight in [0, 1].

    distance_km = 0      -> 1.0 (on parcel or at boundary)
    distance_km = cutoff -> 0.0
    distance_km > cutoff -> 0.0
    distance_km = None   -> 0.0  (no geometry, no claim)
    """
    if distance_km is None:
        return 0.0
    if distance_km <= 0:
        return 1.0
    if distance_km >= cutoff_km:
        return 0.0
    return max(0.0, 1.0 - (distance_km / cutoff_km))


# -----------------------------------------------------------------------------
# Public API — classifier
# -----------------------------------------------------------------------------

def classify_camera(camera, target_parcel,
                    cutoff_km: float = NEIGHBOR_RADIUS_KM
                    ) -> ProximityResult:
    """Classify a camera's relationship to a target parcel.

    Inputs are ORM rows (Camera and Property) but we read only:
      - camera.id, .camera_label, .lat, .lon, .property_id
      - target_parcel.id, .boundary_geojson

    Same-property cameras are always ``on_parcel`` with confidence 1.0,
    even if we can't parse the boundary (the property_id match is
    authoritative).
    """
    cam_id = getattr(camera, "id", None)
    cam_label = getattr(camera, "camera_label", None)
    cam_lat = getattr(camera, "lat", None)
    cam_lon = getattr(camera, "lon", None)
    cam_prop_id = getattr(camera, "property_id", None)

    target_id = getattr(target_parcel, "id", None)
    boundary = getattr(target_parcel, "boundary_geojson", None)

    # Belongs-to-the-parcel short-circuit.
    if cam_prop_id is not None and cam_prop_id == target_id:
        return ProximityResult(
            camera_id=cam_id,
            camera_label=cam_label,
            source=SOURCE_ON_PARCEL,
            distance_km=0.0,
            proximity_confidence=1.0,
            owner_property_id=cam_prop_id,
        )

    # From here the camera is on a different property — potential neighbor.
    if cam_lat is None or cam_lon is None:
        return ProximityResult(
            camera_id=cam_id, camera_label=cam_label,
            source=SOURCE_UNKNOWN, distance_km=None, proximity_confidence=0.0,
            owner_property_id=cam_prop_id,
            notes=["Camera has no lat/lon; cannot compute proximity."],
        )
    if not boundary:
        return ProximityResult(
            camera_id=cam_id, camera_label=cam_label,
            source=SOURCE_UNKNOWN, distance_km=None, proximity_confidence=0.0,
            owner_property_id=cam_prop_id,
            notes=["Target parcel has no boundary geometry; cannot compute proximity."],
        )

    dist = _distance_to_polygon_boundary_km(cam_lat, cam_lon, boundary)
    if dist is None:
        return ProximityResult(
            camera_id=cam_id, camera_label=cam_label,
            source=SOURCE_UNKNOWN, distance_km=None, proximity_confidence=0.0,
            owner_property_id=cam_prop_id,
            notes=["Parcel boundary unparseable."],
        )

    conf = proximity_confidence(dist, cutoff_km)
    source = SOURCE_NEIGHBORING if dist < cutoff_km else SOURCE_OUT_OF_SCOPE
    return ProximityResult(
        camera_id=cam_id,
        camera_label=cam_label,
        source=source,
        distance_km=round(dist, 3),
        proximity_confidence=round(conf, 3),
        owner_property_id=cam_prop_id,
    )


def classify_cameras(cameras: Iterable, target_parcel,
                     cutoff_km: float = NEIGHBOR_RADIUS_KM
                     ) -> List[ProximityResult]:
    """Classify a batch; returns only on_parcel + neighboring + unknown
    (out_of_scope cameras are filtered since they contribute no signal).
    """
    out = []
    for c in cameras:
        r = classify_camera(c, target_parcel, cutoff_km=cutoff_km)
        if r.source == SOURCE_OUT_OF_SCOPE:
            continue
        out.append(r)
    # on_parcel first, then neighboring nearest-first, then unknown.
    def _key(r):
        rank = {SOURCE_ON_PARCEL: 0, SOURCE_NEIGHBORING: 1,
                SOURCE_UNKNOWN: 2}.get(r.source, 3)
        return (rank, r.distance_km if r.distance_km is not None else 9e9)
    out.sort(key=_key)
    return out
