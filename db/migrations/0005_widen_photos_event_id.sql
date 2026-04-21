-- 0005_widen_photos_event_id.sql
-- photos.independent_event_id was initially sized VARCHAR(32) but real
-- event IDs are ``IE-<camera_label>-<species_key>-<seq6>`` which for
-- long species keys (e.g. ``cottontail_rabbit``) or verbose camera
-- labels (e.g. ``_unlabeled``) overflow at 32 chars. One TNDeer upload
-- tripped:
--     IE-_unlabeled-cottontail_rabbit-000057  (38 chars)
-- Widen to VARCHAR(80) to cover realistic combinations with headroom.
--
-- Postgres: ALTER COLUMN TYPE is a metadata-only rewrite when the new
-- type is the same family and strictly wider — no table scan.
-- SQLite: ALTER COLUMN is partially supported; VARCHAR length is
-- advisory there anyway, so the migrate.py translator treats this
-- as a no-op.
--
-- Idempotent: the final width is 80 regardless of prior state.

ALTER TABLE photos
    ALTER COLUMN independent_event_id TYPE VARCHAR(80);
