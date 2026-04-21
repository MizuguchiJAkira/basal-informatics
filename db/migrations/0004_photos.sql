-- 0004_photos.sql
-- Adds the `photos` table — per-photo records for every detection the
-- worker keeps. Stores the Spaces key, the classifier output, and the
-- EXIF timestamp. The web tier queries this table to render the
-- dashboard Photo Gallery, generating short-lived presigned Spaces GET
-- URLs at request time.
--
-- Pre-existing `detection_summaries` remains untouched — it's the
-- aggregate per-season/camera/species roll-up that feeds the KPI
-- cards. `photos` is the photo-level record that backs the gallery.
--
-- Worker upload convention: the key is
--     photos/<property_id>/<job_id>/<sha1-of-original-path>.jpg
-- with the original filename preserved as `original_name` for display.
--
-- Only detections (photos SpeciesNet flagged with animals above
-- threshold) are stored — not blanks. This keeps storage bounded.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS photos (
    id                       BIGSERIAL PRIMARY KEY,
    property_id              INTEGER     NOT NULL REFERENCES properties(id),
    camera_id                INTEGER              REFERENCES cameras(id),
    season_id                INTEGER              REFERENCES seasons(id),
    processing_job_id        VARCHAR(8),           -- links to processing_jobs.job_id
    spaces_key               VARCHAR(500) NOT NULL,   -- S3/Spaces object key
    original_name            VARCHAR(500),         -- filename inside the ZIP
    species_key              VARCHAR(200),         -- SpeciesNet class (null if MD-only detection)
    common_name              VARCHAR(200),
    confidence               REAL,                 -- classifier confidence 0-1
    independent_event_id     VARCHAR(80),          -- groups burst/dependent triggers (see migration 0005)
    review_required          BOOLEAN DEFAULT FALSE,
    bbox_json                TEXT,                 -- JSON array of MegaDetector bboxes
    taken_at                 TIMESTAMP,            -- EXIF DateTimeOriginal
    uploaded_at              TIMESTAMP DEFAULT NOW(),
    -- We unique the storage key so re-ingesting the same ZIP is
    -- idempotent — the worker can upsert on spaces_key instead of
    -- accumulating duplicates on retry.
    CONSTRAINT uq_photos_spaces_key UNIQUE (spaces_key)
);

CREATE INDEX IF NOT EXISTS ix_photos_property_id
    ON photos(property_id);
CREATE INDEX IF NOT EXISTS ix_photos_season_id
    ON photos(season_id);
CREATE INDEX IF NOT EXISTS ix_photos_camera_id
    ON photos(camera_id);
CREATE INDEX IF NOT EXISTS ix_photos_species_key
    ON photos(species_key);
-- Composite: dashboard gallery pagination sorts by taken_at desc
-- within a property/season filter. This index covers that shape.
CREATE INDEX IF NOT EXISTS ix_photos_prop_season_taken
    ON photos(property_id, season_id, taken_at DESC);
