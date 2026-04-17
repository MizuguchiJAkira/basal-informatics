"""Tests for risk.proximity — DetectionIngest bridge classifier."""

import json
from dataclasses import dataclass
from typing import Optional

import pytest

from risk.proximity import (
    NEIGHBOR_RADIUS_KM,
    SOURCE_NEIGHBORING,
    SOURCE_ON_PARCEL,
    SOURCE_OUT_OF_SCOPE,
    SOURCE_UNKNOWN,
    _camera_inside_parcel,
    _distance_to_polygon_boundary_km,
    _equirect_point_to_point_km,
    _parcel_centroid,
    classify_camera,
    classify_cameras,
    proximity_confidence,
)


# -------------------------------------------------------------------------
# Fixtures — tiny rectangular parcel in Texas Hill Country for deterministic
# distance math. Roughly 2 km east-west by 3 km north-south.
# -------------------------------------------------------------------------

EDWARDS_PLATEAU_BOUNDARY = json.dumps({
    "type": "Feature",
    "properties": {"name": "Edwards Plateau Ranch"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [-99.77, 30.46],  # SW
            [-99.77, 30.53],  # NW
            [-99.69, 30.53],  # NE
            [-99.69, 30.46],  # SE
            [-99.77, 30.46],  # close ring
        ]],
    },
})


@dataclass
class FakeCamera:
    id: int
    property_id: int
    camera_label: str
    lat: Optional[float] = None
    lon: Optional[float] = None


@dataclass
class FakeParcel:
    id: int
    boundary_geojson: Optional[str] = None


# -------------------------------------------------------------------------
# Pure math
# -------------------------------------------------------------------------

class TestEquirect:

    def test_zero_distance(self):
        assert _equirect_point_to_point_km(30.5, -99.7, 30.5, -99.7) == 0

    def test_latitude_degree_is_about_111km(self):
        # 1 degree of latitude north.
        d = _equirect_point_to_point_km(30.5, -99.7, 31.5, -99.7)
        assert d == pytest.approx(111.0, abs=0.5)

    def test_longitude_degree_at_30N_is_about_96km(self):
        # 1 degree of longitude at lat=30.5.
        d = _equirect_point_to_point_km(30.5, -99.7, 30.5, -98.7)
        # cos(30.5°) ≈ 0.862, so 111 * 0.862 ≈ 95.7
        assert d == pytest.approx(95.7, abs=1.0)


class TestProximityConfidence:

    def test_zero_km_is_one(self):
        assert proximity_confidence(0.0) == 1.0

    def test_cutoff_km_is_zero(self):
        assert proximity_confidence(NEIGHBOR_RADIUS_KM) == 0.0

    def test_halfway_is_half(self):
        assert proximity_confidence(1.0, cutoff_km=2.0) == 0.5

    def test_beyond_cutoff_is_zero(self):
        assert proximity_confidence(5.0, cutoff_km=2.0) == 0.0

    def test_none_is_zero(self):
        assert proximity_confidence(None) == 0.0

    def test_negative_treated_as_zero_distance(self):
        # Defensive: a point inside a polygon can sometimes be reported as
        # negative by distance algorithms. We treat that as "on parcel".
        assert proximity_confidence(-0.1) == 1.0


class TestParcelCentroid:

    def test_rectangular_parcel(self):
        lat, lon = _parcel_centroid(EDWARDS_PLATEAU_BOUNDARY)
        assert lat == pytest.approx(30.495, abs=0.01)
        assert lon == pytest.approx(-99.73, abs=0.01)

    def test_missing_boundary(self):
        assert _parcel_centroid(None) is None
        assert _parcel_centroid("") is None
        assert _parcel_centroid("not-json") is None


class TestInsideParcel:

    def test_camera_inside(self):
        # Center of the rectangle.
        assert _camera_inside_parcel(30.495, -99.73, EDWARDS_PLATEAU_BOUNDARY) is True

    def test_camera_outside(self):
        # Well to the north.
        assert _camera_inside_parcel(30.6, -99.73, EDWARDS_PLATEAU_BOUNDARY) is False

    def test_missing_boundary(self):
        assert _camera_inside_parcel(30.5, -99.73, None) is None


class TestDistanceToBoundary:

    def test_inside_is_zero(self):
        # Centroid is inside, so distance = 0.
        d = _distance_to_polygon_boundary_km(30.495, -99.73, EDWARDS_PLATEAU_BOUNDARY)
        assert d == pytest.approx(0.0, abs=0.01)

    def test_outside_close(self):
        # 0.01 degrees north of the north edge (30.53). That's ~1.11 km north.
        d = _distance_to_polygon_boundary_km(30.54, -99.73, EDWARDS_PLATEAU_BOUNDARY)
        # Accept either 1.1 km (proper polygon distance) or bounded-by-corner
        # fallback (~1.1-1.3). Both are within the neighbor radius.
        assert 0.9 < d < 1.4

    def test_outside_far(self):
        # 0.1 deg north (~11 km) — clearly out of scope.
        d = _distance_to_polygon_boundary_km(30.63, -99.73, EDWARDS_PLATEAU_BOUNDARY)
        assert d > 5.0

    def test_no_boundary(self):
        assert _distance_to_polygon_boundary_km(30.5, -99.73, None) is None


# -------------------------------------------------------------------------
# classify_camera
# -------------------------------------------------------------------------

class TestClassifyCamera:

    _parcel = FakeParcel(id=1, boundary_geojson=EDWARDS_PLATEAU_BOUNDARY)

    def test_same_property_always_on_parcel(self):
        # Even without lat/lon, a camera on the target property is on_parcel
        # because property_id match is authoritative.
        cam = FakeCamera(id=10, property_id=1, camera_label="CAM-01",
                         lat=None, lon=None)
        r = classify_camera(cam, self._parcel)
        assert r.source == SOURCE_ON_PARCEL
        assert r.proximity_confidence == 1.0
        assert r.distance_km == 0.0

    def test_different_property_inside_geom_is_on_parcel_by_distance(self):
        # Hypothetical: a camera on property 99 but geographically inside
        # parcel 1's boundary. Classified as neighboring with distance 0
        # (confidence 1.0) — on_parcel is reserved for property_id match.
        cam = FakeCamera(id=11, property_id=99, camera_label="CAM-NBR-INSIDE",
                         lat=30.495, lon=-99.73)
        r = classify_camera(cam, self._parcel)
        assert r.source == SOURCE_NEIGHBORING
        assert r.distance_km == 0.0
        assert r.proximity_confidence == 1.0

    def test_neighboring_within_cutoff(self):
        # ~1 km north of parcel edge.
        cam = FakeCamera(id=12, property_id=99, camera_label="CAM-NBR-1KM",
                         lat=30.54, lon=-99.73)
        r = classify_camera(cam, self._parcel)
        assert r.source == SOURCE_NEIGHBORING
        assert 0.9 < r.distance_km < 1.4
        assert 0.3 < r.proximity_confidence < 0.6

    def test_out_of_scope_beyond_cutoff(self):
        # ~11 km away.
        cam = FakeCamera(id=13, property_id=99, camera_label="CAM-FAR",
                         lat=30.63, lon=-99.73)
        r = classify_camera(cam, self._parcel)
        assert r.source == SOURCE_OUT_OF_SCOPE
        assert r.proximity_confidence == 0.0

    def test_missing_camera_coords(self):
        cam = FakeCamera(id=14, property_id=99, camera_label="CAM-NO-GEO",
                         lat=None, lon=None)
        r = classify_camera(cam, self._parcel)
        assert r.source == SOURCE_UNKNOWN
        assert r.distance_km is None
        assert any("no lat/lon" in n for n in r.notes)

    def test_missing_parcel_boundary(self):
        cam = FakeCamera(id=15, property_id=99, camera_label="CAM-NBR",
                         lat=30.54, lon=-99.73)
        empty = FakeParcel(id=2, boundary_geojson=None)
        r = classify_camera(cam, empty)
        assert r.source == SOURCE_UNKNOWN
        assert any("no boundary geometry" in n for n in r.notes)


# -------------------------------------------------------------------------
# classify_cameras batch
# -------------------------------------------------------------------------

class TestClassifyCamerasBatch:

    def test_sorts_on_parcel_first_then_nearest(self):
        parcel = FakeParcel(id=1, boundary_geojson=EDWARDS_PLATEAU_BOUNDARY)
        cams = [
            FakeCamera(id=1, property_id=1, camera_label="CAM-OWN", lat=30.5, lon=-99.73),
            FakeCamera(id=2, property_id=99, camera_label="CAM-FAR-NBR", lat=30.545, lon=-99.73),
            FakeCamera(id=3, property_id=99, camera_label="CAM-NEAR-NBR", lat=30.535, lon=-99.73),
        ]
        results = classify_cameras(cams, parcel)
        labels = [r.camera_label for r in results]
        assert labels[0] == "CAM-OWN"
        # Nearest neighbor before further.
        assert labels.index("CAM-NEAR-NBR") < labels.index("CAM-FAR-NBR")

    def test_out_of_scope_filtered(self):
        parcel = FakeParcel(id=1, boundary_geojson=EDWARDS_PLATEAU_BOUNDARY)
        cams = [
            FakeCamera(id=1, property_id=99, camera_label="CAM-NBR", lat=30.54, lon=-99.73),
            FakeCamera(id=2, property_id=99, camera_label="CAM-FAR", lat=30.63, lon=-99.73),
        ]
        results = classify_cameras(cams, parcel)
        labels = {r.camera_label for r in results}
        assert "CAM-NBR" in labels
        assert "CAM-FAR" not in labels

    def test_empty_input(self):
        parcel = FakeParcel(id=1, boundary_geojson=EDWARDS_PLATEAU_BOUNDARY)
        assert classify_cameras([], parcel) == []
