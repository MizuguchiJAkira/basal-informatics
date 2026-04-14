"""Strecker background worker — polls ProcessingJob for queued ZIPs.

Runs on a separate Droplet with the full ML stack (PyTorch + SpeciesNet)
installed. The web container (on App Platform, slim image) only accepts
uploads and writes ProcessingJob rows; this process does the actual work.

Claim semantics:
    SELECT ... WHERE status='queued'
      ORDER BY submitted_at
      LIMIT 1
      FOR UPDATE SKIP LOCKED
    UPDATE status='processing', worker_id, claimed_at

SKIP LOCKED lets multiple workers run in parallel safely (Postgres only;
SQLite falls back to "first writer wins" which is fine for a single worker).

Run:
    python -m strecker.worker

Environment:
    DATABASE_URL       — shared Postgres with the web app
    SPACES_BUCKET,
    SPACES_KEY,
    SPACES_SECRET      — shared object storage with the web app
    WORKER_POLL_SECS   — poll interval, default 10
    WORKER_ID          — identifier for this worker, default hostname
    WORKER_STALE_MINS  — reclaim jobs stuck in 'processing' older than this,
                         default 60 (crashes mid-job)
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root is on path when invoked as `python -m strecker.worker`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import settings
from strecker import storage

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("strecker.worker")

POLL_SECS = int(os.environ.get("WORKER_POLL_SECS", "10"))
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())[:64]
STALE_MINS = int(os.environ.get("WORKER_STALE_MINS", "60"))

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    logger.info("Signal %d received — finishing current job then exiting", signum)
    _shutdown = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


def _make_app():
    """Build the Flask app just for DB access (no routes served)."""
    from web.app import create_app
    return create_app(demo=False, site="strecker")


def _claim_next_job(db, ProcessingJob):
    """Atomically claim the oldest queued job. Returns job_id or None."""
    # Postgres path: row-level lock with SKIP LOCKED.
    dialect = db.engine.dialect.name
    if dialect == "postgresql":
        from sqlalchemy import text
        sql = text("""
            SELECT id FROM processing_jobs
            WHERE status = 'queued'
            ORDER BY submitted_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = db.session.execute(sql).first()
        if not row:
            return None
        pj = db.session.get(ProcessingJob, row[0])
    else:
        # SQLite / other: single-writer assumption
        pj = (ProcessingJob.query
              .filter_by(status="queued")
              .order_by(ProcessingJob.submitted_at.asc())
              .first())
        if not pj:
            return None

    pj.status = "processing"
    pj.worker_id = WORKER_ID
    pj.claimed_at = datetime.utcnow()
    db.session.commit()
    return pj.job_id


def _reclaim_stale(db, ProcessingJob):
    """Reset jobs stuck in 'processing' longer than STALE_MINS back to queued.

    Catches workers that crashed mid-job without writing 'error'.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_MINS)
    stale = (ProcessingJob.query
             .filter(ProcessingJob.status == "processing")
             .filter(ProcessingJob.claimed_at < cutoff)
             .all())
    for pj in stale:
        logger.warning("Reclaiming stale job %s (claimed_at=%s, worker=%s)",
                       pj.job_id, pj.claimed_at, pj.worker_id)
        pj.status = "queued"
        pj.worker_id = None
        pj.claimed_at = None
    if stale:
        db.session.commit()


def _process_job(db, ProcessingJob, job_id: str):
    """Run the full Strecker pipeline for one claimed job."""
    from strecker.ingest import ingest
    from strecker.classify import classify
    from strecker.report import generate_report
    from config.species_reference import SPECIES_REFERENCE

    pj = ProcessingJob.query.filter_by(job_id=job_id).first()
    if not pj:
        logger.error("Claimed job %s disappeared", job_id)
        return

    workdir = Path(tempfile.mkdtemp(prefix=f"job_{job_id}_"))
    try:
        # ── 1. Download ZIP from Spaces ──
        if not pj.zip_key:
            raise RuntimeError(f"Job {job_id} has no zip_key")
        local_zip = str(workdir / "upload.zip")
        storage.get_file(pj.zip_key, local_zip)
        logger.info("Job %s: downloaded ZIP (%d bytes)", job_id,
                    os.path.getsize(local_zip))

        # ── 2. Ingest (extract + SpeciesNet) ──
        pj.status = "processing"
        db.session.commit()
        extract_dir = str(workdir / "extracted")
        photos = ingest(zip_path=local_zip, extract_dir=extract_dir,
                        state=pj.state or "TX")

        # ── 3. Classify ──
        pj.status = "classifying"
        db.session.commit()
        detections = classify(photos, demo=False)

        # ── 4. Report ──
        pj.status = "reporting"
        db.session.commit()
        output_dir = workdir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        report_local = str(output_dir / "game_inventory_report.pdf")
        generate_report(
            detections, output_path=report_local,
            property_name=pj.property_name or "My Property", demo=False,
        )

        # ── 5. Upload artifacts ──
        r_key = storage.report_key(job_id)
        storage.put_file(report_local, r_key, content_type="application/pdf")

        appendix_local = output_dir / "events_appendix.csv"
        a_key = None
        if appendix_local.exists():
            a_key = storage.appendix_key(job_id)
            storage.put_file(str(appendix_local), a_key, content_type="text/csv")

        # ── 6. Species summary ──
        species_stats = defaultdict(lambda: {
            "events": set(), "photos": 0, "cameras": set()
        })
        for det in detections:
            sp = species_stats[det.species_key]
            sp["events"].add(det.independent_event_id)
            sp["photos"] += 1
            sp["cameras"].add(det.camera_id)

        species_list = []
        for sp_key, stats in sorted(species_stats.items(),
                                    key=lambda x: -len(x[1]["events"])):
            ref = SPECIES_REFERENCE.get(sp_key, {})
            species_list.append({
                "common_name": ref.get("common_name",
                                       sp_key.replace("_", " ").title()),
                "events": len(stats["events"]),
                "photos": stats["photos"],
                "cameras": len(stats["cameras"]),
            })
        n_events = sum(s["events"] for s in species_list)

        # ── 7. Commit final state ──
        pj.status = "complete"
        pj.n_photos = f"{len(detections):,}"
        pj.n_species = len(species_list)
        pj.n_events = f"{n_events:,}"
        pj.report_key = r_key
        pj.appendix_key = a_key
        pj.species_json = json.dumps(species_list)
        pj.completed_at = datetime.utcnow()
        db.session.commit()

        logger.info("Job %s complete: %d detections, %d species, %d events",
                    job_id, len(detections), len(species_list), n_events)

        # ── 8. Delete the uploaded ZIP to save on storage ──
        storage.delete_file(pj.zip_key)

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        pj.status = "error"
        pj.error_message = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()[-2000:]}"
        pj.completed_at = datetime.utcnow()
        db.session.commit()

    finally:
        # Always clean the working directory
        try:
            import shutil as _shutil
            _shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


def run():
    """Main loop."""
    logger.info("Starting Strecker worker (id=%s, poll=%ds, stale=%dmin)",
                WORKER_ID, POLL_SECS, STALE_MINS)
    logger.info("DB: %s", settings.DATABASE_URL.split("@")[-1]
                if "@" in settings.DATABASE_URL else settings.DATABASE_URL)
    logger.info("Storage: %s",
                f"Spaces/{settings.SPACES_BUCKET}" if settings.SPACES_BUCKET
                else f"local/{settings.UPLOAD_DIR}")

    app = _make_app()

    with app.app_context():
        from db.models import db, ProcessingJob

        while not _shutdown:
            try:
                _reclaim_stale(db, ProcessingJob)
                job_id = _claim_next_job(db, ProcessingJob)
                if job_id:
                    logger.info("Claimed job %s", job_id)
                    _process_job(db, ProcessingJob, job_id)
                else:
                    # No work; sleep with early-exit on shutdown signal
                    for _ in range(POLL_SECS):
                        if _shutdown:
                            break
                        time.sleep(1)
            except Exception:
                logger.exception("Worker loop error; backing off 30s")
                db.session.rollback()
                for _ in range(30):
                    if _shutdown:
                        break
                    time.sleep(1)

    logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    run()
