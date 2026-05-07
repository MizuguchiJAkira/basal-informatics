-- 0007_valuation.down.sql
-- Rollback of 0007_valuation.sql.
--
-- DROP order respects the foreign-key chain:
--   valuation_risk_factors → parcel_valuation_status → cad_snapshot
--
-- Idempotent: re-running on a database that's already been rolled
-- back is a no-op. The trailing DELETE removes the migration's row
-- from the schema_migrations tracker so a subsequent ``manage.py
-- db migrate`` will re-apply 0007.

DROP TABLE IF EXISTS valuation_risk_factors;
DROP TABLE IF EXISTS parcel_valuation_status;
DROP TABLE IF EXISTS cad_snapshot;

DELETE FROM schema_migrations WHERE filename = '0007_valuation.sql';
