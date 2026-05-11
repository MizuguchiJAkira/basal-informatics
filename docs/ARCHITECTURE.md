# Architecture — orientation for new readers

A 1-page guide to how the parts connect. Pair this with the README
(top-level overview + pipeline diagram) and METHODOLOGY.md (the
science). This file points at the actual code.

## Mental model

The codebase has three concerns layered on one Flask process:

```
┌──────────────────────────────────────────────────────────────────┐
│ Web   — Flask routes + Jinja templates                           │
│        (basal.eco lender / strecker.app hunter, host-routed)     │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Domain — pure-ish Python modules per concern                     │
│   bias/        IPW placement-bias correction                     │
│   risk/        density estimation, tier classification           │
│   habitat/     per-parcel habitat scoring (v2)                   │
│   valuation/   Stage 7 — Texas ag valuation risk                 │
│   report/      PDF + HTML report generation                      │
│   strecker/    ML pipeline driver (worker-side)                  │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│ Storage — Postgres (PostGIS) + DO Spaces + local fallback        │
└──────────────────────────────────────────────────────────────────┘
```

The web layer doesn't do math; the domain layer doesn't talk HTTP.
A request handler in `web/routes/lender.py` reads the database,
calls into a domain module, and renders the result.

## How a parcel report request flows

`GET /lender/<lender_slug>/parcel/<id>` is the most-trafficked path
in the codebase. Every Stage 1–7 component touches it. Tracing it
from request to response:

```
                              web/routes/lender.py:parcel_report()
                              ─┬───────────────────────────────────
                               │ 1. Look up Property + Season
                               │    ─→ db/models.py
                               │ 2. Compute hog exposure
                               │    ─→ risk/exposure.py
                               │       risk/population.py (REM)
                               │       bias/placement_ipw.py (IPW)
                               │ 3. Compute Stage 7 valuation
                               │    ─→ valuation/compute.py
                               │       └─ valuation/adapters/cad/
                               │       └─ valuation/scoring.py
                               │       └─ valuation/exposure.py
                               │       └─ valuation/remediation.py
                               │       └─ valuation/reference/*.yaml
                               │ 4. Compute coverage + neighbors
                               │    ─→ risk/proximity.py
                               │ 5. Render
                               │    ─→ web/templates/lender/
                               │       parcel_report.html (Jinja)
                               ▼
                              200 OK   text/html
```

Every stage's output is a plain dict; nothing crosses module
boundaries as a SQLAlchemy object except where the route layer
does the read. This keeps the domain modules independently
unit-testable — see `tests/test_valuation_*.py` and
`tests/test_population.py`.

## Where to look for "how does X work?"

| Question | File |
|---|---|
| Pipeline orchestration / Flask factory | `web/app.py` |
| Lender-side routes (portfolio, parcel report, override API) | `web/routes/lender/` package — see breakdown below |
| Hunter-side routes (Strecker upload, dashboard) | `web/routes/upload.py`, `web/routes/results.py` |
| Database schema | `db/models.py` |
| Migrations (forward + paired `.down.sql`) | `db/migrations/NNNN_*.sql` |
| Worker (MegaDetector + SpeciesNet) | `strecker/worker.py`, `strecker/detect.py`, `strecker/classify.py` |
| Density estimation (REM) | `risk/population.py` |
| Bias correction (IPW) | `bias/placement_ipw.py` |
| Stage 7 risk scoring (rubric + drivers) | `valuation/scoring.py` |
| Stage 7 exposure (collateral + §23.55) | `valuation/exposure.py` |
| Stage 7 remediation (TPWD 3-of-7) | `valuation/remediation.py` |
| Stage 7 reference data (YAML, hand-curated) | `valuation/reference/*.yaml` |
| CAD adapters (per-county snapshots, PTAD cache) | `valuation/adapters/cad/*.py` |
| HTML parcel report (the big one) | `web/templates/lender/parcel_report.html` |
| PDF parcel report | `report/generator.py` + `report/sections/*.py` |
| Methodology one-pager (rendered at `/methodology`) | `docs/METHODOLOGY.md` |
| Pre-public-flip checklist | `NOTICE.md` |

## Data flow at a glance

```
SD card ZIP
    │
    │  uploaded by hunter (Strecker) or pulled by token (Basal lender)
    ▼
DO Spaces ── object store, presigned PUT
    │
    ▼
processing_jobs row  ── status: queued
    │
    │  worker droplet polls (FOR UPDATE SKIP LOCKED)
    ▼
strecker/worker.py
    │
    ├─→ strecker/detect.py     ── MegaDetector v5 (animal bbox + conf)
    │
    ├─→ strecker/classify.py   ── SpeciesNet v4 (geofenced, calibrated)
    │
    ├─→ strecker/ingest.py     ── independence filter (30-min)
    │
    └─→ db.write photos / detection_summaries
                │
                ▼
          parcel report read path (above) ← lender or hunter
```

The worker is process-isolated from the web app; they only share the
Postgres queue and the Spaces bucket. A worker crash never takes
down a user request.

## Site routing — one Flask process, two brands

`web/app.py:active_site()` resolves the active brand from the
request `Host` header:

| Host pattern | Brand | URL space |
|---|---|---|
| `basal.eco`, `*.basal.eco`, `basalinformatics.com` | basal | `/lender/...`, `/owner/...`, `/methodology` |
| `strecker.*`, `*.strecker.*` | strecker | `/properties/...`, `/upload/...`, `/dashboard/...` |
| `localhost`, `*.ondigitalocean.app` | falls back to `SITE` env | both |

Routes register at boot for both brands; a route on the "wrong"
brand simply isn't reachable because the host doesn't resolve to it.
Templates branch on `active_site` only when copy needs to differ
(error pages, the `/` landing route).

## Feature flags

| Env var | Default (demo) | Default (prod) | Effect |
|---|---|---|---|
| `DEMO_MODE` | True | False | Auto-login the demo user; seed Edwards Plateau parcel + cameras + detection summaries |
| `FEATURE_VALUATION_RISK` | True (when demo) | False | Enable Stage 7 section in HTML + PDF parcel report |
| `SITE` | `strecker` | (per-deployment) | Default brand when host resolution falls through |

A pilot lender that hasn't approved Stage 7 yet should run with
`FEATURE_VALUATION_RISK=False` — the section disappears from both
report layers, no code change needed.

## Test layout

| Concern | File |
|---|---|
| Schema + migrations | `tests/test_migrations.py` |
| REM density math | `tests/test_population.py` |
| IPW bias correction | `tests/test_placement_ipw.py` |
| Tier classifier | `tests/test_exposure.py` |
| Worker + classify pipeline | `tests/test_strecker.py`, `tests/test_classify_and_score.py` |
| Lender route end-to-end (HTML render parity) | `tests/test_lender_route.py` |
| Stage 7 scoring rubric | `tests/test_valuation_scoring.py` |
| Stage 7 exposure math | `tests/test_valuation_exposure.py` |
| Stage 7 remediation 3-of-7 | `tests/test_valuation_remediation.py` |
| Stage 7 orchestrator + persistence | `tests/test_valuation_compute.py` |
| Stage 7 override API + audit log | `tests/test_valuation_api.py` |
| Stage 7 PTAD cache adapter | `tests/test_valuation_ptad.py` |
| Edge cases (empty ZIPs, bad EXIF, unicode, concurrent claims) | `tests/test_adversarial.py` |

Run individually with `pytest tests/test_valuation_scoring.py` etc.;
full suite is `pytest tests/`. Currently **500 passing**.

## `web/routes/lender/` package layout

Split from a 1,210-line monolith in 2026-05. Five files, each a
single concern:

| File | Lines | Holds |
|---|---|---|
| `__init__.py` | 56 | Package docstring + back-compat re-exports of the public surface (`lender_bp`, `parcel_valuation_override`, `_hog_history`, `_override_rate_*`). Triggers route registration by importing the route modules at the bottom. |
| `blueprint.py` | 19 | Just the `Blueprint()` constructor. Lives in its own leaf module so route modules can import it without going through `__init__` (avoids circular imports). |
| `helpers.py` | 572 | The `lender_access_required` decorator, density+exposure compute helpers (`_compute_parcel_exposures`, `_neighboring_coverage`, `_hog_history`, `_hog_hourly_activity`), and report-shape helpers (`_aggregate_accuracy_reports`, `_confidence_grade`, `_build_exec_summary`). |
| `portfolio.py` | 109 | `GET /` and `GET /<lender_slug>/`. |
| `parcel_report.py` | 290 | `GET /<lender_slug>/parcel/<id>` and `GET /<lender_slug>/parcel/<id>/upload`. |
| `api.py` | 394 | `GET /api/<slug>/parcel/<id>/exposure`, `POST /api/<slug>/parcel/<id>/valuation/override`, plus the in-process override rate-limiter. |

Old import paths (`from web.routes.lender import lender_bp`) still
work — the package `__init__` re-exports the public surface.

## Where the code is rough

Read these with patience:

- **`web/templates/lender/parcel_report.html`** — 1,000+ lines of
  inline-styled Jinja. The visual weight of the report renders from
  this single file. Worth viewing the rendered output (screenshots
  in this directory) before reading the markup. Splitting into
  template includes is the next refactor on this surface.
- **Bobcat photo modifications cleared (2026-05-10).** Earlier
  versions of this file warned about 322 uncommitted demo photo
  modifications; those were reverted to the tracked state via
  `git checkout HEAD -- demo/output/sorted/`. The synthetic-photo
  render path in `web/app.py:serve_photo` covers them at request
  time. See `NOTICE.md`.

## What's next (engineering)

Tracked in `docs/ROADMAP.md` and `docs/PROD_MIGRATION_QUEUE.md`.
The two highest-priority engineering items not yet shipped:

1. Real CAD data ingestion through the productionized PTAD
   adapter (live network fetch, currently `--simulate` default).
2. Lender-route file split mentioned above.

Non-engineering blockers (legal review, reference-data audit,
TNDeer photo replacement) are tracked in `NOTICE.md`.
