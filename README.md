# Basal Informatics

Primary-source ecological verification for agricultural lenders and reinsurers
facing TNFD / EU CSRD nature-risk disclosure. We turn trail-camera SD cards
into parcel-level species inventories, density estimates with CIs, and a
standardized damage-risk tier — orders of magnitude cheaper than the
consultant-led biodiversity assessments they replace.

Live: [basal.eco](https://basal.eco) (fallback:
[monkfish-app-ju2lv.ondigitalocean.app](https://monkfish-app-ju2lv.ondigitalocean.app))

## What it ships

The codebase is a two-site Flask app sharing a Postgres/PostGIS backbone:

- **Basal site** (`SITE=basal`) — lender / reinsurer portal. Editorial landing
  page at `/`, per-lender portfolio at `/lender/<slug>/`, per-parcel report
  at `/lender/<slug>/parcel/<id>`, JSON exposure feed at
  `/lender/api/<slug>/parcel/<id>/exposure`.
- **Strecker site** (`SITE=strecker`) — hunter-facing ingestion. SD-card ZIP
  upload → MegaDetector + SpeciesNet on a GPU worker → detection summaries
  write back to the same Postgres.

Both sites share:

- `db/` — SQLAlchemy models + PostGIS schema
- `web/` — Flask factory (`create_app(demo=?, site=?)`), routes, templates,
  branded static assets
- `strecker/worker/` — background GPU pipeline (runs on the Droplet, not
  in the web container; web never imports torch)
- `bias/`, `habitat/`, `risk/` — the methodology modules invoked by the
  parcel-report generator (IPW debias, REM density, Mayer-Brisbin tiers)
- `report/` — PDF + HTML lender-report templates
- `demo/` — deterministic synthetic dataset for `DEMO_MODE=1`

## Setup

```bash
# Copy environment config
cp .env.example .env

# Start PostGIS locally
docker-compose up -d db

# Install Python dependencies (web container only — worker is separate)
pip install -r requirements.txt

# Initialize schema
python manage.py db init

# Seed demo lender / parcels / detections
python manage.py db seed
```

## Running locally

```bash
# Basal site (lender portal) on :5002
SITE=basal python -c "from web.app import create_app; \
  create_app(demo=True, site='basal').run(port=5002)"

# Strecker site (hunter uploads) on :5001
SITE=strecker python -c "from web.app import create_app; \
  create_app(demo=True, site='strecker').run(port=5001)"
```

With `.claude/launch.json` in place, the Claude Preview MCP (`preview_start
basal-web`) does the same thing.

## Tests

```bash
pytest tests/ -v
```

Coverage spans eight layers: schema, models, methodology units (IPW / REM /
Mayer-Brisbin), pipeline integration, worker contract, lender report
rendering, route API smoke tests, and exhaustive regression on the six
PDF-parity additions to the inline parcel report.

## Deployment

DigitalOcean App Platform auto-deploys `main` on push:

- `web` service — `gunicorn wsgi:app`, both sites behind the same domain,
  `SITE` env var toggles which one renders at `/`
- `worker` service — GPU Droplet consuming jobs from the `ProcessingJob`
  table
- Managed Postgres + PostGIS
- Spaces bucket for SD-card ZIPs

Env flags that matter in production: `DEMO_MODE`, `SITE`, `DATABASE_URL`,
`FLASK_SECRET_KEY`, `SPACES_*`, `MEGA_MODEL_PATH`.

## Status

- Editorial landing + lender portal: live
- Strecker ingestion pipeline: live
- basal.eco DNS: waiting on the registry to clear `serverHold` after the
  .eco sustainability pledge was submitted at community.eco
- Next milestone: Matagorda Bay field calibration + first reinsurer LOI
