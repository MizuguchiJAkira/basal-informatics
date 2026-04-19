"""Tests for the ad-hoc migration runner in scripts/migrate.py.

Goal: prove that running migrations against a fresh SQLite database
created by ``db.create_all()`` (1) succeeds, (2) populates the
``schema_migrations`` tracking table with one row per migration file,
and (3) is a no-op on the second run.

We run against SQLite because that's the test harness the rest of the
suite uses. The migrations themselves target Postgres in production
(hence ``ADD COLUMN IF NOT EXISTS``); scripts/migrate.py translates
those away for SQLite and treats "already exists" errors as benign,
which is exactly the idempotence contract we want to verify.
"""

import os
import pathlib
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def fresh_sqlite(tmp_path, monkeypatch):
    """A brand-new SQLite DB pre-populated by `db.create_all()`.

    Mirrors what a freshly-deployed instance would look like before the
    migration runner is invoked.
    """
    db_path = tmp_path / "basal_test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # Purge cached modules that read DATABASE_URL at import time, so
    # SQLAlchemy binds to the throwaway file rather than whatever the
    # previous test configured.
    for mod in list(sys.modules):
        if mod.startswith(("config", "db", "web")):
            sys.modules.pop(mod, None)

    from flask import Flask

    from db.models import db

    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()

    return db_url


def _migration_filenames():
    mig_dir = _ROOT / "db" / "migrations"
    return sorted(p.name for p in mig_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def test_migration_files_discovered():
    """Guard against accidentally deleting the migration directory."""
    names = _migration_filenames()
    assert names, "expected at least one migration file in db/migrations/"
    # Canonical expected set for the current schema-add batch.
    assert "0001_upload_tokens.sql" in names
    assert "0002_processing_job_accuracy.sql" in names
    assert "0003_camera_stations.sql" in names


def test_migrate_populates_tracking_table(fresh_sqlite):
    # Re-import after env var is monkeypatched so migrate.py resolves
    # the fresh URL.
    sys.modules.pop("scripts.migrate", None)
    from scripts import migrate

    rc = migrate.run(db_url=fresh_sqlite)
    assert rc == 0

    engine = create_engine(fresh_sqlite)
    insp = inspect(engine)
    assert "schema_migrations" in insp.get_table_names()

    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT filename FROM schema_migrations ORDER BY filename")
        ).fetchall()
    got = [r[0] for r in rows]
    assert got == _migration_filenames()


def test_migrate_is_idempotent(fresh_sqlite):
    """Second invocation must not add duplicate rows or error."""
    sys.modules.pop("scripts.migrate", None)
    from scripts import migrate

    assert migrate.run(db_url=fresh_sqlite) == 0
    # Re-run — should be a clean no-op.
    assert migrate.run(db_url=fresh_sqlite) == 0

    engine = create_engine(fresh_sqlite)
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar()
    assert n == len(_migration_filenames())


def test_status_flag_does_not_apply(tmp_path, monkeypatch):
    """--status on an un-migrated DB leaves schema_migrations empty."""
    db_path = tmp_path / "status.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", db_url)

    # No `db.create_all()` here — status mode must not require any
    # app tables, only the tracking table.
    sys.modules.pop("scripts.migrate", None)
    from scripts import migrate

    rc = migrate.run(db_url=db_url, status_only=True)
    assert rc == 0

    engine = create_engine(db_url)
    with engine.connect() as conn:
        n = conn.execute(
            text("SELECT COUNT(*) FROM schema_migrations")
        ).scalar()
    assert n == 0
