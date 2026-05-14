# YC Demo Run Sheet — Basal Informatics

Prep + click sequence for the YC application video.

---

## 0. Environment prep

Run once before recording.

```bash
# 1. Clean demo DB so schema matches latest models.
cd /Users/jonahakiracheng/Desktop/Basal_Informatics_v2/basal-informatics
rm -f instance/basal.db instance/basal.db.bak-*

# 2. Install TNDeer real trail-cam photos onto Edwards Plateau.
#    (234 real photos distributed across 8 species, bear + elk + nulls excluded.)
python3 demo/seed/install_tndeer_photos.py

# 3. Start the Basal demo server.
#    DB auto-creates + Edwards Plateau auto-seeds at boot.
python3 -c "import sys; sys.path.insert(0, '.'); \
  from web.app import create_app; \
  app = create_app(demo=True, site='basal'); \
  app.run(port=5002, debug=False)" &

# 4. Wait ~5 seconds for boot, then seed the lender portfolio.
sleep 5
python3 demo/seed/seed_lender_portfolio_sqlite.py

# Verify
curl -sf http://localhost:5002/health
```

Expected `/health` response:
```json
{"db": true, "default_site": "basal", "demo": true, "site": "basal", "status": "ok"}
```

---

## 1. URLs in camera order

| # | URL | What it shows | Hero |
|---|---|---|---|
| 1 | `http://localhost:5002/` | Editorial landing page — hero, pipeline diagram, Riverbend worked example | ⭐ open with |
| 2 | `http://localhost:5002/lender/acme/` | Acme Agricultural Credit portfolio — 2 parcels, 1 Severe + 1 Low | ⭐ |
| 3 | `http://localhost:5002/lender/acme/parcel/2` | Riverbend Farm Nature Exposure Report (Severe, 83.7/100) | ⭐⭐⭐ |
| 4 | `http://localhost:5002/lender/acme/parcel/1` | Edwards Plateau Ranch Nature Exposure Report (Low, 12.1/100) | ⭐⭐ |
| 5 | `http://localhost:5002/demo` | "Run Assessment" — click-to-execute pipeline demo | ⭐⭐⭐ |
| 6 | `http://localhost:5002/static/sample/nature_exposure_sample.pdf` | 8.2 MB sample PDF report (institutional artifact) | ⭐ closer |

**Demo mode auto-logs in as `owner@basal.eco` — no password entry on camera.**

---

## 2. Click sequence (90–120 sec video)

### Opening: the landing page tells the story (15s)
1. Navigate to `/` — let the dark hero land. Voiceover: "Brier branches are underwriting billions against farmland; their ecological due-diligence today is a one-shot biologist survey, stale on arrival."
2. Scroll to the "Riverbend Farm, Brazos Co. — 650 acres of corn" worked example. Voiceover: "Here's what a live report looks like — 83.7/100 Severe feral-hog exposure, density trajectory up 138% since the prior survey."

### Lender view: portfolio → parcel (45s)
3. Click the "See live portfolio" CTA, or navigate `/lender/acme/`.
4. Point at the tier tally bar: **1 LOW · 0 MODERATE · 0 ELEVATED · 1 SEVERE**. Voiceover: "Two parcels under assessment — one tier diversity row, which is what Farm Credit committees want to see at a glance."
5. Click **Riverbend Farm** row → lands on `/lender/acme/parcel/2`.
6. Point at the Executive Summary: "Feral Hog Exposure: Severe — 13.49 animals/km² (95% CI 6.46–33.56)." Voiceover: "Every number carries a confidence interval. Every methodology decision is a citation."
7. Scroll to the **Feral Hog Exposure Score: 83.7/100 SEVERE** with the tier bar. Voiceover: "This is the committee-ready signal — bias-adjusted rate consumed by a Random Encounter Model, tier assigned per Mayer & Brisbin 2009."
8. Scroll to **Modeled Projection $22,999/yr (CI $11,006 – $57,205)**. Voiceover: "Supplementary damage estimate labeled clearly as a modeled projection, not a pipeline output — we surface the signal separately from the economic overlay."
9. Scroll to the **Caveats** panel. Voiceover: "Every caveat the committee would want surfaced is stated plainly."

### Live run: execute the pipeline (20s)
10. Click **Enterprise Demo** in top-right nav → lands on `/demo`.
11. Point at left card: "Demo Parcel — TX-KIM-2024-04817, Kimble County TX, 2,340 acres, 14 cameras, 10 months monitoring."
12. Point at right card: "Pipeline Stages — Strecker ingest+classify → Habitat analysis → IPW bias correction → Risk synthesis → Enterprise PDF."
13. Click the teal **Run Assessment** button.
14. Wait for the progress + results view. PDF downloads.

### Close (15s)
15. Open the downloaded PDF briefly (or route `/demo/download-pdf`). Voiceover: "The artifact your committee gets."
16. End on the home page with the pricing section: "Pilot engagements with ag lenders and reinsurers."

---

## 3. Gotchas

| Issue | Fix |
|---|---|
| `/lender/acme/parcel/*` returns 500 with `no such column: processing_jobs.zip_key` | DB schema drift. Run Env Prep step 1 again. |
| `/lender/acme/` returns 404 or "No lenders" | Seed wasn't run. Run `python3 demo/seed/seed_lender_portfolio_sqlite.py`. |
| Dashboard or parcel report shows old styling | Flask has template caching on. Kill + restart the server: `lsof -ti:5002 \| xargs kill` then re-run. |
| Port 5002 already in use | `lsof -ti:5002 \| xargs kill` |
| `Run Assessment` button stalls | The demo pipeline takes ~20–30 seconds. Don't click twice. |
| Trail-cam photos in dashboard are synthetic-looking | TNDeer photos install to `demo/output/sorted/<species>/*.jpg`. Re-run `python3 demo/seed/install_tndeer_photos.py`. |

---

## 4. What is NOT in the demo

These are intentionally excluded so the video stays tight:

- **Strecker-side** (localhost:5001) — hunter game-inventory dashboard. Different product; don't mix into Basal pitch.
- **My Deer / individual re-identification** — Coming Soon in the app; don't open that section.
- **Upload flow** at `/properties/<id>/upload` — not part of the Basal lender story.
- **Coverage Map** at `/owner/coverage` — internal staff view; no customer value in showing.

---

## 5. Known aesthetic caveats

- **Riverbend parcel map** lands on the Texas A&M RELLIS Campus footprint (the lat/lon I chose for the seed falls there). Not inaccurate — it's real Brazos Co TX land — but if it distracts, move the seed coordinates in `demo/seed/seed_lender_portfolio_sqlite.py` → `cam_configs` to a more pastoral location south of Bryan.
- **The landing page "Riverbend Farm, Brazos Co." parcel card** is hardcoded HTML on `landing.html`. The live `/lender/acme/parcel/2` matches its numbers (83.7, 13.49, $22,999) but the live report's camera names and placement contexts are different from what the landing claims verbatim. Don't put both on screen at once.
- **`/demo/run`** uses the full existing 12K-record synthetic manifest as the data source — NOT the TNDeer photo subset. The TNDeer photos are purely the visible imagery layer. The score/tier/density the pipeline produces comes from the synthetic statistical spine.

---

Last updated after commit hash TBD (post-commit this file lives in `demo/YC_DEMO_RUNSHEET.md`).
