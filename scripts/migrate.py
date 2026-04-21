#!/usr/bin/env python3
"""Apply idempotent SQL migrations from db/migrations/.

Usage:
    python scripts/migrate.py              # apply all pending
    python scripts/migrate.py --status     # list applied / pending, don't apply
    python scripts/migrate.py --db URL     # override DATABASE_URL

The codebase uses ``db.create_all()`` for initial schema creation, which
handles greenfield deploys fine but CANNOT evolve an already-created
database: it never issues ``ALTER TABLE`` and never creates columns on
tables that already exist. Any schema change that landed after the
production database was first provisioned therefore needs a real
migration.

This script is the bridge. It maintains a ``schema_migrations`` table
that records which ``NNNN_*.sql`` files have already been applied and
runs the remaining ones in filename order. Each migration is expected
to be idempotent (``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE …
ADD COLUMN IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``) so
re-running is a no-op even in unusual recovery scenarios.

Works against both Postgres (production) and SQLite (local/tests).
On SQLite, statements that Postgres supports but SQLite does not
(``ADD COLUMN IF NOT EXISTS``) are executed tolerantly: a
"duplicate column" / "already exists" error is treated as success,
which matches the idempotent intent of the migration file.
"""

import argparse
import os
import pathlib
import re
import sys
from datetime import datetime

# Ensure project root is on path whether invoked as `python scripts/migrate.py`
# from the repo root or directly.
_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from sqlalchemy import create_engine, text  # noqa: E402


MIGRATIONS_DIR = _ROOT / "db" / "migrations"
TRACKING_TABLE = "schema_migrations"


# -- Dialect tolerance --------------------------------------------------

# Phrases that indicate "the thing you asked me to add is already
# there" — safe to ignore when running an idempotent migration.
_BENIGN_ERROR_FRAGMENTS = (
    "already exists",
    "duplicate column",
    "duplicate column name",
)


def _split_statements(sql: str):
    """Split a SQL file into individual statements.

    Simple splitter: strips line comments, splits on ``;``. Migration
    scripts in this project are intentionally kept to a handful of
    top-level DDL statements, so this is sufficient — no need for a
    real SQL parser.
    """
    # Strip full-line `--` comments so they don't confuse the splitter.
    stripped = re.sub(r"(?m)^\s*--.*$", "", sql)
    parts = [p.strip() for p in stripped.split(";")]
    return [p for p in parts if p]


def _is_benign(err: Exception) -> bool:
    msg = str(err).lower()
    return any(frag in msg for frag in _BENIGN_ERROR_FRAGMENTS)


def _translate_for_sqlite(stmt: str) -> str:
    """SQLite doesn't support ``ADD COLUMN IF NOT EXISTS`` syntax.

    Strip the ``IF NOT EXISTS`` so the statement becomes plain
    ``ALTER TABLE … ADD COLUMN …``. We then rely on the tracking
    table + tolerant execution (``_is_benign``) to keep re-runs safe.
    """
    return re.sub(
        r"ADD COLUMN IF NOT EXISTS",
        "ADD COLUMN",
        stmt,
        flags=re.IGNORECASE,
    )


def _sqlite_existing_tables(conn) -> set[str]:
    rows = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")
    ).fetchall()
    return {r[0] for r in rows}


def _sqlite_existing_columns(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


_CREATE_TABLE_RE = re.compile(
    r"^\s*CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_ALTER_ADD_COL_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+"
    r"(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_CREATE_INDEX_RE = re.compile(
    r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+ON\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
# Postgres-only constructs — SQLite simply can't run these. We match
# them up front so the migration file stays single-source and the
# runner silently skips them on SQLite. On Postgres they execute
# normally; idempotence there is either baked into the statement
# ("IF NOT EXISTS") or into the benign-error fallback below.
_ALTER_ADD_CONSTRAINT_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+[A-Za-z_][A-Za-z0-9_]*\s+ADD\s+CONSTRAINT\b",
    re.IGNORECASE | re.DOTALL,
)
_ALTER_COLUMN_TYPE_RE = re.compile(
    r"^\s*ALTER\s+TABLE\s+[A-Za-z_][A-Za-z0-9_]*\s+ALTER\s+COLUMN\s+"
    r"[A-Za-z_][A-Za-z0-9_]*\s+(?:SET\s+DATA\s+)?TYPE\b",
    re.IGNORECASE | re.DOTALL,
)


def _should_skip_on_sqlite(conn, stmt: str) -> bool:
    """Decide if a Postgres-flavoured DDL statement should be skipped
    on SQLite because the target object already exists.

    SQLite will choke on ``SERIAL``, ``TIMESTAMPTZ``, etc. even inside
    a ``CREATE TABLE IF NOT EXISTS`` block — the parser rejects the
    body before the existence check kicks in. So for idempotence on
    the SQLite test harness we pre-check ourselves and skip.
    """
    m = _CREATE_TABLE_RE.match(stmt)
    if m:
        return m.group(1).lower() in {t.lower() for t in _sqlite_existing_tables(conn)}
    m = _ALTER_ADD_COL_RE.match(stmt)
    if m:
        table, col = m.group(1), m.group(2)
        if table.lower() not in {t.lower() for t in _sqlite_existing_tables(conn)}:
            # Nothing to alter — underlying table isn't in this DB.
            return True
        cols = {c.lower() for c in _sqlite_existing_columns(conn, table)}
        return col.lower() in cols
    m = _CREATE_INDEX_RE.match(stmt)
    if m:
        idx_name = m.group(1)
        rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name=:n"
            ),
            {"n": idx_name},
        ).fetchall()
        return bool(rows)
    # Postgres-only DDL — skip unconditionally on SQLite. These carry
    # no matching obligation on SQLite's side (no referential integrity
    # enforcement, no fixed column length), so skipping is correct, not
    # just tolerant.
    if _ALTER_ADD_CONSTRAINT_RE.match(stmt):
        return True
    if _ALTER_COLUMN_TYPE_RE.match(stmt):
        return True
    return False


# -- Core ---------------------------------------------------------------


def _resolve_database_url(cli_override: str | None) -> str:
    if cli_override:
        url = cli_override
    else:
        url = os.environ.get("DATABASE_URL")
    if not url:
        # Fall back to settings.py default — keeps the script usable
        # in dev where only `instance/basal.db` is set up.
        try:
            from config import settings

            url = settings.DATABASE_URL
        except Exception:
            url = "sqlite:///basal.db"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _ensure_tracking_table(conn, is_sqlite: bool) -> None:
    if is_sqlite:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
                    filename    TEXT PRIMARY KEY,
                    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    else:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {TRACKING_TABLE} (
                    filename    TEXT PRIMARY KEY,
                    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


def _applied_set(conn) -> set[str]:
    rows = conn.execute(
        text(f"SELECT filename FROM {TRACKING_TABLE}")
    ).fetchall()
    return {r[0] for r in rows}


def _discover_migrations() -> list[pathlib.Path]:
    if not MIGRATIONS_DIR.is_dir():
        return []
    files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    return files


def run(db_url: str | None = None, status_only: bool = False) -> int:
    url = _resolve_database_url(db_url)
    engine = create_engine(url)
    is_sqlite = engine.dialect.name == "sqlite"

    files = _discover_migrations()
    if not files:
        print("No migration files found in db/migrations/.")
        return 0

    with engine.begin() as conn:
        _ensure_tracking_table(conn, is_sqlite)
        applied = _applied_set(conn)

    pending = [f for f in files if f.name not in applied]

    # Drift detection: filenames in the tracker that we don't have a
    # matching file for on disk. This happens when someone runs
    # migrate.py from a container/checkout that's older than the
    # tracker — the file was applied from a newer codebase but the
    # runner can't see it, and the "Up to date" message masks that
    # the current checkout is NOT in sync. Loud warning so the
    # operator knows to redeploy (or git pull) before trusting the
    # state.
    file_names = {f.name for f in files}
    orphan = sorted(applied - file_names)
    if orphan:
        print(
            "⚠️  WARNING: tracker records migrations that aren't in "
            "this checkout. Your migrations/ dir is OLDER than the "
            "database. Rebuild or git pull, then re-run this."
        )
        for name in orphan:
            print(f"    tracker has   {name}  (no matching file here)")

    if status_only:
        print(f"Database: {url.split('@')[-1] if '@' in url else url}")
        print(f"Applied ({len(applied)}):")
        for f in files:
            if f.name in applied:
                print(f"  [x] {f.name}")
        print(f"Pending ({len(pending)}):")
        for f in pending:
            print(f"  [ ] {f.name}")
        return 0

    if not pending:
        print(f"Up to date — {len(applied)} migration(s) already applied.")
        return 0

    print(f"Applying {len(pending)} migration(s) against "
          f"{'sqlite' if is_sqlite else 'postgres'}…")

    for path in pending:
        print(f"  → {path.name}")
        sql = path.read_text()
        statements = _split_statements(sql)
        if is_sqlite:
            statements = [_translate_for_sqlite(s) for s in statements]

        # Run each migration file in its own transaction so one failure
        # doesn't leave the tracking table half-written.
        with engine.begin() as conn:
            for stmt in statements:
                if is_sqlite and _should_skip_on_sqlite(conn, stmt):
                    # Pre-filter: the target table/column/index already
                    # exists under db.create_all(), so the Postgres DDL
                    # (which SQLite can't parse) would be a no-op anyway.
                    continue
                try:
                    conn.execute(text(stmt))
                except Exception as e:  # noqa: BLE001
                    if _is_benign(e):
                        # Re-run case (migration was partially applied,
                        # or we're running on SQLite where `ADD COLUMN
                        # IF NOT EXISTS` can't be expressed natively).
                        continue
                    raise
            conn.execute(
                text(
                    f"INSERT INTO {TRACKING_TABLE}(filename, applied_at) "
                    f"VALUES (:f, :t)"
                ),
                {"f": path.name, "t": datetime.utcnow()},
            )

    print(f"Done. {len(pending)} migration(s) applied.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", help="Database URL (overrides DATABASE_URL)")
    ap.add_argument(
        "--status", action="store_true",
        help="Show applied / pending migrations, don't apply anything",
    )
    args = ap.parse_args()
    return run(db_url=args.db, status_only=args.status)


if __name__ == "__main__":
    sys.exit(main())
