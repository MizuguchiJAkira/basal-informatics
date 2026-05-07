-- 0008_valuation_override_history.sql
-- Append-only audit log for parcel_valuation_status.underwriter_override.
--
-- Why a separate table: ``parcel_valuation_status`` carries the
-- *current* override only. When an underwriter changes the override
-- twice (e.g. set to "low" → set to "moderate"), the prior value is
-- overwritten in place. Lender pilots have audit obligations that
-- require a history of every change with actor + timestamp.
--
-- Each row records ONE override action: prev_band → new_band, who did
-- it, when, and the notes attached. Rows are inserted; never updated
-- or deleted. ``DROP`` semantics in the down file remove the table
-- entirely (the data is lost on rollback — same posture as Stage 7's
-- other tables).
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS valuation_override_history (
    id                       SERIAL PRIMARY KEY,
    parcel_valuation_status_id  INTEGER NOT NULL
        REFERENCES parcel_valuation_status(id) ON DELETE CASCADE,
    -- low | moderate | elevated | high | NULL (NULL = "no override
    -- before/after this change"). Both columns nullable so a row can
    -- record a set-from-clear or a clear-of-existing.
    prev_band                VARCHAR(20),
    new_band                 VARCHAR(20),
    -- Notes captured at the moment of change. The current notes on
    -- parcel_valuation_status may have been edited again since.
    notes                    TEXT,
    set_by_user_id           INTEGER REFERENCES users(id),
    set_at                   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_valuation_override_history_status
    ON valuation_override_history(parcel_valuation_status_id, set_at DESC);
