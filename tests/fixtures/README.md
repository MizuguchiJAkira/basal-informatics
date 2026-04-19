# tests/fixtures/

Test data bundles. These are reproducible from public sources — **the
ZIP and manifest are gitignored**. Rebuild on demand.

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
