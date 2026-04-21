-- 0006_invite_codes.sql
-- Invite-gated signup for the Strecker beta.
--
-- Public visitors can still browse the landing page, but /register
-- requires a valid, unused invite code. The ``invite_codes`` table
-- tracks each code we mint (via ``manage.py invites generate``), who
-- it was intended for (free-form note — "TNDeer wave 1", "Jim Cross",
-- etc.), when it was used, and by whom.
--
-- Single-use: once ``used_at`` is set, the code can't be redeemed
-- again. If we want multi-use later (a referral code for a corporate
-- partner, say), we add a ``max_uses`` column in a later migration.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS invite_codes (
    id                  SERIAL PRIMARY KEY,
    code                VARCHAR(32)  NOT NULL UNIQUE,
    intended_for        VARCHAR(200),
    note                TEXT,
    created_at          TIMESTAMP    DEFAULT NOW(),
    created_by_user_id  INTEGER      REFERENCES users(id),
    used_at             TIMESTAMP,
    used_by_user_id     INTEGER      REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS ix_invite_codes_code
    ON invite_codes(code);
-- Used codes don't clutter the unused-codes query; predicate index
-- keeps list-pending-codes fast as the table grows.
CREATE INDEX IF NOT EXISTS ix_invite_codes_unused
    ON invite_codes(created_at) WHERE used_at IS NULL;
