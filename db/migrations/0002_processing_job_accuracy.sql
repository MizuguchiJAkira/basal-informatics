-- 0002_processing_job_accuracy.sql
-- Adds `processing_jobs.accuracy_report_json` — populated by the
-- worker's ground-truth-vs-classifier reconciliation pass when the
-- uploaded ZIP contains hunter-labeled filenames
-- (commit 3486a1e — feat(uploads): filename ground-truth).
--
-- `db.create_all()` will NOT alter an existing `processing_jobs`
-- table to add the new column, so every worker INSERT that includes
-- `accuracy_report_json` fails with `UndefinedColumn` on prod.
--
-- Idempotent: Postgres 9.6+ supports ADD COLUMN IF NOT EXISTS.

ALTER TABLE processing_jobs
    ADD COLUMN IF NOT EXISTS accuracy_report_json TEXT;
