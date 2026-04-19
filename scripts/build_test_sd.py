#!/usr/bin/env python3
"""Build a synthetic test SD-card ZIP for Basal's upload pipeline.

Pulls research-grade, CC-licensed wildlife photos from iNaturalist
(Sus scrofa, Odocoileus virginianus, Canis latrans — all in Texas),
rewrites EXIF ``DateTimeOriginal`` to simulate a 60-day deployment
across four synthetic cameras with realistic diurnal patterns, and
zips the result.

The output ZIP is the closest thing we can assemble from public data
to a hunter's trail-cam SD card — not the perfect substitute, but
enough to drive the classifier, event-independence, and aggregation
layers in a reproducible way.

What this exercises
-------------------
  - EXIF timestamp parsing in the ingest layer
  - MegaDetector + SpeciesNet on real animal bytes
  - Independent-event grouping (60s burst + 30min window)
  - Placement-context-aware IPW correction (4 cameras, 4 contexts)
  - ``DetectionSummary`` aggregation into the lender portal

What this does NOT exercise
---------------------------
  - Camera-manufacturer EXIF maker-notes (Reconyx, Stealth, Bushnell
    each write differently — only a real SD card exposes those quirks)
  - IR / low-light / mistriggered frames (iNat photos are
    good-light field photography, not trigger-based)
  - Empty-frame handling at hunter-deployment rates (iNat only
    surfaces confirmed observations, so every photo is a positive)

For a first live validation run, follow docs/UPLOAD_LIVE_RUN.md
against a real SD card from a cooperating hunter.

Usage
-----
    python scripts/build_test_sd.py
    python scripts/build_test_sd.py --out path/to/sd_card.zip
    python scripts/build_test_sd.py --per-species 50 --days 60

Defaults assemble ~120 photos into ``tests/fixtures/sd_card.zip``.

Attribution
-----------
Each photo is tagged in EXIF ``Copyright`` with its iNaturalist
observer + license. A manifest JSON beside the ZIP records source IDs
so attribution is preserved if this bundle is shared.
"""

import argparse
import io
import json
import random
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ---------------------------------------------------------------------------
# Species / camera / deployment plan
# ---------------------------------------------------------------------------

INAT_TAXA = {
    "feral_hog":          42134,
    "white_tailed_deer":  42223,
    "coyote":             42051,
}
INAT_PLACE_TEXAS = 18

# Four synthetic cameras matching the placement_context values the
# IPW layer expects. The camera folder names mirror real SD-card
# structure (DCIM/1xx<STATION>/) so the ingest layer parses them
# correctly.
CAMERAS = [
    {"station": "CAM-01", "context": "random",    "lat": 30.63, "lon": -99.52},
    {"station": "CAM-02", "context": "feeder",    "lat": 30.61, "lon": -99.49},
    {"station": "CAM-03", "context": "trail",     "lat": 30.59, "lon": -99.51},
    {"station": "CAM-04", "context": "water",     "lat": 30.64, "lon": -99.46},
]

# Diurnal activity curve per species — hour-of-day weights. Hogs
# peak at night, deer crepuscular (dawn/dusk), coyote mixed-nocturnal.
_ACTIVITY_HOURS = {
    "feral_hog":         [3, 3, 4, 4, 3, 2, 1, 1, 1, 1, 1, 1,
                          1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 5, 4],
    "white_tailed_deer": [1, 1, 1, 1, 2, 4, 6, 5, 3, 2, 1, 1,
                          1, 1, 1, 2, 3, 4, 6, 5, 3, 2, 1, 1],
    "coyote":            [3, 3, 3, 2, 2, 3, 3, 2, 1, 1, 1, 1,
                          1, 1, 1, 1, 1, 2, 3, 4, 4, 4, 3, 3],
}
_DEFAULT_ACTIVITY = [1] * 24


# ---------------------------------------------------------------------------
# iNaturalist client (stdlib only, polite rate-limiting)
# ---------------------------------------------------------------------------

_INAT_USER_AGENT = "basal-informatics-test-sd-builder/1.0 (+https://basal.eco)"
_INAT_API = "https://api.inaturalist.org/v1"


def _inat_get(path: str, params: dict) -> dict:
    qs = urlencode(params, doseq=True)
    req = Request(f"{_INAT_API}{path}?{qs}",
                  headers={"User-Agent": _INAT_USER_AGENT})
    with urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _http_get_bytes(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": _INAT_USER_AGENT})
    with urlopen(req, timeout=30) as r:
        return r.read()


def _search_observations(taxon_id: int, place_id: int,
                          n: int) -> list[dict]:
    """Return up to ``n`` research-grade observations with photos."""
    out, page, per_page = [], 1, min(n, 200)
    while len(out) < n and page <= 10:
        data = _inat_get("/observations", {
            "taxon_id": taxon_id,
            "place_id": place_id,
            "quality_grade": "research",
            "photo_license": "cc0,cc-by,cc-by-sa,cc-by-nc",
            "has[]": "photos",
            "per_page": per_page,
            "page": page,
            "order_by": "random",
        })
        results = data.get("results", [])
        if not results:
            break
        out.extend(results)
        if len(results) < per_page:
            break
        page += 1
        time.sleep(0.5)  # polite pause
    return out[:n]


def _pick_photo_url(observation: dict) -> tuple[str, str] | None:
    """Return (url, license_code) for the first licensed photo, or None."""
    for p in observation.get("photos", []):
        url = p.get("url")
        lic = p.get("license_code")
        if not url or not lic:
            continue
        # Swap the iNat ``square.jpg`` variant for a larger one.
        # https://inaturalist-open-data.s3.amazonaws.com/photos/<id>/square.jpg
        for variant in ("large.jpg", "medium.jpg", "original.jpg",
                        "square.jpg"):
            candidate = url.replace("square.jpg", variant)
            if candidate != url or variant == "square.jpg":
                return candidate, lic
    return None


# ---------------------------------------------------------------------------
# EXIF injection
# ---------------------------------------------------------------------------

def _inject_exif(jpeg_bytes: bytes, *,
                  when: datetime,
                  camera_station: str,
                  copyright_text: str,
                  lat: float, lon: float) -> bytes:
    """Rewrite the JPEG's EXIF so DateTimeOriginal + GPS + maker fields
    look like a camera-trap trigger.
    """
    import piexif
    from PIL import Image

    im = Image.open(io.BytesIO(jpeg_bytes))
    # Normalise to RGB JPEG — iNat can serve PNG/HEIF-sourced photos.
    if im.mode != "RGB":
        im = im.convert("RGB")

    stamp = when.strftime("%Y:%m:%d %H:%M:%S")
    exif = {
        "0th": {
            piexif.ImageIFD.Make: b"Basal-Test-Fixture",
            piexif.ImageIFD.Model: camera_station.encode("ascii"),
            piexif.ImageIFD.Copyright: copyright_text.encode("utf-8"),
            piexif.ImageIFD.DateTime: stamp.encode("ascii"),
            piexif.ImageIFD.Software: b"basal build_test_sd.py",
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: stamp.encode("ascii"),
            piexif.ExifIFD.DateTimeDigitized: stamp.encode("ascii"),
        },
        "GPS": _gps_ifd(lat, lon),
        "1st": {}, "thumbnail": None,
    }
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88,
            exif=piexif.dump(exif))
    return buf.getvalue()


def _gps_ifd(lat: float, lon: float) -> dict:
    """Build a minimal GPS-IFD dict for piexif."""
    import piexif

    def _dms(deg: float) -> list[tuple[int, int]]:
        deg = abs(deg)
        d = int(deg)
        m_full = (deg - d) * 60
        m = int(m_full)
        s = round((m_full - m) * 60 * 10000)
        return [(d, 1), (m, 1), (s, 10000)]

    return {
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _dms(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _dms(lon),
    }


# ---------------------------------------------------------------------------
# Timestamp distribution
# ---------------------------------------------------------------------------

def _sample_timestamps(n: int, *, species_key: str,
                        start: datetime, end: datetime,
                        rng: random.Random) -> list[datetime]:
    """Sample ``n`` timestamps in [start, end] weighted by the species'
    diurnal activity curve.
    """
    hours_w = _ACTIVITY_HOURS.get(species_key, _DEFAULT_ACTIVITY)
    total_days = max(1, (end - start).days)
    out = []
    for _ in range(n):
        day = rng.randrange(0, total_days)
        hour = rng.choices(range(24), weights=hours_w, k=1)[0]
        minute = rng.randrange(0, 60)
        second = rng.randrange(0, 60)
        out.append(start + timedelta(days=day, hours=hour,
                                     minutes=minute, seconds=second))
    return sorted(out)


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------

def build(out_path: Path, per_species: int, days: int, seed: int) -> dict:
    rng = random.Random(seed)
    end = datetime(2026, 4, 1, 0, 0, 0)   # deployment ends 1 Apr 2026
    start = end - timedelta(days=days)

    # Deterministic camera-context assignment per species: hogs cluster
    # around feeders + water, deer around feeders + trails, coyotes
    # random + trail.
    species_camera_weights = {
        "feral_hog":         {"CAM-01": 0.5, "CAM-02": 2.5, "CAM-03": 1.0, "CAM-04": 2.0},
        "white_tailed_deer": {"CAM-01": 1.0, "CAM-02": 2.0, "CAM-03": 2.0, "CAM-04": 0.8},
        "coyote":            {"CAM-01": 1.5, "CAM-02": 0.3, "CAM-03": 1.2, "CAM-04": 0.8},
    }
    cameras_by_station = {c["station"]: c for c in CAMERAS}

    print(f"→ Building test SD bundle  ({per_species} photos × "
          f"{len(INAT_TAXA)} species, {days}d window, seed={seed})")
    print(f"  window: {start.date()} → {end.date()}")

    manifest = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "seed": seed,
        "attribution": (
            "Photos courtesy of iNaturalist observers. Each entry's "
            "license_code and observer are recorded below and in the "
            "EXIF Copyright field of the corresponding JPEG."
        ),
        "photos": [],
    }

    zip_staging = []  # (arcname, bytes) tuples

    for species_key, taxon_id in INAT_TAXA.items():
        print(f"\n[{species_key}]  taxon={taxon_id}")
        # Pull a bit more than we need so we can drop unusable entries.
        n_fetch = int(per_species * 1.3) + 5
        observations = _search_observations(
            taxon_id=taxon_id, place_id=INAT_PLACE_TEXAS, n=n_fetch)
        print(f"  iNat returned {len(observations)} observations")

        # Sample timestamps before we know exact count so sorting is
        # meaningful per camera.
        chosen = []
        for obs in observations:
            pick = _pick_photo_url(obs)
            if not pick:
                continue
            photo_url, license_code = pick
            observer = (obs.get("user") or {}).get("login") or "unknown"
            chosen.append({
                "obs_id": obs.get("id"), "photo_url": photo_url,
                "license_code": license_code, "observer": observer,
            })
            if len(chosen) >= per_species:
                break
        print(f"  picked {len(chosen)} photos")

        # Weighted camera assignment for this species
        stations = list(species_camera_weights[species_key].keys())
        station_w = [species_camera_weights[species_key][s] for s in stations]

        timestamps = _sample_timestamps(
            len(chosen), species_key=species_key,
            start=start, end=end, rng=rng)

        for idx, (photo, ts) in enumerate(zip(chosen, timestamps)):
            station = rng.choices(stations, weights=station_w, k=1)[0]
            cam = cameras_by_station[station]
            try:
                raw = _http_get_bytes(photo["photo_url"])
            except Exception as e:
                print(f"    skip {photo['photo_url']}: {e}")
                continue

            attribution = (
                f"(c) {photo['observer']} / iNaturalist obs "
                f"{photo['obs_id']} / {photo['license_code']}"
            )
            try:
                jpeg = _inject_exif(
                    raw, when=ts,
                    camera_station=station,
                    copyright_text=attribution,
                    lat=cam["lat"], lon=cam["lon"])
            except Exception as e:
                print(f"    EXIF inject failed for {photo['obs_id']}: {e}")
                continue

            # DCIM-ish structure: /<station>/IMG_<NNNN>.JPG
            arcname = (
                f"{station}/IMG_{ts.strftime('%Y%m%d_%H%M%S')}"
                f"_{photo['obs_id']}.JPG"
            )
            zip_staging.append((arcname, jpeg))
            manifest["photos"].append({
                "arcname": arcname,
                "species_ground_truth": species_key,
                "taxon_id": taxon_id,
                "observed_at": ts.isoformat(),
                "camera_station": station,
                "placement_context": cam["context"],
                "lat": cam["lat"], "lon": cam["lon"],
                "inat_obs_id": photo["obs_id"],
                "inat_photo_url": photo["photo_url"],
                "license_code": photo["license_code"],
                "observer": photo["observer"],
                "size_bytes": len(jpeg),
            })
            if (idx + 1) % 10 == 0:
                print(f"    {idx + 1}/{len(chosen)} photos captured")
            time.sleep(0.2)   # be polite to the S3 bucket

    # Write the ZIP
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arcname, payload in zip_staging:
            z.writestr(arcname, payload)
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))

    total_bytes = sum(len(b) for _, b in zip_staging)
    print()
    print(f"✓ wrote {out_path}")
    print(f"  {len(zip_staging)} photos, {total_bytes // 1024} KB raw, "
          f"{out_path.stat().st_size // 1024} KB compressed")
    print(f"  manifest: {len(manifest['photos'])} entries")

    # Also drop the manifest next to the ZIP for easy inspection
    manifest_path = out_path.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  manifest: {manifest_path}")

    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=REPO / "tests" / "fixtures" / "sd_card.zip")
    ap.add_argument("--per-species", type=int, default=40,
                    help="photos per species (default 40)")
    ap.add_argument("--days", type=int, default=60,
                    help="deployment window length (default 60)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    build(out_path=args.out, per_species=args.per_species,
          days=args.days, seed=args.seed)


if __name__ == "__main__":
    main()
