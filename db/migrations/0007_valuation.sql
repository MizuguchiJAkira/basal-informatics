-- 0007_valuation.sql
-- Texas wildlife valuation risk module (Stage 7).
--
-- Three tables back the lender-facing Valuation Risk section on the
-- parcel report:
--
--   cad_snapshot             — raw County Appraisal District record per
--                              parcel + as_of_date. Audit trail for the
--                              numbers shown in the report.
--   parcel_valuation_status  — current classification, computed risk
--                              band/score, exposure, remediation, and
--                              the underwriter-override slot.
--   valuation_risk_factors   — the named drivers a score decomposes
--                              into. Every score has at least one row;
--                              no driverless scores in the report.
--
-- Texas-only language is enforced at the application layer, not in
-- enums here, so future Texas-specific classifications (1-d-1(t),
-- etc.) can be added without a column change.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS cad_snapshot (
    id                       SERIAL PRIMARY KEY,
    parcel_id                INTEGER NOT NULL
        REFERENCES properties(id) ON DELETE CASCADE,
    -- 'kimble_tx', 'brazos_tx' — keys the CAD adapter registry.
    county_slug              VARCHAR(40)  NOT NULL,
    -- ag_open_space | wildlife_open_space | timber | market | unknown
    classification           VARCHAR(40)  NOT NULL,
    assessed_value_per_acre  NUMERIC(14, 2),
    market_value_per_acre    NUMERIC(14, 2),
    -- Last recorded deed transfer. Drives the
    -- ownership_change_recent factor.
    ownership_change_date    DATE,
    as_of_date               DATE         NOT NULL,
    -- The adapter's full pulled record, JSON-serialized. Lets an
    -- auditor reproduce the score from the same input snapshot
    -- without re-pulling CAD data.
    raw_record_json          TEXT,
    created_at               TIMESTAMP    DEFAULT NOW(),
    UNIQUE (parcel_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS ix_cad_snapshot_parcel
    ON cad_snapshot(parcel_id, as_of_date DESC);


CREATE TABLE IF NOT EXISTS parcel_valuation_status (
    id                       SERIAL PRIMARY KEY,
    parcel_id                INTEGER NOT NULL UNIQUE
        REFERENCES properties(id) ON DELETE CASCADE,
    cad_snapshot_id          INTEGER REFERENCES cad_snapshot(id),
    -- Indicative band — never displayed as a probability or percentage
    -- the lender could quote back. low | moderate | elevated | high.
    risk_band                VARCHAR(20)  NOT NULL,
    risk_score_value         NUMERIC(5, 3) NOT NULL,    -- 0.000 - 1.000
    -- Negative dollar value if status is lost (assessed-to-market
    -- reset). NULL when CAD adapter couldn't supply both numbers.
    exposure_dollars         NUMERIC(14, 2),
    exposure_method          VARCHAR(60),
    exposure_confidence      VARCHAR(20),               -- low | medium | high
    -- Remediation pathway (3-of-7 TPWD practices logic).
    remediation_viable       BOOLEAN,
    ecoregion                VARCHAR(40),
    -- Underwriter override slot. UI may not exist yet; data path does.
    -- override == NULL means no override.
    underwriter_override     VARCHAR(20),
    underwriter_notes        TEXT,
    override_at              TIMESTAMP,
    override_by_user_id      INTEGER REFERENCES users(id),
    computed_at              TIMESTAMP    DEFAULT NOW()
);


CREATE TABLE IF NOT EXISTS valuation_risk_factors (
    id                              SERIAL PRIMARY KEY,
    parcel_valuation_status_id      INTEGER NOT NULL
        REFERENCES parcel_valuation_status(id) ON DELETE CASCADE,
    factor_key                      VARCHAR(80) NOT NULL,
    -- Factor weights in the rubric sum to 1.0; stored per-row so an
    -- auditor can see what the rubric looked like when the score was
    -- computed (rubric is versioned in valuation/scoring.py).
    weight                          NUMERIC(4, 3) NOT NULL,
    -- Did this driver fire on this parcel? When FALSE, the row is
    -- still recorded so the report can show "considered, did not
    -- contribute" rather than implying the rubric is shorter than
    -- it is.
    triggered                       BOOLEAN     NOT NULL,
    evidence                        TEXT,
    display_order                   INTEGER     DEFAULT 0
);

CREATE INDEX IF NOT EXISTS ix_valuation_risk_factors_status
    ON valuation_risk_factors(parcel_valuation_status_id);
