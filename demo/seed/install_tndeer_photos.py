"""Install real TNDeer trail-cam photos into the Edwards Plateau demo.

The synthetic Edwards Plateau Ranch demo (demo/output/sorted/) ships with
12,019 filename slots across 12 species. Most slots are zero-byte
placeholders the photo server synthesizes imagery for at render time;
~88 slots are real iNaturalist-style synthetic JPEGs.

This script overlays **real trail-cam photos** from the TNDeer fixture
(tests/fixtures/tndeer_sd_card.zip — 142 photos from a 5-year Cumberland
Plateau TN hunter archive) onto existing synthetic filenames so that
clicking through the dashboard shows authentic imagery.

Scope:
  * Filter out black_bear (18) + elk (15) + null-labeled (35) —
    biogeographically implausible for a Kimble County TX Hill-Country
    parcel. Leaves 73 photos: 25 white-tail, 18 coyote, 14 feral_hog,
    10 turkey, 4 raccoon, 1 bobcat, 1 fox, 1 squirrel.
  * For each TX-plausible TNDeer species, distribute its photos
    round-robin across existing filenames in
    demo/output/sorted/<species>/. The fox photo is copied to both
    red_fox/ and gray_fox/ (TNDeer fixture doesn't distinguish).
  * Squirrel → no matching species directory in existing sorted/, skip.

Non-goals:
  * Does NOT modify manifest.csv or detections.json. The 12K-record
    statistical spine stays intact so the Nature Exposure Report
    (tier, density, CI) still looks demo-weighty.
  * Does NOT touch camera setup, seasons, or any DB state. Pure file
    operation on demo/output/sorted/.

Idempotent: re-running re-copies the same TNDeer bytes to the same
filenames. No side effects beyond file writes.

Usage (from repo root):
    python3 demo/seed/install_tndeer_photos.py
    python3 demo/seed/install_tndeer_photos.py --dry-run   # plan only
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("install_tndeer_photos")
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
)

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
TNDEER_ZIP = REPO_ROOT / "tests" / "fixtures" / "tndeer_sd_card.zip"
TNDEER_MANIFEST = REPO_ROOT / "tests" / "fixtures" / "tndeer_sd_card.manifest.json"
SORTED_ROOT = REPO_ROOT / "demo" / "output" / "sorted"

# Species excluded for biogeographic plausibility (Kimble County TX)
EXCLUDE_SPECIES = {"black_bear", "elk"}

# Map TNDeer species label → one or more target directories under sorted/.
# "fox" in TNDeer is unresolved (red vs gray); copy it to both.
# "squirrel" has no target dir in existing sorted/ (ignore).
TNDEER_TO_SORTED: dict[str, tuple[str, ...]] = {
    "white_tailed_deer": ("white_tailed_deer",),
    "coyote": ("coyote",),
    "feral_hog": ("feral_hog",),
    "turkey": ("turkey",),
    "raccoon": ("raccoon",),
    "bobcat": ("bobcat",),
    "fox": ("red_fox", "gray_fox"),
}


def load_selected_tndeer_photos() -> dict[str, list[dict]]:
    """Return {species: [photo_record, ...]} for TX-plausible TNDeer photos."""
    if not TNDEER_MANIFEST.exists():
        sys.exit(f"Missing TNDeer manifest: {TNDEER_MANIFEST}")
    if not TNDEER_ZIP.exists():
        sys.exit(f"Missing TNDeer source ZIP: {TNDEER_ZIP}")

    manifest = json.load(TNDEER_MANIFEST.open())
    by_species: dict[str, list[dict]] = defaultdict(list)
    for p in manifest["photos"]:
        species = p.get("species_ground_truth")
        if not species:
            continue  # skip the 35 null-labeled
        if species in EXCLUDE_SPECIES:
            continue
        if species not in TNDEER_TO_SORTED:
            continue  # squirrel + anything else without a sorted/ target
        by_species[species].append(p)
    return by_species


def distribute_evenly(
    src_photos: list[bytes], target_files: list[Path],
) -> list[tuple[bytes, Path]]:
    """Return list of (photo_bytes, dest_path) pairs that evenly distribute
    the N source photos across the K target files, K >= N.

    Step = K // N. At step intervals, write one TNDeer photo (round-robin
    through src). If there are many more targets than sources (K >> N),
    multiple targets get the same TNDeer photo — that's fine for a demo.
    """
    if not src_photos or not target_files:
        return []
    n_src = len(src_photos)
    n_tgt = len(target_files)
    # Write each target_files[i * (n_tgt / n_src_copies)] with src_photos[i % n_src].
    # Aim for ~2× coverage so random clicks hit a real photo most of the time.
    # Empirically: n_writes = min(n_tgt, max(n_src * 3, 30))
    n_writes = min(n_tgt, max(n_src * 3, 30))
    if n_writes == 0:
        return []
    assignments = []
    stride = n_tgt / n_writes
    for i in range(n_writes):
        idx = int(i * stride)
        if idx >= n_tgt:
            break
        photo_bytes = src_photos[i % n_src]
        assignments.append((photo_bytes, target_files[idx]))
    return assignments


def install(dry_run: bool = False) -> None:
    by_species = load_selected_tndeer_photos()
    logger.info(
        "loaded TNDeer selection: %d species, %d photos total",
        len(by_species),
        sum(len(v) for v in by_species.values()),
    )

    # Open the zip once; pull requested arcnames lazily.
    with zipfile.ZipFile(TNDEER_ZIP) as zf:
        for tndeer_species, photos in by_species.items():
            src_bytes = [zf.read(p["arcname"]) for p in photos]

            for target_dir_name in TNDEER_TO_SORTED[tndeer_species]:
                target_dir = SORTED_ROOT / target_dir_name
                if not target_dir.exists():
                    logger.warning(
                        "target dir missing, skipping: %s", target_dir,
                    )
                    continue

                target_files = sorted(
                    target_dir.glob("*.jpg"),
                    key=lambda p: p.name,
                )
                assignments = distribute_evenly(src_bytes, target_files)

                logger.info(
                    "%s  → %-18s   %d photos  × writing %d slots  (of %d total)",
                    tndeer_species,
                    target_dir_name,
                    len(src_bytes),
                    len(assignments),
                    len(target_files),
                )

                if dry_run:
                    continue

                for photo_bytes, dest in assignments:
                    dest.write_bytes(photo_bytes)

    if dry_run:
        logger.info("dry run complete; no files written")
    else:
        logger.info("TNDeer photos installed to demo/output/sorted/")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the install plan without touching files",
    )
    args = parser.parse_args()
    install(dry_run=args.dry_run)
