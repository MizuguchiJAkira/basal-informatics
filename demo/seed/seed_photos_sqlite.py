"""Populate the demo Photo Gallery for Edwards Plateau Ranch (SQLite).

The local demo DB seeds detection counts + species cards but leaves the
``photos`` table empty, so the dashboard's Photo Gallery renders
"No photos found." This seeder walks ``demo/output/sorted/<species>/``
for real-byte JPEGs (skips zero-byte placeholder filenames), parses
camera label + timestamp out of the filename, and inserts Photo rows
that point at the existing ``/photos/<species>/<filename>`` Flask route
via ``spaces_key="local/<species>/<filename>"``.

Idempotent: re-running deletes prior local-key Photo rows for property 1
and re-inserts.

Usage (from repo root):
    python3 demo/seed/seed_photos_sqlite.py
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + str(REPO_ROOT / "instance" / "basal.db"),
)
os.environ.setdefault("FLASK_SECRET_KEY", "dev")

from web.app import create_app  # noqa: E402
from db.models import db, Photo, Camera  # noqa: E402

PROPERTY_ID = 1
SORTED_ROOT = REPO_ROOT / "demo" / "output" / "sorted"
MIN_BYTES = 1024  # skip empty/placeholder files

FILENAME_RE = re.compile(
    r"^(CAM-[\w-]+)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_\d+\.jpg$",
    re.IGNORECASE,
)


def main() -> int:
    app = create_app(demo=True, site="strecker")
    with app.app_context():
        cams = {
            c.camera_label: c.id
            for c in Camera.query.filter_by(property_id=PROPERTY_ID).all()
        }
        if not cams:
            print(f"No cameras for property {PROPERTY_ID}", file=sys.stderr)
            return 1

        # Wipe prior local-keyed photos for this property so the seeder
        # is idempotent without trampling real Spaces photos (none in dev,
        # but the partition keeps prod safe if someone runs this).
        deleted = (
            Photo.query
            .filter(Photo.property_id == PROPERTY_ID)
            .filter(Photo.spaces_key.like("local/%"))
            .delete(synchronize_session=False)
        )
        print(f"Cleared {deleted} prior local-keyed photos.")

        # SQLite + BigInteger PK doesn't autoincrement reliably under
        # SQLAlchemy without an explicit value; seed our own.
        next_id = (db.session.query(db.func.coalesce(
            db.func.max(Photo.id), 0)).scalar() or 0) + 1

        inserted = 0
        skipped_no_cam = 0
        for sp_dir in sorted(SORTED_ROOT.iterdir()):
            if not sp_dir.is_dir():
                continue
            species = sp_dir.name
            for jpg in sorted(sp_dir.glob("*.jpg")):
                if jpg.stat().st_size < MIN_BYTES:
                    continue
                m = FILENAME_RE.match(jpg.name)
                if not m:
                    continue
                cam_label = m.group(1).upper()
                cam_id = cams.get(cam_label)
                if cam_id is None:
                    skipped_no_cam += 1
                    continue
                taken = datetime(
                    int(m.group(2)), int(m.group(3)), int(m.group(4)),
                    int(m.group(5)), int(m.group(6)), int(m.group(7)),
                )
                spaces_key = f"local/{species}/{jpg.name}"
                p = Photo(
                    id=next_id,
                    property_id=PROPERTY_ID,
                    camera_id=cam_id,
                    spaces_key=spaces_key,
                    original_name=jpg.name,
                    species_key=species,
                    common_name=species.replace("_", " ").title(),
                    confidence=0.92,
                    taken_at=taken,
                )
                db.session.add(p)
                next_id += 1
                inserted += 1

        db.session.commit()
        print(f"Inserted {inserted} photos "
              f"({skipped_no_cam} skipped — camera not on property).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
