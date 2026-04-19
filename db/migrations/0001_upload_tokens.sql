-- 0001_upload_tokens.sql
-- Adds the `upload_tokens` table introduced by the passwordless
-- landowner-upload flow (commit 0aad2ba — feat(uploads-v2)).
--
-- `db.create_all()` only creates tables that are ENTIRELY missing,
-- so production Postgres (initialized months ago) never got this
-- table. Any POST /u/<token>/... request will fail with
-- `UndefinedTable: relation "upload_tokens" does not exist` until
-- this migration is applied.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS upload_tokens (
    id                   SERIAL PRIMARY KEY,
    token                VARCHAR(64)  NOT NULL UNIQUE,
    property_id          INTEGER      NOT NULL REFERENCES properties(id),
    created_by_user_id   INTEGER               REFERENCES users(id),
    label                VARCHAR(200),
    email_hint           VARCHAR(255),
    uses_remaining       INTEGER      NOT NULL DEFAULT 10,
    revoked              BOOLEAN      NOT NULL DEFAULT FALSE,
    expires_at           TIMESTAMP,
    last_used_at         TIMESTAMP,
    created_at           TIMESTAMP             DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_upload_tokens_token       ON upload_tokens(token);
CREATE INDEX IF NOT EXISTS ix_upload_tokens_property_id ON upload_tokens(property_id);
