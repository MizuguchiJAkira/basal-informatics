# tests/fixtures/

Test data bundles. Reproducible from source, **gitignored** (licensing
hygiene + repo size). Two bundles live here, with different purposes.

## Which bundle to use

| Bundle | Purpose | Realism |
|---|---|---|
| `tndeer_sd_card.zip` | First-class classifier regression fixture | Real hunter data |
| `sd_card.zip` | Pipeline-wiring smoke test | Synthetic from iNaturalist |

Prefer `tndeer_sd_card.zip` when you need actual trail-cam aesthetic
(IR, low-light, mistriggers, multi-camera EXIF quirks). Prefer
`sd_card.zip` when you just need valid JPEGs flowing end-to-end
without depending on a hunter-supplied source ZIP.

## tndeer_sd_card.zip — real hunter subset

~142 curated photos from a real five-year Cumberland Plateau (TN)
trail-cam archive. Spans 14 camera models across 7 manufacturers
(Moultrie, Muddy, Wildgame, Stealth Cam, GardePro, Cuddeback,
even an iPhone placement-snapshot). Every photo carries real native
EXIF — `Make`, `Model`, `DateTimeOriginal`, manufacturer-specific
maker-notes — so this fixture is the authoritative test of the
camera-brand-specific ingest paths.

Ground-truth species labels extracted from the hunter's filename
convention (`CF Pig 2025-05-19 Goldilocks MH.JPG` → species=`feral_hog`,
station=`MH`). Labels are hand-curated by the hunter and should be
treated as good-but-not-perfect — spot-check before reporting
classifier accuracy numbers.

Build it:

```sh
python scripts/build_tndeer_fixture.py \
    --src ~/Downloads/TNDeer\ Transfer\ Pics-20260419T180219Z-3-001.zip
```

Defaults to reading from `~/Downloads/TNDeer…`. Output goes to
`tests/fixtures/tndeer_sd_card.zip`. Deterministic with `--seed 42`.

### Source ZIP is private data

The source zip is **one hunter's property data**, not ours to
redistribute. Treat it like PII: don't commit it, don't post it,
don't share it. The derived fixture is also gitignored, even though
the hunter shared the dump for Basal testing — we're careful about
consent scope.

### Species distribution (default cap)

~25 white-tailed deer · 18 black bear · 18 coyote · 15 elk ·
14 feral hog · 10 turkey · 4 raccoon · 1 each of bobcat, fox,
squirrel · 35 Moultrie-default-named (MFDC####) as
empty-frame / "hunter hasn't curated yet" controls.

The species cap is configurable in `SPECIES_CAPS` at the top of
`scripts/build_tndeer_fixture.py`.

---

## sd_card.zip — synthetic trail-cam SD card

~120 photos of Sus scrofa, Odocoileus virginianus, and Canis latrans
drawn from iNaturalist research-grade observations in Texas, organised
into four synthetic camera stations with realistic EXIF timestamps and
placement-context metadata matching what the IPW layer expects.

Build it:

```sh
python scripts/build_test_sd.py
```

Downloads ~15 MB from iNaturalist's S3 bucket. Takes ~2 minutes with a
polite 0.2 s pause between photos.

### What it exercises

- ZIP extraction + EXIF timestamp parsing in the ingest layer
- MegaDetector + SpeciesNet on real animal bytes
- Independent-event grouping (60 s burst + 30 min window)
- Placement-context IPW correction (4 cameras × 4 contexts)
- `DetectionSummary` aggregation into the lender portal

### What it does NOT exercise

- Camera-manufacturer EXIF maker-notes (Reconyx, Stealth, Bushnell,
  Moultrie all write maker-notes differently — only a real SD card
  exposes those quirks)
- IR / low-light / mistriggered-on-tree-branch frames
- Empty-frame handling at hunter-deployment rates (every iNat photo
  is a confirmed positive; a real card is mostly empty frames)
- Regional hog subpopulations outside the Edwards Plateau range

For real pipeline validation, follow `docs/UPLOAD_LIVE_RUN.md`
against a real hunter's SD card.

### Attribution

Each photo is tagged in EXIF `Copyright` with its iNaturalist
observer + license code. The sibling `sd_card.manifest.json` records
source observation IDs, licenses, observers, species ground-truth,
and assigned camera/context for every image.

Photos are drawn from these CC-licensed variants:

- `cc0` (public domain)
- `cc-by`
- `cc-by-sa`
- `cc-by-nc`

Use of the bundle for internal testing + research is consistent with
these licenses; redistribution requires preserving the per-photo
attribution in the manifest.

### Why this isn't committed

Licensing: the manifest is the attribution record; redistributing the
ZIP without it would break the CC-BY chain, and even with it the
binary photos don't add to repo quality — we can rebuild from source.
Repo size: ~15 MB is tolerable but additive; rebuilding is ~2 min and
produces a byte-identical bundle when the `--seed` is fixed.
