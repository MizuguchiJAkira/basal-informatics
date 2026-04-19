#!/usr/bin/env python3
"""Curate a Basal-compatible regression fixture from the TNDeer dump.

The TNDeer dump is a real hunter's five-year curated trail-cam archive
— 855 photos across 14 camera models on a Cumberland-Plateau TN
property. 239 of the photos carry species labels in their filenames
(``CF Pig 2025-05-19 Goldilocks MH.JPG`` → species=pig, station=MH).

This script selects a balanced ~120-photo subset, preserves the
originals' bytes (and thus their native per-manufacturer EXIF
quirks), and emits a ZIP + a MANIFEST.json recording per-photo
ground truth extracted from filenames.

Produces the first-class classifier regression fixture, replacing
the iNaturalist synthetic set (sd_card.zip) for accuracy work —
real trail-cam aesthetic, real EXIF, real camera-manufacturer
fingerprints, real deployment-style frequency distributions.

Not redistributed — gitignored. Build requires the source ZIP on
the local machine.

Usage
-----
    python scripts/build_tndeer_fixture.py \\
        --src ~/Downloads/TNDeer\\ Transfer\\ Pics-20260419T180219Z-3-001.zip

    # or with explicit output
    python scripts/build_tndeer_fixture.py --src <zip> --out <path>

Defaults
--------
- Output: ``tests/fixtures/tndeer_sd_card.zip``
- ~25 photos per hand-labeled species (cap)
- ~35 unlabeled Moultrie-default-named (MFDC####) for empty-frame controls
"""

import argparse
import io
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Filename → ground-truth mapping
# ---------------------------------------------------------------------------

_SPECIES_WORDS = re.compile(
    r'\b(Pig|Hog|Deer|Buck|Doe|Fawn|Elk|Turkey|Bear|Coyote|Fox|'
    r'Bobcat|Raccoon|Opossum|Squirrel)\b',
    re.IGNORECASE)

_SPECIES_MAP = {
    "pig": "feral_hog", "hog": "feral_hog",
    "deer": "white_tailed_deer", "buck": "white_tailed_deer",
    "doe": "white_tailed_deer", "fawn": "white_tailed_deer",
    "elk": "elk", "turkey": "turkey", "bear": "black_bear",
    "coyote": "coyote", "fox": "fox",
    "bobcat": "bobcat", "raccoon": "raccoon",
    "opossum": "opossum", "squirrel": "squirrel",
}

_MFDC_PAT = re.compile(r'^MFDC\d+\.JPG$', re.I)

# Station suffix — 2–3 letter code right before ".JPG", optionally
# after a descriptor like "Big 10", "5X3", "(7)".
_STATION_PAT = re.compile(
    r'\b([A-Z]{2,3})'
    r'\s*(?:\([0-9]+\)|\d+\s*(?:pt|PT)?|[A-Z0-9-]+)?\s*'
    r'\.JPG$'
)


def parse_filename(name: str) -> dict:
    """Return a {species, station, tag, original_filename} dict."""
    base = os.path.basename(name)

    # Moultrie's native naming → no hunter label
    if _MFDC_PAT.match(base):
        return {
            "species": None,
            "station": None,
            "tag": "moultrie-mfdc",
            "original_filename": base,
        }

    species = None
    m = _SPECIES_WORDS.search(base)
    if m:
        species = _SPECIES_MAP.get(m.group(1).lower())

    station = None
    s = _STATION_PAT.search(base)
    if s:
        candidate = s.group(1)
        # Don't collide with the species word itself if it ended up matching.
        if candidate.lower() not in _SPECIES_MAP:
            station = candidate

    return {
        "species": species,
        "station": station,
        "tag": "hand-labeled" if species else "untagged-other",
        "original_filename": base,
    }


def extract_dto(exif_blob: bytes) -> Optional[datetime]:
    """Pull DateTimeOriginal from the Exif blob."""
    try:
        import piexif
        ex = piexif.load(exif_blob)
        dto = ex.get("Exif", {}).get(piexif.ExifIFD.DateTimeOriginal)
        if not dto:
            return None
        return datetime.strptime(dto.decode("ascii"), "%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Selection strategy
# ---------------------------------------------------------------------------

SPECIES_CAPS = {
    "feral_hog":         14,   # all of them (only 14 in source)
    "white_tailed_deer": 25,
    "black_bear":        18,
    "coyote":            18,
    "elk":               15,   # all 15
    "turkey":            10,   # all 10
    "raccoon":           4,
    "bobcat":            1,
    "fox":               1,
    "squirrel":          1,
}
UNLABELED_CAP = 35   # MFDC#### Moultrie defaults, for empty-frame controls


def select_subset(entries: list[dict], *, seed: int = 42) -> list[dict]:
    """Return the subset to emit, capped by species (see SPECIES_CAPS)."""
    import random
    rng = random.Random(seed)

    by_species = defaultdict(list)
    unlabeled = []
    for e in entries:
        if e["species"]:
            by_species[e["species"]].append(e)
        elif e["tag"] == "moultrie-mfdc":
            unlabeled.append(e)

    kept: list[dict] = []

    # Deterministic shuffle + cap per species
    for sp_key, pool in sorted(by_species.items()):
        rng.shuffle(pool)
        cap = SPECIES_CAPS.get(sp_key, 10)
        kept.extend(pool[:cap])

    # Unlabeled (MFDC####) — random subset
    rng.shuffle(unlabeled)
    kept.extend(unlabeled[:UNLABELED_CAP])
    return kept


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(src_zip: Path, out_zip: Path, seed: int = 42) -> dict:
    print(f"→ Building TNDeer regression fixture")
    print(f"  src: {src_zip}")
    if not src_zip.exists():
        raise SystemExit(f"source ZIP not found: {src_zip}")

    all_entries: list[dict] = []
    bytes_cache: dict[str, tuple[bytes, bytes]] = {}

    with zipfile.ZipFile(src_zip) as zin:
        infos = [i for i in zin.infolist()
                 if i.filename.lower().endswith(".jpg")
                 and not i.is_dir()]
        print(f"  source contains {len(infos)} JPGs")
        for info in infos:
            parsed = parse_filename(info.filename)
            parsed["source_arcname"] = info.filename
            parsed["source_size"] = info.file_size
            all_entries.append(parsed)

    # Select the subset
    kept = select_subset(all_entries, seed=seed)
    print(f"  selected {len(kept)} photos")

    species_counts = defaultdict(int)
    station_counts = defaultdict(int)
    for e in kept:
        species_counts[e["species"] or "_unlabeled"] += 1
        if e["station"]:
            station_counts[e["station"]] += 1

    print()
    print("  species distribution:")
    for sp, n in sorted(species_counts.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {sp}")
    print("  station distribution (labeled subset):")
    for st, n in sorted(station_counts.items(), key=lambda x: -x[1]):
        print(f"    {n:>3}  {st}")

    # Copy the bytes out of the source ZIP and into the fixture ZIP
    # — preserve the originals verbatim so native EXIF stays intact.
    print()
    print(f"→ Writing {out_zip}")
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "source": str(src_zip),
        "total_source_photos": len(all_entries),
        "selected_photos": len(kept),
        "seed": seed,
        "species_cap_config": SPECIES_CAPS,
        "unlabeled_cap": UNLABELED_CAP,
        "notes": (
            "Photos are the unmodified bytes from a hunter's real "
            "five-year trail-cam archive (Cumberland Plateau, TN). "
            "Ground-truth species labels are extracted from the "
            "hunter's filename convention and are NOT guaranteed "
            "to be perfect — spot-check before reporting accuracy."
        ),
        "photos": [],
    }

    with zipfile.ZipFile(src_zip) as zin, \
         zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zout:
        for entry in kept:
            src_name = entry["source_arcname"]
            raw = zin.read(src_name)
            # Arrange into station subfolders (or _unlabeled/) so the
            # ingest layer's directory heuristics apply.
            station = entry["station"] or "_unlabeled"
            arc_basename = entry["original_filename"]
            arc = f"{station}/{arc_basename}"

            # Pull the timestamp for manifest bookkeeping
            try:
                im_exif = zipfile.ZipFile(io.BytesIO(raw)) if False else None
            except Exception:
                im_exif = None
            dto_iso = None
            try:
                from PIL import Image
                import piexif
                im = Image.open(io.BytesIO(raw))
                ex_blob = im.info.get("exif")
                if ex_blob:
                    dto = extract_dto(ex_blob)
                    if dto:
                        dto_iso = dto.isoformat()
            except Exception:
                pass

            zout.writestr(arc, raw)
            manifest["photos"].append({
                "arcname": arc,
                "source_arcname": src_name,
                "species_ground_truth": entry["species"],
                "station_code": entry["station"],
                "original_filename": arc_basename,
                "label_provenance": entry["tag"],
                "datetime_original": dto_iso,
                "size_bytes": len(raw),
            })
        zout.writestr("MANIFEST.json", json.dumps(manifest, indent=2))

    # Sibling manifest for easy inspection without extracting
    manifest_path = out_zip.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))

    size_mb = out_zip.stat().st_size / 1024 / 1024
    print(f"  {out_zip.name}: {size_mb:.1f} MB  ({len(kept)} photos)")
    print(f"  manifest: {manifest_path.name}")
    print()
    print("Ground-truth species distribution (final):")
    for sp, n in sorted(species_counts.items(), key=lambda x: -x[1]):
        print(f"  {n:>3}  {sp}")
    return manifest


def main():
    default_src = (Path.home() / "Downloads" /
                   "TNDeer Transfer Pics-20260419T180219Z-3-001.zip")
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=default_src,
                    help="source ZIP path (default: ~/Downloads/TNDeer…)")
    ap.add_argument("--out", type=Path,
                    default=REPO / "tests" / "fixtures" / "tndeer_sd_card.zip")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    build(src_zip=args.src, out_zip=args.out, seed=args.seed)


if __name__ == "__main__":
    main()
