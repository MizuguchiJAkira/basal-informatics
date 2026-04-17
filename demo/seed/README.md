# Demo seed scripts

Scripts that populate the database with compelling per-property data so the
dashboard has something to render during YC demo prep.

## `seed_dashboard.py`

Direct-SQL seeder for **Edwards Plateau Ranch** (2,340 acres, Kimble County, TX).
Creates:

- 1 property (id=1, renamed from whatever it was)
- 1 season (`Spring 2026`, 2026-02-01 – 2026-03-31)
- 3 cameras (N feeder, S feeder, creek crossing) with realistic lat/lon,
  placement contexts, and camera model metadata
- 10 DetectionSummary rows (4 species × 3 stations, minus absent combos)
  — 584 photos, 181 independent events total, matched to realistic
  activity windows (hogs nocturnal at feeders, deer crepuscular, coyotes
  late-night on trails)

**Idempotent:** re-running wipes prior data for the property and re-seeds.
FK-safe cleanup order: coverage_scores → share_cards → detection_summaries
→ processing_jobs → uploads → seasons → cameras.

### Usage

From inside the worker container (which has `DATABASE_URL` etc injected):
```bash
docker exec strecker-worker python3 /app/demo/seed/seed_dashboard.py
```

From a local dev shell:
```bash
# requires .env with DATABASE_URL set, or inline:
DATABASE_URL="postgresql://..." python3 demo/seed/seed_dashboard.py
```

### What this does NOT do

- Does not exercise the real ML pipeline (ingest, SpeciesNet, classify).
  The point is to have data ready for dashboard work; live ML is tested
  separately on the worker Droplet once it's been upsized to 4 GB RAM.
- Does not create Photo records — the photo gallery reads from a separate
  `demo/output/sorted/` filesystem tree. That's a known UX inconsistency
  (photo filenames don't match seeded camera labels); see
  `docs/DEMO_NARRATIVE.md` "What to NOT show" for handling.
- Does not create a User account. The property must already have an owner;
  the seed assumes id=1 → some existing user.

### Adjusting the numbers

Tune `CAMERAS[].species[].photos` and `events` to reshape the demo
narrative. The hourly-activity distributions live in the `hourly()`
helper calls; each tuple is `(start_hour, end_hour, weight)` — the
distribution is normalized when rendered, so weights are relative.

Changes flow through to the dashboard's Population Estimates section
automatically since REM runs against DetectionSummary inputs.
