# Strecker Pilot Deployment Guide

Target shape (~$44/mo):

```
App Platform (web)  ─┐                         ┌─► Managed Postgres
   slim image        ├─► enqueues job rows ───►│       (shared)
   DEMO_MODE=0       │                         │
                     │                         └─► DO Spaces (ZIPs, PDFs)
                     │                              ▲
Worker Droplet       │                              │
  full ML image      └────── polls job rows ◄───────┤
  torch + speciesnet                                │
                                                    │
Basal Informatics (later) ── reads DetectionIngest ◄┘
```

---

## 1. Provision Managed Postgres

DO Console → **Databases** → Create → PostgreSQL 16 → **Basic ($15/mo)** is
fine for pilot volumes.

- Region: same as App Platform (e.g. NYC3).
- Leave DB name default (`defaultdb`) or create `strecker`.
- Under **Trusted sources**, add your App Platform app and the Worker Droplet
  once both exist (or leave open and restrict later).

Copy the **connection string** under "Connection Details". It looks like:

```
postgresql://doadmin:XXXXX@db-postgresql-nyc3-12345.b.db.ondigitalocean.com:25060/defaultdb?sslmode=require
```

Save it — you'll paste it into both the web app env and the worker Droplet.

## 2. Provision Spaces

DO Console → **Spaces Object Storage** → Create a Space → NYC3 → name it
`strecker-pilot` (must be globally unique).

Then create an **access key**: DO Console → API → Spaces Keys → Generate.
Save the key + secret; DO shows the secret exactly once.

## 3. Wire App Platform

In your existing `strecker` app → Settings → Environment Variables → add:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | the full Postgres URL from step 1 |
| `SPACES_BUCKET` | `strecker-pilot` |
| `SPACES_REGION` | `nyc3` |
| `SPACES_ENDPOINT` | `https://nyc3.digitaloceanspaces.com` |
| `SPACES_KEY` | your Spaces access key |
| `SPACES_SECRET` | your Spaces secret (mark as encrypted) |
| `DEMO_MODE` | `0` |
| `FLASK_DEBUG` | `0` |
| `FLASK_SECRET_KEY` | (already set) |

Remove `DATABASE_URL=sqlite:...` if it's still there from the earlier workaround.

Save. App Platform will auto-redeploy. On boot it runs `db.create_all()` so
the schema materializes on first deploy.

## 4. Provision Worker Droplet

DO Console → **Droplets** → Create → Ubuntu 22.04 → **Basic / Regular / 2GB RAM**
($12/mo) → same region as Postgres & Spaces → add your SSH key → create.

Once it's up (~60s), SSH in:

```bash
ssh root@<droplet-ip>
curl -fsSL https://raw.githubusercontent.com/MizuguchiJAkira/strecker/main/deploy/worker/bootstrap.sh | bash
```

The bootstrap:
1. Installs Docker.
2. Clones the repo to `/opt/strecker`.
3. Builds `Dockerfile.worker` (takes ~10 min — PyTorch is chunky).
4. Creates `/etc/strecker/worker.env` (empty template).
5. Installs + enables `strecker-worker.service`.

Fill the env file:

```bash
nano /etc/strecker/worker.env
```

Paste the same `DATABASE_URL` and Spaces credentials as the web app. Save.

Start it:

```bash
systemctl start strecker-worker
journalctl -fu strecker-worker
```

Expected first log lines:

```
Starting Strecker worker (id=<hostname>, poll=10s, stale=60min)
DB: db-postgresql-nyc3-12345.b.db.ondigitalocean.com:25060/defaultdb
Storage: Spaces/strecker-pilot
```

## 5. End-to-end smoke test

From your browser:

1. Visit the App Platform URL, register, log in.
2. Upload a small ZIP of trail-cam photos.
3. Watch the job transition: `queued → processing → classifying → reporting → complete`.
4. Download the PDF — it's streamed from Spaces through the web app.

Confirm on the worker:

```bash
journalctl -u strecker-worker --since "5 minutes ago"
# Should show: Claimed job <id>  →  Job <id> complete
```

## 6. Updating the worker later

Any change pushed to `main`:

```bash
ssh root@<droplet>
bash /opt/strecker/deploy/worker/update.sh
```

This does `git pull`, rebuild, `systemctl restart`. The worker finishes its
current job before restarting (graceful SIGTERM, 10min `TimeoutStopSec`).

## Cost summary

| Item | Monthly |
|---|---|
| App Platform Basic | $12 |
| Managed Postgres Basic | $15 |
| Worker Droplet (2GB) | $12 |
| Spaces (250GB) | $5 |
| **Total** | **~$44** |

## When to upgrade

- **Postgres** → Professional when connection count > 22 or latency matters
- **Worker** → 4GB+ or GPU when per-ZIP processing > 10 minutes
- **Dispatch layer** (Celery/RQ) → when > 100 jobs/day sustained, or when
  retry-with-backoff matters

## Data lifecycle

- ZIPs are deleted from Spaces after successful processing (worker does this).
- Report PDFs are retained indefinitely.
- Failed jobs keep their ZIP (so you can retry manually).
- `processing_jobs` rows are permanent — they're the audit trail.

## Backups

Managed Postgres auto-backs-up daily (included). Spaces does not — if you
care about the PDFs long-term, configure lifecycle rules or set up
cross-region replication later.
