-- 0003_camera_stations.sql
-- Adds the `camera_stations` table (SQLAlchemy model — NOT the
-- legacy PostGIS `camera_stations` in db/schema.sql which was never
-- actually deployed under this name in the Flask-SQLAlchemy schema).
--
-- Introduced by commit 7dd8cdf — feat(stations): per-property
-- CameraStation mapping for IPW context. The ingest pipeline reads
-- this table to resolve filename station codes (e.g. "MH", "CW") to
-- a `placement_context` so bias/placement_ipw.py can deflate
-- per-camera detection rates correctly.
--
-- Scoped per property: UNIQUE(property_id, station_code) enforces
-- that the same short code can map differently on different ranches.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS camera_stations (
    id                 SERIAL PRIMARY KEY,
    property_id        INTEGER      NOT NULL REFERENCES properties(id),
    station_code       VARCHAR(8)   NOT NULL,
    placement_context  VARCHAR(30)  NOT NULL,
    label              VARCHAR(200),
    created_at         TIMESTAMP             DEFAULT NOW(),
    updated_at         TIMESTAMP             DEFAULT NOW(),
    CONSTRAINT uq_camera_station_property_code
        UNIQUE (property_id, station_code)
);

CREATE INDEX IF NOT EXISTS ix_camera_stations_property_id
    ON camera_stations(property_id);
