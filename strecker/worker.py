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
    """Atomically claim the oldest queued job. Returns job_id or None.

    CRITICAL: every code path must end with commit() or rollback().
    On Postgres, the SELECT FOR UPDATE opens an implicit transaction;
    returning None without rollback leaves the connection "idle in
    transaction" forever, exhausting the connection pool over hours.
    """
    dialect = db.engine.dialect.name
    try:
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
                db.session.rollback()  # release the implicit txn
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
    except Exception:
        db.session.rollback()
        raise


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


def _quarter_for(ts: datetime):
    """Return (quarter_index 0..3, start_date, end_date, label) for a timestamp."""
    from datetime import date
    q = (ts.month - 1) // 3
    start = date(ts.year, q * 3 + 1, 1)
    if q == 3:
        end = date(ts.year, 12, 31)
    else:
        end = date(ts.year, (q + 1) * 3 + 1, 1) - timedelta(days=1)
    label = ["Spring", "Summer", "Fall", "Winter"][q] + f" {ts.year}"
    return q, start, end, label


def _common_name_map():
    """species_key -> human-friendly common name, lazily loaded from the
    reference config. Cached after first call."""
    cached = getattr(_common_name_map, "_cache", None)
    if cached is not None:
        return cached
    try:
        from config.species_reference import SPECIES_REFERENCE
        m = {k: v.get("common_name") for k, v in SPECIES_REFERENCE.items()
             if v.get("common_name")}
    except Exception:
        m = {}
    _common_name_map._cache = m
    return m


def _is_real_species_key(key):
    """Skip SpeciesNet internal "blank" / "no_cv_result" UUID class ids
    before aggregation. Those keys leak into the Basal dashboard as
    garbage rows like "f1856211-...-;;;;;;blank" otherwise.

    A legitimate species_key is lowercase + underscores (e.g.
    "feral_hog", "white_tailed_deer"). Anything containing a UUID
    fragment, "blank", or "no_cv_result" is filtered.
    """
    if not key or not isinstance(key, str):
        return False
    if "no_cv_result" in key or ";" in key:
        return False
    # UUID patterns: 8-4-4-4-12 hex chars with dashes
    import re
    if re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-", key):
        return False
    if key == "blank" or key == "unknown":
        return False
    return True


def _aggregate_to_property(db, pj, detections, extract_dir=None):
    """Per-property aggregation: auto-create Cameras, slice detections
    across Season windows, upsert DetectionSummary rows.

    Cameras: top-level folder of the ZIP → camera_label (via det.camera_id
    which strecker.ingest already derives).
    Seasons: each detection is routed to the existing Season whose
    ``[start_date, end_date]`` covers its timestamp; when no Season
    matches, a calendar-year season ``"Auto-detected YYYY deployment"``
    is auto-created. This is what lets a single SD-card ZIP that spans
    multiple years produce one DetectionSummary per (year, camera, species)
    instead of collapsing into whichever Season happened to be active.
    See ``strecker.seasons.resolve_seasons_for_detections``.
    DetectionSummary: (season_id, camera_id, species_key) is unique; sum.
    Filters out SpeciesNet's "blank" / "no_cv_result" internal classes.

    Photos: when ``extract_dir`` is provided, each detection's image is
    uploaded to Spaces under ``photos/<property_id>/<job_id>/<hash>.jpg``
    and a Photo row is inserted so the dashboard gallery can surface it.
    Photo upload is fail-soft — a Spaces hiccup doesn't fail the whole
    pipeline; aggregate stats still land.
    """
    import hashlib
    import json as _json
    import os
    from db.models import Camera, Season, Upload, DetectionSummary, Photo
    from config import settings as _settings
    from strecker.seasons import group_detections_by_season

    # Strip SpeciesNet "blank"/"no_cv_result" detections before anything
    # else; they'd otherwise create phantom DetectionSummary rows that
    # confuse the dashboard.
    detections = [d for d in detections if _is_real_species_key(d.species_key)]

    if not detections:
        return

    # 1. Auto-create cameras keyed on camera_label
    labels = {d.camera_id for d in detections if d.camera_id}
    existing_cams = {
        c.camera_label: c
        for c in Camera.query.filter_by(property_id=pj.property_id).all()
    }
    for label in labels:
        if label not in existing_cams:
            cam = Camera(
                property_id=pj.property_id,
                camera_label=label[:50],
                name=label[:120],
                is_active=True,
            )
            db.session.add(cam)
            existing_cams[label] = cam
    db.session.flush()  # populate cam.id

    # 2. Partition detections across Season windows, auto-creating a
    # calendar-year Season for any detection whose timestamp falls
    # outside every existing Season for this property. Single-season
    # uploads (the common case) still return a one-entry list, so we
    # don't pay per-season overhead for them.
    season_groups = group_detections_by_season(
        db, Season, pj.property_id, detections)
    # Maintain the legacy ``seasons`` + ``by_quarter`` shapes downstream
    # needs (primary-season-for-Upload pick, log message count).
    seasons = {s.id: s for s, _ in season_groups}
    by_season_dets = {s.id: dets for s, dets in season_groups}

    # 3. Aggregate into per-(season, camera, species) buckets
    agg = defaultdict(lambda: {
        "photos": 0,
        "events": set(),
        "confidences": [],
        "first_seen": None,
        "last_seen": None,
        "buck": 0,
        "doe": 0,
        "hourly": [0] * 24,
    })
    # Build a detection → season map once (id() keyed — detection objects
    # are plain dataclasses, no __hash__ collisions to worry about across
    # a single batch).
    det_to_season = {}
    for season, dets in season_groups:
        for d in dets:
            det_to_season[id(d)] = season
    for d in detections:
        if not d.camera_id:
            continue
        cam = existing_cams.get(d.camera_id)
        if not cam:
            continue
        season = det_to_season.get(id(d))
        if season is None:
            continue  # detection had no timestamp; skip
        key = (season.id, cam.id, d.species_key)
        a = agg[key]
        a["photos"] += 1
        if d.independent_event_id:
            a["events"].add(d.independent_event_id)
        conf = d.confidence_calibrated if d.confidence_calibrated is not None else d.confidence
        a["confidences"].append(conf)
        ts = d.timestamp
        if a["first_seen"] is None or ts < a["first_seen"]:
            a["first_seen"] = ts
        if a["last_seen"] is None or ts > a["last_seen"]:
            a["last_seen"] = ts
        if d.antler_classification == "buck":
            a["buck"] += 1
        elif d.antler_classification == "doe":
            a["doe"] += 1
        a["hourly"][ts.hour] += 1

    # 4. Upsert DetectionSummary rows
    for (season_id, camera_id, species_key), a in agg.items():
        hourly = a["hourly"]
        peak_hour = hourly.index(max(hourly)) if max(hourly) > 0 else None
        avg_conf = (round(sum(a["confidences"]) / len(a["confidences"]), 4)
                    if a["confidences"] else None)
        existing = DetectionSummary.query.filter_by(
            season_id=season_id, camera_id=camera_id, species_key=species_key,
        ).first()
        if existing:
            existing.total_photos = (existing.total_photos or 0) + a["photos"]
            existing.independent_events = (
                (existing.independent_events or 0) + len(a["events"]))
            if avg_conf is not None:
                existing.avg_confidence = avg_conf
            if a["first_seen"] and (not existing.first_seen
                                    or a["first_seen"] < existing.first_seen):
                existing.first_seen = a["first_seen"]
            if a["last_seen"] and (not existing.last_seen
                                   or a["last_seen"] > existing.last_seen):
                existing.last_seen = a["last_seen"]
            existing.buck_count = (existing.buck_count or 0) + a["buck"]
            existing.doe_count = (existing.doe_count or 0) + a["doe"]
            existing.peak_hour = peak_hour
            existing.hourly_distribution = _json.dumps(hourly)
        else:
            db.session.add(DetectionSummary(
                season_id=season_id,
                camera_id=camera_id,
                species_key=species_key,
                total_photos=a["photos"],
                independent_events=len(a["events"]),
                avg_confidence=avg_conf,
                first_seen=a["first_seen"],
                last_seen=a["last_seen"],
                buck_count=a["buck"],
                doe_count=a["doe"],
                peak_hour=peak_hour,
                hourly_distribution=_json.dumps(hourly),
            ))

    # 4b. Upload classified photos to Spaces + insert Photo rows.
    # Skipped when extract_dir isn't provided (e.g. legacy code paths,
    # tests). Fail-soft: a Spaces error here doesn't roll back the
    # DetectionSummary work above — the dashboard KPIs / density still
    # render, the gallery just stays empty for that job.
    if extract_dir:
        # Commit the DetectionSummary work first. If photo upload then
        # hits a per-row integrity problem (schema width mismatch,
        # encoding quirk, etc.), we can rollback *just* that savepoint
        # and keep the KPIs the hunter sees. Without this split, a
        # single bad row poisoned the whole transaction and we lost
        # the aggregate numbers too.
        try:
            db.session.commit()
        except Exception:
            logger.exception("DetectionSummary commit failed; rolling back")
            db.session.rollback()
            raise

        from strecker import storage as _storage
        common = _common_name_map()
        photos_added = 0
        photo_failures = 0
        for d in detections:
            if not d.camera_id or not d.image_filename:
                continue
            cam = existing_cams.get(d.camera_id)
            if not cam:
                continue
            season = det_to_season.get(id(d))
            season_id = season.id if season else None
            local_path = os.path.join(extract_dir, d.image_filename)
            if not os.path.exists(local_path):
                continue
            digest = hashlib.sha1(
                f"{pj.job_id}:{d.image_filename}".encode("utf-8")
            ).hexdigest()[:16]
            spaces_key = f"photos/{pj.property_id}/{pj.job_id}/{digest}.jpg"

            # Savepoint-per-row: a schema overflow or encoding problem
            # on one detection rolls back ONE row, not the whole batch.
            try:
                existing_photo = Photo.query.filter_by(
                    spaces_key=spaces_key
                ).first()
                if existing_photo:
                    continue
                _storage.put_file(
                    local_path, spaces_key, content_type="image/jpeg",
                )
                conf = (d.confidence_calibrated
                        if d.confidence_calibrated is not None
                        else d.confidence)
                db.session.add(Photo(
                    property_id=pj.property_id,
                    camera_id=cam.id,
                    season_id=season_id,
                    processing_job_id=pj.job_id,
                    spaces_key=spaces_key,
                    original_name=os.path.basename(d.image_filename),
                    species_key=d.species_key,
                    common_name=common.get(
                        d.species_key,
                        d.species_key.replace("_", " ").title(),
                    ),
                    confidence=conf,
                    independent_event_id=d.independent_event_id,
                    review_required=bool(d.review_required),
                    taken_at=d.timestamp,
                ))
                db.session.flush()
                photos_added += 1
            except Exception:
                logger.exception(
                    "Photo row failed (%s); rolling back just this row",
                    spaces_key,
                )
                db.session.rollback()
                photo_failures += 1
        try:
            db.session.commit()
        except Exception:
            logger.exception("Photo-batch final commit failed")
            db.session.rollback()
        if photos_added or photo_failures:
            logger.info(
                "Job %s: uploaded %d photos (%d failed) to Spaces + "
                "inserted Photo rows",
                pj.job_id, photos_added, photo_failures,
            )

    # 5. Mark the Upload complete
    if pj.upload_id:
        up = Upload.query.get(pj.upload_id)
        if up:
            up.status = "complete"
            up.photo_count = len(detections)
            up.processed_at = datetime.utcnow()
            # Link to the season with the most detections (primary season)
            if by_season_dets:
                primary_sid = max(
                    by_season_dets.items(), key=lambda kv: len(kv[1]))[0]
                up.season_id = primary_sid

    db.session.commit()
    logger.info("Job %s aggregated to property %s: %d cameras, %d seasons, %d summaries",
                pj.job_id, pj.property_id, len(existing_cams),
                len(seasons), len(agg))


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

        # Short-circuit when SpeciesNet finds nothing. Real cards can
        # legitimately return zero detections (all false triggers, wind,
        # weather, rejected small animals). The report generator assumes
        # at least one detection — calling it here used to crash with
        # "min() arg is an empty sequence". Mark the job complete with
        # zero stats instead of erroring out on the hunter.
        if not detections:
            logger.info("Job %s: 0 detections — skipping report", job_id)
            pj.status = "complete"
            pj.n_photos = str(len(photos) if photos else 0)
            pj.n_species = 0
            pj.n_events = "0"
            pj.species_json = "[]"
            pj.completed_at = datetime.utcnow()
            db.session.commit()
            return

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

        # ── 6b. Filename-derived accuracy report (opt-in) ──
        # If the hunter curated their SD card with species words in
        # filenames (e.g. "CF Pig 2025-05-19 Goldilocks MH.JPG"),
        # reconcile classifier predictions against those labels and
        # attach a per-species confusion report to the ProcessingJob
        # row. Silent no-op when no filenames carry labels.
        try:
            from strecker.filename_labels import build_accuracy_report
            pairs = [
                (getattr(d, "filename", None) or
                 getattr(d, "photo_path", None) or "",
                 d.species_key)
                for d in detections
            ]
            acc = build_accuracy_report(pairs)
            if acc["n_labeled"] > 0:
                pj.accuracy_report_json = json.dumps(acc)
                logger.info(
                    "Job %s accuracy: %d/%d labeled photos matched "
                    "(%d missed, %d confused)",
                    job_id, acc["n_matched"], acc["n_labeled"],
                    acc["n_missed"], acc["n_confused"])
        except Exception:
            logger.exception("Job %s: accuracy report failed (non-fatal)",
                             job_id)

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

        # ── 7b. Property-scoped aggregation (dashboard data) ──
        if pj.property_id:
            try:
                _aggregate_to_property(db, pj, detections,
                                       extract_dir=extract_dir)
            except Exception:
                logger.exception(
                    "Job %s: pipeline OK but aggregation failed", job_id)
                db.session.rollback()
                # Don't fail the whole job — the PDF is still valid. Mark the
                # linked Upload (if any) as errored so the UI surfaces it.
                if pj.upload_id:
                    from db.models import Upload
                    up = Upload.query.get(pj.upload_id)
                    if up:
                        up.status = "error"
                        up.error_message = "Aggregation failed; see worker logs"
                        db.session.commit()

        # ── 8. Delete the uploaded ZIP to save on storage ──
        storage.delete_file(pj.zip_key)

    except Exception as e:
        logger.exception("Job %s failed", job_id)
        pj.status = "error"
        pj.error_message = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()[-2000:]}"
        pj.completed_at = datetime.utcnow()
        # Mirror failure onto the linked Upload
        if pj.upload_id:
            try:
                from db.models import Upload
                up = Upload.query.get(pj.upload_id)
                if up:
                    up.status = "error"
                    up.error_message = str(e)[:500]
            except Exception:
                pass
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
