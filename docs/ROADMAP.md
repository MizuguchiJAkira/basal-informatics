# Strecker / Basal Informatics — Roadmap to YC Demo

**Demo target:** ~ +30 days from 2026-04-16
**Anchor:** A defensible, narratable 90-second product demo on a stable URL
plus a methodology brief that survives an actuary's scrutiny.

## Status snapshot (2026-04-17)

✓ Lender pivot shipped: LenderClient model, exposure engine, /lender routes, 5-parcel portfolio
✓ Farm Credit of Central Texas portfolio live (verified via JSON + HTML render)
✓ REM density estimator + Feral Hog Exposure Score (17 new tests; 40/40 green)
✓ Compliance-aesthetic UI (portfolio table + Nature Exposure Report)
✓ 4 GB worker Droplet (upsized from 2 GB — SpeciesNet now runs without OOM)
✓ Methodology + demo narrative + session log committed (YC-partner framing)
✓ Stability: idle-transaction leak fixed, gunicorn tuned, health-check window bumped
✓ basal.eco registered at Namecheap, DNS records entered, App Platform domain added
~ DNS propagation in progress (.eco registry delegation not yet published; ~15 min – few hours typical for newly-registered domains)
✗ Pre-signed Spaces URL upload path (Week 2)
✗ Live ML pipeline validated end-to-end through a real upload (Week 2)
✗ IPW bias correction wired into REM input (Week 3)

## Week 1 — Demo polish (this week)

The dashboard works. This week is about making it bulletproof for the
demo and visible from a real domain.

| Day | Task | Owner | Done? |
|-----|------|-------|-------|
| Mon | Custom domain DNS records (CNAME apex → App Platform) | User | ☐ |
| Mon | App Platform domain config + Let's Encrypt | Claude | ☐ |
| Mon | Update marketing home page meta tags (OG image, title) | Claude | ☐ |
| Tue | Replace placeholder `preview-*.png` with real dashboard screenshots | User+Claude | ☐ |
| Tue | Add downloadable Methodology PDF link to dashboard | Claude | ☐ |
| Wed | Buff demo narrative to user's voice | User | ☐ |
| Wed | First full demo run-through with stopwatch | User | ☐ |
| Thu | Address whatever felt awkward in run-through | Claude | ☐ |
| Fri | Practice run on the new domain end-to-end | User | ☐ |

## Week 2 — Architecture hardening

The demo flow doesn't depend on uploads, but the product story does. This
week takes the upload path from "untested-but-shipped" to "observed-working"
and addresses the connection pool fragility for real.

| Day | Task | Notes |
|-----|------|-------|
| Mon | Pre-signed Spaces URL upload route | Browser PUTs ZIP directly to Spaces; web container only writes a row. Eliminates the boto3-hung-the-request failure class. |
| Mon | Worker upsize to 4 GB | $24/mo. Validates SpeciesNet on real photo batches. |
| Tue | End-to-end ZIP upload test through new flow | Document timing per phase. |
| Wed | PgBouncer (DO connection pooler) in front of Postgres | Removes the 22-slot Basic-tier ceiling that bit us tonight. |
| Thu | Variance decomposition: report camera-bootstrap CI + v-sensitivity separately | Methodologically cleaner. Slightly tighter headline numbers. |
| Fri | Add `/api/properties/<pid>/uploads` polling to property dashboard | "Upload Photos" button leads to a working flow. |

## Week 3 — Methodology rigor + observability

| Day | Task | Notes |
|-----|------|-------|
| Mon | `bias/ipw.py` — placement-context inverse propensity weighting | The 9.7× trail/feeder inflation factor (Kolowski 2017) |
| Tue | Wire IPW-adjusted detection rate into REM input | Reports both raw + adjusted rates |
| Wed | Sentry or DO log forwarding | Visibility into the gunicorn/worker pipeline without SSH'ing |
| Thu | Test the methodology page with a friendly ecologist | Sanity check before showing investors |
| Fri | One-pager methodology PDF generator (server-side render) | Downloadable from dashboard + included in pilot deck |

## Week 4 — Pilot prep + demo rehearsal

| Day | Task | Notes |
|-----|------|-------|
| Mon | Farm Credit pilot one-pager: problem, methodology, verification artifact | The leave-behind PDF a loan-review committee can read in 10 minutes |
| Tue | Outreach to first Farm Credit System contact (TX association first — same geography as our seed) | Get one pilot conversation booked |
| Wed | Demo recording (fallback for live demo failures) | 1280×800, exact same flow |
| Thu | Final dashboard polish based on practice runs | Cosmetic only; no architectural changes |
| Fri | DEMO DAY | Use custom domain, not the App Platform default |

## Risk register

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| App Platform deploy fails on demo day | Low | Health-check window now 5 min; deploys validated repeatedly. |
| Worker OOM during live ML demo | Medium | Demo narrative does not require live ML; seeded data is the demo. |
| Custom domain DNS not propagated in time | Medium | Set up Week 1, day 1. Allow 48h propagation buffer. |
| Reinsurer asks for a metric we don't compute | Medium | Methodology doc lists what we DO and DO NOT claim explicitly. |
| Browser warns "dangerous site" during demo | Low after domain setup | Custom domain Step 1 fixes this. |
| Postgres connection slot exhaustion | Low after pool fixes | PgBouncer (Week 2 Wed) makes it impossible. |
| Live demo crashes mid-pitch | Low | Pre-recorded fallback (Week 4 Wed). |

## Decisions deferred to user

These are choices I cannot make without you:

1. **Custom domain.** What apex? `strecker.basalinformatics.com`? Something
   else? Does Basal Informatics own the apex DNS?
2. **Pricing model.** Per-property subscription? Per-survey? Reinsurer-paid
   per-parcel-verified? Fills the TODO in `DEMO_NARRATIVE.md`.
3. **Raise amount.** Fills the TODO in `DEMO_NARRATIVE.md` Beat 4.
4. **First Farm Credit contact.** Which association? District (Texas
   Agriculture Credit, Capital Farm Credit, Legacy Ag Credit, etc.) or
   AgFirst/FCS America headquarters-level? What's the lead-time for a
   pilot conversation — branch decision vs. bank-wide steering committee?
5. **Demo style.** Live demo with risk of crashes vs. pre-recorded with
   no risk but less interactive feel.

## What stays out of scope until after demo

- Mobile app
- Multi-property portfolio view
- Historical (multi-year) trend analysis
- Damage-dollar projections (POPULATION_PIVOT.md explicitly defers these)
- Re-ID for individual deer tracking (the dashboard has a placeholder UI
  but no backing model; ship it as "coming soon" rather than half-built)
- B2B-API for lender portfolio integration (post-pilot — the pilot
  conversation will dictate what shape the import/export API needs)
- Reinsurer / TNFD-disclosure channel — secondary market that picks up
  once the lender motion has 3+ signed pilots and we can publish
  methodology-validated ecological data at scale
