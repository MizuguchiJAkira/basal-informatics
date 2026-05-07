# Basal Informatics — Reinsurer Brief

*For: reinsurance underwriting teams, ILS structuring desks, TNFD
quality-data leads. Two-page leave-behind; methodology and sample
artifact are linked at the bottom.*

---

## The problem a reinsurer actually has

Nature-related disclosure is moving from "comply with a narrative
framework" to "price the cedent's exposure." TNFD LEAP, EU CSRD ESRS
E4, the IFRS SASB biodiversity package, the FCA sustainability rules
in the UK — all converge on the same expectation: **biodiversity
exposure at the asset level, with a provenance chain a regulator or
an auditor can follow.**

The available data today falls short in one of three ways:

1. **Remote-sensed aggregates** (EO-based biodiversity indices,
   Impact Cubed, MSCI, WWF Risk Filter) give portfolio-level
   scores derived from habitat-overlap priors. They don't tell
   you what animals are on a specific acre, and they can't be
   re-verified against ground truth.
2. **Consultant field surveys** (~$40K/parcel, point-in-time) give
   you a single ecologist's notebook on one day in one quarter.
   They go stale inside six months and don't scale across a
   portfolio.
3. **Self-reported landowner data** (producer surveys, soil-test
   extrapolations) is recall-biased and non-reproducible.

None of those produce a density estimate with a defensible
confidence interval. None of them are refreshable.

## What Basal delivers

**Continuously-refreshed, parcel-level, primary-source species
inventories and density estimates with methodology-backed CIs.**

- Ingestion: landowner's trail-camera SD card → Basal pipeline
- Outputs per parcel per season:
  - Detection frequency (pre-REM relative abundance index)
  - Density estimate (animals/km², Rowcliffe 2008 REM)
  - 95% bootstrap CI (1,000 iterations, camera-level resampling +
    movement-parameter perturbation)
  - Mayer–Brisbin 2009 tier classification (Low / Moderate /
    Elevated / Severe — feral hog v1; other species in v2)
- JSON API with explicit separation between **pipeline outputs**
  (density, tier, CI) and **supplementary modeled projections**
  (damage dollars, clearly labeled as not-a-pipeline-output). A
  reinsurer's importer can consume one without accidentally
  consuming the other.
- Full audit trail at camera-day granularity: the raw SD-card ZIP,
  per-photo SpeciesNet inference confidence, all EXIF, all
  classifier thresholds applied.

## Why a reinsurer should care

### 1. The data primitive maps to how reinsurance already works

Reinsurance is priced from ground-truth loss data with a statistical
wrapper. Basal's pipeline produces ground-truth species data with a
statistical wrapper. The correspondence is exact:

- **Raw observation** = camera trigger + SpeciesNet class + EXIF timestamp
- **Individual event** = burst/independence filter applied
- **Aggregate metric** = detection rate per camera-day
- **Model output** = REM density + bootstrap CI
- **Classification** = Mayer-Brisbin tier

Same shape as claim → loss event → frequency/severity → modeled
loss. A reinsurer's quant can line up the two.

### 2. Parcel-level is the grain that matters

Portfolio-level biodiversity indices smear across hundreds of
geographies. Reinsurance contracts are written on specific assets
in specific ecoregions. The question "is this parcel adversely
impacted by hog pressure" is binary and per-parcel. Basal is the
only public tool that produces that binary with CI.

### 3. Refreshability changes the underwriting cadence

A consultant survey is a static document. Basal's pipeline ingests
on whatever cadence the landowner operates their cameras — typically
quarterly for active deployments. That turns biodiversity data from
an annual disclosure event into a tracked quantity. Cedent trajectory
becomes observable. Renewal conversations get a new dimension.

### 4. Defensibility against a disclosure challenge

Every number in a Nature Exposure Report is backed by a literature
citation: REM (Rowcliffe 2008, *J. Appl. Ecol.*), placement-bias
correction (Kolowski & Forrester 2017, *PLOS ONE*), tier cutoffs
(Mayer & Brisbin 2009), daily-travel-distance priors (Kay et al.
2017; Webb et al. 2010; Andelt 1985). The audit trail goes down to
the individual photo and its classifier confidence. This is the
regulatory-defense posture TNFD requires.

## Pilot shape

A reinsurer pilot looks different from the Farm Credit pilot the
codebase has built out. Two key differences:

1. **Cedent-driven, not landowner-driven.** The reinsurer surfaces
   2–10 cedents whose agricultural portfolios are suitable for
   per-parcel verification; Basal provides the upload tokens; the
   cedent's landowners upload over a 60-day window.
2. **Reporting cadence, not point-in-time.** Quarterly refresh
   over a 12-month observation period, producing four sequential
   parcel reports per pilot parcel. Lets the reinsurer observe
   whether tier trajectories are informative under their own
   modeling frameworks.

### What a 90-day pilot includes

- Up to **25 parcels** across 2–5 cedents, reinsurer's choice
- **Four refresh cycles** over 12 months (one every 90 days)
- **Per-parcel Nature Exposure Report** (HTML + PDF + JSON API)
- **Reinsurer dashboard** rolling up tier distribution + trajectory
  across the pilot portfolio
- **Methodology briefing** for the reinsurer's internal model-review
  committee — a written Q&A + live session
- **White-glove onboarding** of each cedent landowner
  (passwordless upload tokens emailed directly)

### Pilot price

- **$50K flat, prepaid.** Covers all parcels, all refreshes,
  methodology briefing, and reinsurer dashboard access for the
  12-month window.
- Steady-state post-pilot pricing negotiated from observed usage;
  standard rate is $5K/month for portfolio-unlimited access plus
  $1,500 per parcel-verification for one-off submissions outside
  a portfolio contract.

Compare to a single consultant field survey at ~$40K per parcel,
point-in-time, non-refreshable. The pilot produces 25×4=100
parcel-reports over the 12 months at the flat rate.

## What we won't do

- **We don't price risk.** Basal produces the inputs a reinsurer's
  quant team consumes. Density, tier, CI — those are outputs; the
  price is the reinsurer's job.
- **We don't estimate damage dollars as a pipeline output.** See
  docs/POPULATION_PIVOT.md — the compounded uncertainty is wider
  than the point estimate. A convenience dollar figure ships in
  the JSON under `supplementary_projection`, clearly labeled; the
  reinsurer's model should consume density, not dollars.
- **We don't aggregate outside the surveyed parcel.** Extrapolation
  to neighboring or unsurveyed parcels requires habitat-similarity
  tooling which is a separate product line (scheduled for v2).

## Artifacts

- **Sample Nature Exposure Report (PDF)** —
  [basal.eco/static/sample/nature_exposure_sample.pdf](https://basal.eco/static/sample/nature_exposure_sample.pdf)
- **Full methodology** — [basal.eco/methodology](https://basal.eco/methodology)
- **Live lender portal** (Farm Credit pilot) —
  [basal.eco/lender/acme/](https://basal.eco/lender/acme/)
- **Sample JSON API response** —
  [basal.eco/lender/api/acme/parcel/12/exposure](https://basal.eco/lender/api/acme/parcel/12/exposure)

## Contact

**Jonah Akira Cheng** — founder
[hello@basal.eco](mailto:hello@basal.eco)
basal informatics · Austin, TX

---

*This document is a pilot proposal only. Any commercial engagement is
subject to a mutually-executed pilot agreement.*
