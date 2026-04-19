# Upload Live-Run Runbook

The first real SD-card upload. Everything in code is ready; this doc
captures the human-side steps that the pipeline can't do itself — CORS
on Spaces, worker `.env`, how to mint a token, what logs to tail, and
the failure modes to expect.

Read top-to-bottom the first time; after that, jump to the checklist at
the end.

## 1. Infrastructure prereqs

### 1.1 DigitalOcean Space

Exists already (`SPACES_BUCKET=strecker-uploads` in prod). Two things to
confirm **before** the first browser → Space PUT:

**CORS policy on the bucket** (DO console → Space → Settings → CORS).
The browser PUT sends a preflight `OPTIONS` and then a `PUT`; both need
ACAO set. Paste this CORS config:

```xml
<CORSRule>
  <AllowedOrigin>https://basal.eco</AllowedOrigin>
  <AllowedOrigin>https://monkfish-app-ju2lv.ondigitalocean.app</AllowedOrigin>
  <AllowedMethod>PUT</AllowedMethod>
  <AllowedMethod>GET</AllowedMethod>
  <AllowedMethod>HEAD</AllowedMethod>
  <AllowedHeader>Content-Type</AllowedHeader>
  <AllowedHeader>x-amz-*</AllowedHeader>
  <ExposeHeader>ETag</ExposeHeader>
  <MaxAgeSeconds>3600</MaxAgeSeconds>
</CORSRule>
```

If you're hitting a localhost dev build from a browser, add
`http://localhost:5001` and `http://localhost:5002` to the allowed
origins. Do **not** use `*`.

**Lifecycle policy** (optional but recommended):

- Delete objects under `uploads/*/upload.zip` older than 90 days — the
  ZIP is only needed until the worker finishes processing; retaining it
  past that is data liability.
- Delete `uploads/*/output/*` older than 365 days — reports live in the
  DB anyway.

### 1.2 Worker Droplet `.env`

On the 4 GB Droplet that runs `strecker-worker.service`. These must
match the web container:

```sh
DATABASE_URL=postgres://user:pass@<managed-pg>/strecker  # same as web
FLASK_SECRET_KEY=<same as web>
SPACES_BUCKET=strecker-uploads
SPACES_KEY=<do-spaces-access-key>
SPACES_SECRET=<do-spaces-secret>
SPACES_REGION=nyc3
SPACES_ENDPOINT=https://nyc3.digitaloceanspaces.com

# Model paths (models/ is provisioned by deploy/worker/bootstrap.sh)
MEGADETECTOR_PATH=/opt/basal/models/megadetector_v5.pt
SPECIESNET_MODEL=kaggle:google/speciesnet/pyTorch/v4.0.2a/1

# Tuning
MEGADETECTOR_CONFIDENCE_THRESHOLD=0.15
SPECIESNET_CONFIDENCE_THRESHOLD=0.7
```

Verify the service is running:

```sh
ssh worker
systemctl status strecker-worker
journalctl -u strecker-worker -f   # tail in one shell for the run
```

### 1.3 Web container env

On DO App Platform, under the web service:

- `DATABASE_URL` — managed Postgres
- `SPACES_BUCKET`, `SPACES_KEY`, `SPACES_SECRET`, `SPACES_REGION`,
  `SPACES_ENDPOINT` — same values as worker
- `DEMO_MODE=0` — do **not** leave this on for real uploads; demo mode
  auto-logs you in as the seed user and will attribute the real upload
  to that account

## 2. Mint a token

Two paths.

### 2.1 From the admin dashboard (when it ships)

`/admin/parcels/<id>/tokens` → "Mint share link" → copy the URL. That
UI isn't built yet; use 2.2 for now.

### 2.2 From `curl`

Log into the web site in a browser first to get a session cookie. Then
the browser's dev-tools → Application → Cookies, copy `session=...`.

```sh
curl -X POST https://basal.eco/api/properties/<parcel_id>/upload-tokens \
  -H "Content-Type: application/json" \
  -b "session=<session-cookie>" \
  -d '{
        "label": "Matagorda pilot · Phil Moore",
        "email_hint": "phil@matagorda-ag.test",
        "uses": 3,
        "ttl_days": 30
      }'
```

Response:

```json
{
  "token": "a1b2c3d4...",
  "share_url": "https://basal.eco/u/a1b2c3d4...",
  "uses_remaining": 3,
  "expires_at": "2026-05-19T..."
}
```

Email that `share_url` to the landowner. Until the admin UI ships,
Basal ops is the middleware.

## 3. What the landowner sees

They open the link → `/u/<token>` shows a landing page with the parcel
name, acreage, and a file-picker. They pick their SD-card ZIP, hit
Upload, and watch a progress bar. Under the hood:

1. `POST /u/<token>/uploads/request` → presigned URL from Spaces
2. Browser `PUT` direct to Spaces with `XMLHttpRequest` upload-progress
3. `POST /u/<token>/uploads/<uid>/confirm` → server HEADs Spaces,
   enqueues `ProcessingJob`
4. `GET /u/<token>/uploads/<uid>/status` polled every 2s until
   `complete` or `error`

## 4. What to watch during the run

Three tail points:

### 4.1 Web logs (DO App Platform dashboard → Runtime Logs)

You should see, in order:

```
INFO  Token <prefix>: issued pre-signed PUT for parcel <pid>, upload <uid>
INFO  Token <prefix> confirmed upload <uid> → job <jid> (uses_remaining=<N-1>)
```

If the `confirmed` line doesn't appear within 30 seconds of the
`issued` line, the landowner's PUT to Spaces failed. Check CORS. Check
that the presigned URL hasn't expired (`PRESIGN_TTL_SECONDS = 900`).

### 4.2 Worker logs

```sh
ssh worker
journalctl -u strecker-worker -f
```

You should see, within ~30s of confirm:

```
INFO  Claimed job <jid>
INFO  Job <jid>: downloaded ZIP (<N> bytes)
INFO  Job <jid>: ingest → N_photos photos, N_events events
INFO  Job <jid>: classify → N_species species
INFO  Job <jid>: report generated, uploaded
INFO  Job <jid>: complete
```

### 4.3 Spaces console

You can directly inspect `strecker-uploads/uploads/<jid>/upload.zip`
and `strecker-uploads/uploads/<jid>/output/game_inventory_report.pdf`
to confirm bytes landed.

## 5. Failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser PUT fails with CORS error | Space CORS not configured | §1.1 |
| PUT returns 403 | `SPACES_KEY` / `SPACES_SECRET` mismatch | Web env |
| `/confirm` returns `"Upload not found in storage."` | PUT didn't actually land | Check network tab; check Spaces object listing |
| Status stuck at `queued` for > 1 min | Worker not running OR can't reach DB | `systemctl status`, DB creds |
| Status jumps to `error` | Worker raised | `journalctl` for traceback |
| Classifier OOMs | Droplet too small (was 2 GB, now 4 GB) | Upsize or shrink batch |
| Odd timezone in timestamps | EXIF `DateTimeOriginal` read as naive | Expected; we interpret as local-to-parcel |
| Duplicate-photo rate weird | Inter-trigger independence (30 min) unusual | Set `INDEPENDENCE_THRESHOLD_MINUTES` explicitly |
| `complete` but no `DetectionSummary` rows in lender view | `_aggregate_to_property` hit a season boundary | Re-seed season, rerun via `manage.py reaggregate <property_id>` |

## 6. Smoke test

Before each live run, verify the wiring locally:

```sh
python scripts/smoke_upload.py
```

Drives the full three-phase flow against local-fs storage and asserts
the `ProcessingJob` + token state land in the right shape. Takes ~2s.

## 7. Checklist for the first live SD-card

- [ ] Space CORS includes the production origin
- [ ] Worker Droplet `.env` has Spaces creds + DB URL
- [ ] `systemctl status strecker-worker` = active
- [ ] Web `DEMO_MODE=0` on DO
- [ ] `python scripts/smoke_upload.py` → exit 0
- [ ] Token minted against the target parcel; `share_url` captured
- [ ] Worker logs tailing in a shell (`journalctl -u strecker-worker -f`)
- [ ] DB access in a second shell to `SELECT * FROM processing_jobs ORDER BY submitted_at DESC LIMIT 5;`
- [ ] Landowner confirmed they can open the share link
- [ ] Upload initiated; watch the three log streams

## 8. After the run

- `n_photos`, `n_species`, `n_events` appear on the `ProcessingJob`
  row — sanity-check the species list isn't all "unknown" (if it is,
  confidence threshold may be too high for that camera set)
- Lender portal at `/lender/<slug>/parcel/<pid>` should render with
  real detections instead of demo-seed data
- `DetectionSummary` rows visible in Postgres for the season
- Revoke the one-shot token: `DELETE /api/properties/<pid>/upload-tokens/<token>`
