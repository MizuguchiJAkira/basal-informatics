# Basal Informatics

**Primary-source, parcel-level species density estimates with
methodology-backed confidence intervals — for lenders, reinsurers, and
TNFD / EU CSRD nature-risk disclosure.**

We ingest a landowner's trail-camera SD card, run two sequential
detection/classification models, temperature-scale the classifier output,
apply literature-prior bias corrections and a Random Encounter Model
density estimator, bootstrap a 95% CI, and publish a Nature Exposure
Report where every number traces back to a specific photo.

**Live:**
- [basal.eco](https://basal.eco) — editorial landing + sample report +
  live Farm Credit pilot portal at `/lender/fcct/`
- [strecker.app](https://strecker.app) — consumer-side data-acquisition
  tool (see [*The Strecker arm*](#the-strecker-arm) below)

---

## What the pipeline does

```
  SD card (ZIP)  →  Spaces (object storage)  →  worker Droplet
                                                     │
                                                     ▼
  ┌─────────────┐   ┌──────────────┐   ┌─────────────────────────┐
  │ MegaDetector│   │  SpeciesNet  │   │   Calibration layer     │
  │     v5      │──▶│   v4.0.2     │──▶│ • temperature scaling   │
  │ (bbox, MD   │   │  (geofenced  │   │ • cyclical temporal     │
  │  confidence)│   │   to state)  │   │   prior                 │
  └─────────────┘   └──────────────┘   └────────────┬────────────┘
                                                    │
                                                    ▼
  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────────┐
  │  Entropy    │   │  Independent │   │  REM density + IPW       │
  │  review     │◀──│  event       │──▶│  bias correction         │
  │  routing    │   │  collapse    │   │                          │
  └─────────────┘   └──────────────┘   └────────────┬─────────────┘
                                                    │
                                                    ▼
                                     ┌──────────────────────────────┐
                                     │ 1,000-iteration bootstrap CI │
                                     │ (camera-level resample +     │
                                     │  movement-parameter          │
                                     │  perturbation)               │
                                     └──────────────┬───────────────┘
                                                    │
                                                    ▼
                                     ┌──────────────────────────────┐
                                     │ Tier classification          │
                                     │ (Low / Moderate / Elevated / │
                                     │  Severe)                     │
                                     └──────────────┬───────────────┘
                                                    │
                                                    ▼
                                     ┌──────────────────────────────┐
                                     │  Nature Exposure Report      │
                                     │  PDF  +  HTML  +  JSON API   │
                                     │  (every number cross-refed   │
                                     │   to source photo + EXIF +   │
                                     │   classifier confidence)     │
                                     └──────────────────────────────┘
```

Specific model versions, threshold values, per-species movement
parameters, and calibration details are documented in the public
methodology page:
[basal.eco/methodology](https://basal.eco/methodology).

### Citations

The pipeline implements, not invents. Each stage cites published work:

| Stage | Reference |
|---|---|
| Detection | **MegaDetector v5** — Beery et al., Microsoft AI for Earth. |
| Classification | **SpeciesNet v4.0.2** — Gadot et al., Google Research. |
| Confidence calibration | **Temperature scaling** — Dussert et al., 2025. |
| Temporal priors | **Cyclical time-of-day encoding** — Mac Aodha et al., *ICCV* 2019. |
| Review routing | **Softmax entropy for uncertainty** — Norouzzadeh et al., 2021. |
| Density estimator | **Random Encounter Model** — Rowcliffe, Field, Turvey & Carbone, *J. Appl. Ecol.*, 2008. |
| Placement-bias correction | **Inverse-propensity weighting on camera-placement priors** — Kolowski & Forrester, *PLOS ONE*, 2017. |
| Movement parameters | Kay et al. 2017 (feral swine); Webb et al. 2010 (white-tailed deer); Andelt 1985 (coyote). |
| Tier thresholds | **Mayer & Brisbin**, 2009 (feral hog density bins — v1). |

---

## Architecture

```
                           ┌─────────────────────┐
                           │  DO App Platform    │
  basal.eco ──────────────▶│   (Flask, multi-   │
  strecker.app ───────────▶│    site by Host)    │
  *.ondigitalocean.app ───▶│   $12/mo           │
                           └──────────┬──────────┘
                                      │
       ┌──────────────────────────────┼──────────────────────────┐
       │                              │                          │
       ▼                              ▼                          ▼
 ┌───────────┐              ┌──────────────┐            ┌────────────┐
 │  Managed  │              │  DO Spaces   │            │  Postmark  │
 │  Postgres │              │  (SD-card    │            │   (SMTP,   │
 │ (PostGIS) │              │   ZIPs,      │            │   DKIM-    │
 │  $15/mo   │              │   photos,    │            │   signed)  │
 │           │              │   reports)   │            │            │
 └─────┬─────┘              └──────┬───────┘            └────────────┘
       │                           │
       │       ┌───────────────────┴───────────┐
       └──────▶│  Worker Droplet               │
               │  (PyTorch + SpeciesNet +      │
               │   MegaDetector, Docker +      │
               │   systemd, polls job queue)   │
               │  $24/mo                       │
               └───────────────────────────────┘
```

**Roughly $56/mo all-in at today's scale.** Horizontally scales linearly
via additional worker Droplets consuming the same `processing_jobs`
queue with Postgres `FOR UPDATE SKIP LOCKED`.

---

## The Strecker arm

A secondary consumer-facing tool, [strecker.app](https://strecker.app),
runs on the same Flask process (host-routed) and the same ML pipeline.
It serves hunters and landowners a free trail-cam logbook: upload an SD
card, get back a dashboard with the actual photos sorted by species,
camera station, and hour.

The strategic role is supply-side — hunters bring their own trail-cam
data through the Basal pipeline. This grows the regional calibration
data that underpins Basal's per-parcel density estimates, and it
produces a natural on-ramp when a Strecker user's parcel shows up on a
Farm Credit loan book.

Architecturally, it's **the same codebase**. The brand, user flow, and
landing copy are different; the models, database, and detection code
are identical.

---

## Repository layout

```
config/              settings, species reference tables
db/
  models.py          SQLAlchemy / ORM
  migrations/        idempotent numbered SQL migrations
strecker/
  worker.py          background ML pipeline (Docker)
  detect.py          MegaDetector driver
  classify.py        SpeciesNet + calibration + priors
  ingest.py          ZIP → detections; independence filtering
  storage.py         DO Spaces client
bias/                IPW placement-bias correction
risk/                density estimation, tier classification, synthesis
habitat/             per-parcel habitat scoring (v2 product line)
report/              PDF + HTML report generation (ReportLab, Jinja)
web/
  app.py             Flask factory, host-based site resolution
  routes/            auth, properties, uploads, api, lender, owner
  templates/         basal/, dashboard/, auth/, errors/
  static/css/        basal.css (editorial), strecker.css (outdoor)
demo/                SYNTHETIC demo dataset — see notice below
tests/               395 passing tests
docs/                methodology, migration queue, pilot briefs
scripts/             migrate.py, deploy_worker.sh, build_test_sd.py
```

---

## ⚠️ Demo data

Everything under `demo/` — the "Edwards Plateau Ranch" scenario, the
pre-rendered `detections.json`, the demo seed scripts, the sample PDF
at `web/static/sample/nature_exposure_sample.pdf` — **is synthetic
data generated for product demonstration.** It is not a real ranch,
not real trail-cam photos, not the output of a real landowner
submission. Each file carries a header disclaimer to the same effect.

Production data (actual Farm Credit pilot parcels, actual hunter
uploads via Strecker) lives in the prod Postgres + Spaces, not in this
repository.

---

## Running locally

```bash
# 1. Postgres + PostGIS (dev, via compose)
docker-compose up -d db

# 2. Python deps (web container only — worker image is separate)
pip install -r requirements.txt

# 3. Copy the env template + fill in DATABASE_URL, SPACES_*, FLASK_SECRET_KEY
cp .env.example .env

# 4. Schema + demo data
python manage.py db migrate
python manage.py db seed          # synthetic — see notice above

# 5. Run both brands in demo mode on one process
python manage.py web               # :5002

# Basal landing:       http://localhost:5002/
# Strecker landing:    http://localhost:5002/?site=strecker
```

## Tests

```bash
pytest tests/ -v
```

395 tests across schema + migrations, methodology units (REM, IPW,
temporal priors, tier cutoffs), pipeline integration, worker job
claim semantics, lender report rendering parity, upload flows,
invite-code gating, and adversarial edge cases (empty ZIPs, bad EXIF,
unicode filenames, concurrent worker claims).

## Deployment

The DigitalOcean App Platform auto-deploys `main` on push. Worker
Droplet has its own deploy script:

```bash
# On the Droplet, as root:
cd /opt/strecker && ./scripts/deploy_worker.sh
```

Rebuilds the Docker image, applies pending schema migrations *in a
one-shot container off the fresh image* (so the migrator always sees
new `.sql` files), restarts the systemd unit.

---

## Operational status

- Pipeline live; 395 passing tests; Farm Credit pilot portal functional
- strecker.app live with invite-gated beta signup (see `docs/HUNTER_OUTREACH.md`)
- Email: DKIM-verified outbound from both `basal.eco` and `strecker.app`
- Sample Nature Exposure Report PDF:
  [basal.eco/static/sample/nature_exposure_sample.pdf](https://basal.eco/static/sample/nature_exposure_sample.pdf)
- Reinsurer pilot brief: `docs/REINSURER_ONE_PAGER.md`

## Contact

**Jonah Akira Cheng** — founder
[akira@strecker.app](mailto:akira@strecker.app) · Austin, TX

---

*This repository is published to document the product's technical
approach. Production customer data, specific tuning parameters beyond
what is cited above, proprietary training data, and commercial pilot
specifics are not included here.*
