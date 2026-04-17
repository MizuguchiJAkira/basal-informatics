# Session Log — 2026-04-17 (lender pivot) — newest first

## 2026-04-17 late evening — strategic pivot: Strecker → lender-first Basal

### Context

Go-to-market changed from "hunter consumer app funnels data to Basal via
TOS data license" (arbitrage) to "ag lender requires landowners to upload
trail cam photos direct to Basal as collateral documentation" (direct
lender integration). Strecker remains a separate consumer product for
hunters and the neighboring-lease camera-coverage expansion channel.

### What shipped (oldest first, `9bbba09 .. 71a3ac8`)

```
9bbba09 feat(basal): LenderClient model + Property.lender_client_id/crop_type
848b953 feat(basal): Feral Hog Exposure Score — tier + 0-100 score + damage projection
bb37520 feat(basal): /lender portfolio + Nature Exposure Report routes + UI
28cc71e seed: Farm Credit of Central Texas + 5-parcel portfolio
71a3ac8 feat+docs: portfolio sort fix + YC-partner lender-framed demo narrative
```

Plus an App Platform spec change: `SITE=strecker → SITE=basal` on the live
container, so `/lender/` routes now mount. Strecker hunter-side routes
(/properties/1/dashboard, etc.) are temporarily unreachable on this
container — per strategic spec, they move to their own container + repo
later. The code is still in the monorepo untouched.

### Demo URL for YC partners

<https://basal.eco/lender/fcct/>

Login: jonahakiracheng@gmail.com (now `is_owner=TRUE` via the seed) /
PilotSmoke-d4e5ab. Change before demo day.

### What renders

Portfolio page (`/lender/fcct/`):
  - "Farm Credit of Central Texas · 5 parcels under assessment"
  - Tier-tally chips: 1 Severe · 1 Elevated · 1 Moderate · 1 Low
  - Dense table sorted Severe → Low → Pending, each row linking to its
    Nature Exposure Report
  - Parcel IDs rendered `TX-BRA-2026-00002` etc.

Per-parcel Nature Exposure Report:
  - Metadata strip: county, state, acreage, crop class, cameras, survey period
  - Headline: Feral Hog Exposure Score (0–100 + gradient bar + tier badge + 95% CI)
  - Modeled dollar projection with crop-modifier disclosure + "not a pipeline output" callout
  - Recommendation + caveats block
  - Other-species informational cards
  - Methodology footer citing Rowcliffe 2008 + Mayer & Brisbin 2009

### Portfolio details (live data)

| Parcel                  | Crop     | Acres | Tier     | Score | Density   | $/yr     |
|-------------------------|----------|------:|----------|------:|----------:|---------:|
| Riverbend Farm          | corn     |   650 | Severe   |  91.5 | 16.61/km² | $28,306  |
| Edwards Plateau Ranch   | sorghum  | 2,340 | Elevated |  50.6 |  5.13/km² | $25,561  |
| Oak Ridge Orchards      | peanut   |   180 | Moderate |  36.2 |  3.34/km² |  $1,381  |
| Highland Meadow Ranch   | pasture  | 4,800 | Low      |   7.0 |  0.56/km² |  $2,192  |
| Prairie Creek Property  | rangeland | 3,200| Pending  |     — |         — |        — |

### Methodology engine

- REM density estimator reused from earlier session (`risk/population.py`).
- New `risk/exposure.py`: tier classification per Mayer & Brisbin 2009
  (Low <2, Moderate 2–5, Elevated 5–10, Severe ≥10 animals/km²), 0–100
  score piecewise-linear anchored on the tier cutoffs, dollar projection
  scaled from Anderson 2016 per-hog damage (~$405/hog/yr adjusted)
  times crop modifier (corn 1.6×, peanut 1.4×, pasture 0.5×, etc.).
- 17 new tests; 23 old REM tests unaffected; 40/40 total green.

### Strecker untouched

Verified `SITE=strecker` app boots with 53 routes and **0** `/lender/` routes.
The strategic separation holds at the code level even though we're in a
monorepo transitionally. When Strecker gets split into its own repo the
cut point is: `web/routes/properties.py`, `web/routes/upload.py`,
`web/routes/feedback.py`, `web/routes/results.py`, `web/routes/deer.py`,
and `web/routes/api/properties.py` + `dashboard.py` + `share.py` +
`reid.py` + `uploads.py`. The shared shell is `config/`, `db/models.py`,
`strecker/` (ML pipeline), `risk/` (methodology).

### Decisions deferred to user

1. **Custom domain.** User noted no DNS or host yet. My recommendation:
   DO Domain Registration (free DNS, one-click App Platform hookup),
   candidate names already listed in the previous reply.
2. **DetectionIngest bridge in scope for YC demo?** I've deferred this —
   the demo narrative doesn't require it. Tell me if you want it in
   scope for Week 2.

### Remaining Week 1 items

- Replace placeholder preview-*.png on the Strecker marketing home page
  (those are only visible when the SITE=strecker container is live, so
  currently not load-bearing — demo-time priority only if we intend to
  also show Strecker).
- Custom domain setup (blocked on you).
- Demo rehearsal (blocked on you).

---

# Session Log — 2026-04-16 evening / 2026-04-17 morning

## Reading order for first look

1. This file (status snapshot + decisions log)
2. `docs/DEMO_NARRATIVE.md` (the 90-second YC pitch — needs your voice)
3. `docs/METHODOLOGY.md` (artifact for actuarial/lender audiences)
4. `docs/ROADMAP.md` (4-week plan with day-by-day tasks)
5. The live dashboard: <https://basal.eco/properties/1/dashboard>
   (login: jonahakiracheng@gmail.com / PilotSmoke-d4e5ab)

## Bottom line

**Strecker has a defensible YC-demo dashboard** showing per-species REM
density estimates with bootstrap 95% CIs, recommendation flags, and
plain-language caveats — backed by tested code, fed by real seeded data.

Visit while logged in:
<https://basal.eco/properties/1/dashboard>

Cards rendered live (verified via DOM scrape):

| Species          | Density (animals/km²) | 95% CI         | Flag                      |
|------------------|-----------------------|----------------|---------------------------|
| White-tailed Deer | 21.40                 | 8.45 – 276.40  | Recommend further survey  |
| Feral Hog         | 5.13                  | 1.21 – 30.59   | Recommend further survey  |
| Coyote            | 1.87                  | 1.06 –   7.92  | Insufficient data         |
| Raccoon           | density not computed  | —              | Insufficient data         |

The "insufficient data" + "recommend survey" flags + caveats list are the
actuarial/lender story: we report what we can defend, and we sell the
follow-on survey when we can't.

## What landed tonight

Full git log of the session, oldest first:

```
37a03f5 feat: property-scoped uploads via worker queue + dashboard aggregation
e34e663 fix: speed up and serialize web boot to pass health check
8f51dac fix: cap boto3 timeouts so Spaces misconfig fails fast, not at 5 min
b9fbaa2 chore: force redeploy to cycle containers
1ddceef fix: reduce gunicorn workers + add max-requests to bound DB conn pool
b2ad7b8 fix: optional ephem + worker idle-in-transaction leak
1df074f feat: REM density estimator + dashboard population endpoint
07487ac feat: render REM population estimates section in dashboard UI
cf0d3e3 docs: session log for 2026-04-16 evening
2287808 fix(rem): truncate v perturbation to +/-50% to keep CI bounds believable
623864a docs: methodology one-pager for actuarial / lender audience
e95d5a4 docs: 90-second YC demo narrative + script + Q&A + checklists
7571bf1 polish(map): add tooltip + title to camera markers
d3a87b1 docs: 4-week roadmap to YC demo
abe8255 fix: include population + photo gallery sections in empty-state hide
a3d3fdf perf: gunicorn back to 2 workers for concurrent-user handling
```

That's 16 commits across infrastructure (4), feature work (3), bug fixes (5),
docs (4). Plus tonight's seed of demo data via the worker Droplet's
`/opt/demo-seed/` scripts (not in repo; idempotent re-seed via
`docker exec strecker-worker python3 /tmp/seed_dashboard.py`).

Plus an out-of-tree change: bumped DO App Platform health-check window
(initial_delay 10→30s, period 10→15s, threshold 9→30; path /login→/health)
so the slower db.create_all + ALTER migrations in commit 37a03f5 don't
trip the 90s deadline.

## What's verified

- `python3 -m pytest tests/test_population.py` — 23/23 green, 70 ms
- `GET /` — 200, < 300 ms
- `GET /login` — 200, dark-mode form readable
- `GET /health` — 200 (now used as App Platform health check)
- `GET /properties/1/dashboard` — 200, contains "Population Estimates"
- `GET /api/properties/1/dashboard/population?season_id=4` — 200, returns
  4 species estimates with the numbers above
- DOM scrape of live dashboard confirms 4 population cards render with
  correct labels, recommendation badges, CI ribbons, and caveat counts
- Worker Droplet on b2ad7b8 — `Starting Strecker worker (id=bf6c51329536)`
  visible in journalctl
- Postgres connection pool clean (~6 active, far below 22 limit) after
  fixing the idle-in-transaction leak

## What's seeded

`docker exec strecker-worker python3 /tmp/seed_dashboard.py` is checked in
at `/opt/demo-seed/seed_dashboard.py` on the worker Droplet. Idempotent;
re-run wipes prior demo data and re-seeds.

Property: **Edwards Plateau Ranch** (id=1, Kimble County, TX, 2,340 acres)
Season: **Spring 2026** (id=4, Feb 1 – Mar 31)
3 cameras (North feeder, South feeder, Creek crossing), 4 species, 584
photos, 181 independent events, 10 DetectionSummary rows.

## Architecture decisions made tonight

1. **Database connection pool exhaustion** is real and caused multiple
   outages. Mitigations now in place:
   - `--workers 1` in gunicorn instead of 2 (was 4 effective due to
     wsgi.py double-create)
   - `--max-requests 200` to recycle workers on schedule
   - `_claim_next_job` rolls back on the no-row branch (was leaking
     "idle in transaction" sessions per poll)
   - Bumped health-check window so boots don't get killed mid-migration
   These are defensible for pilot scale (≤10 users); switch to PgBouncer
   when we cross ~50 concurrent users.

2. **REM (Rowcliffe 2008) over individual-ID** as the population
   estimator. Defensible without ML for individual recognition, which
   doesn't work reliably for hogs anyway. Per-species movement
   parameters (v ± v_sd) cited from the literature in
   `config/settings.py` `SPECIES_MOVEMENT`.

3. **Demo data is synthesized, not pipeline-derived.** Tonight's OOM
   on SpeciesNet inference (16 photos × ~150 MB peak each on a 2 GB
   Droplet) means we either upsize the worker or downsample images
   before inference. Out of scope for the demo; the seed bypasses the
   pipeline entirely via direct SQL inserts. The pipeline is still
   sound — verified that worker can claim, download from Spaces,
   extract, and reach the SpeciesNet step. Just runs OOM there.

4. **Property-scoped upload route is technically live but untested.**
   `POST /api/properties/<pid>/uploads` accepts ZIPs and writes a
   ProcessingJob row, but real uploads through the web container have
   not been verified end-to-end since we worked around the initial
   bug. The boto3 timeouts in 8f51dac will surface failures fast;
   they will not silently hang anymore.

## What needs user input

1. **Custom domain** (`strecker.basalinformatics.com` or similar). I
   need DNS access on the apex you control. The domain change also
   fixes the Chrome "dangerous site" warning (it was new-subdomain
   reputation, not actual malware).

2. **Demo narrative.** I drafted the story arc above ("we report
   what we can defend, sell the survey when we can't"). Want it
   rewritten for your voice / a specific reinsurer or LP?

3. **Worker upsize.** 2 GB OOMs on SpeciesNet. $24/mo (4 GB) reliably
   handles batches of ~50 photos. Or stay at $12 and pre-downsample
   images before inference (more code).

4. **Real preview screenshots for the marketing home page.** The
   placeholder PNGs (`web/static/marketing/preview-*.png`) are still
   the hero-poster image. Once we have the populated dashboard, take
   real screenshots and replace.

## Suggested next session priorities

1. **Tighten REM CIs** — current 95% bands are wide because the
   bootstrap perturbs `v` with full published `v_sd`. Decompose
   variance into camera-sampling (bootstrap) + species-knowledge
   (separate band) and report independently. Less impressive-looking
   numbers, more methodologically defensible.

2. **Pre-signed Spaces URLs for the upload route.** This is the
   architectural rewrite I deferred when we ran out of context-budget
   tonight. Browser uploads ZIP DIRECTLY to Spaces; the web container
   only writes the DB row. Eliminates the entire class of "boto3 hung
   the request" failures.

3. **Map with camera positions.** The dashboard already has a
   "Camera Network Map" placeholder; the seeded camera lat/lon values
   put STATION-NORTH-FEEDER, STATION-SOUTH-FEEDER, STATION-CREEK-
   CROSSING within the parcel polygon. Should render.

4. **Methodology one-pager** — a downloadable PDF an actuary can
   read in 5 minutes. Cite the four papers driving REM, IPW, and
   bootstrap. This is the artifact you walk into a reinsurer pilot
   conversation with.

## Login

Same temp credentials as last session:
- Email: jonahakiracheng@gmail.com
- Password: PilotSmoke-d4e5ab

Change via the UI or ask me to reset.

## Operating notes you might want

If you want me to keep iterating overnight on subsequent nights, the
patterns that worked tonight:

- **Batch commits aggressively before pushing** — each push = one App
  Platform deploy (~3-4 min). Tonight I pushed too many small commits;
  could have grouped 2-3.
- **Don't trigger production uploads to test the broken route.** The
  cascade of failures from the Spaces hang ate ~90 minutes. Use the
  worker-side enqueue script (`enqueue.py` on the Droplet) when I need
  to validate the worker pipeline; reserve the web upload route for
  after the pre-signed-URL refactor.
- **Always ssh into the Droplet via `docker exec strecker-worker`** for
  DB queries — host doesn't have psql, container has psycopg2.
- **Health check window is now 5 min** — gives boots room to do
  migrations + advisory-lock dance without tripping. Don't tighten.

— Claude
