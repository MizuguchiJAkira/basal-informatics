-- 0008_valuation_override_history.down.sql
-- Rollback of 0008. Drops the audit table and removes the tracker row.
DROP TABLE IF EXISTS valuation_override_history;
DELETE FROM schema_migrations WHERE filename = '0008_valuation_override_history.sql';
