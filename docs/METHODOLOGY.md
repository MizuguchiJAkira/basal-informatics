# Basal Informatics — Methodology

*One-page brief for ag lenders and loan-review committees. Intended audience:
Farm Credit System associations, regional agricultural banks, and the
portfolio-management / collateral-review teams that commission ecological
condition assessments on parcels they lend against.*

## Who submits the data

Landowners with active agricultural loans. Submission is either required
at loan renewal or incentivized through rate terms — the same
documentation pattern that already covers soil tests, yield records, and
irrigation logs. The landowner exports their own trail-cam SD cards and
uploads a single `.zip` through a Basal web form; the resulting Nature
Exposure Report is shared with their lender for collateral review.

Basal does not collect data from the landowner without their participation.
The lender commissions the report; the landowner supplies the raw photos;
Basal produces the methodology-backed output.

## What we measure

Per-species **density estimates** (animals/km²) for a parcel over a
defined survey period, with bootstrap 95% confidence intervals and a
sufficient/recommend-survey/insufficient-data flag. For feral hogs
specifically we also produce a **tiered Exposure Score** (Low /
Moderate / Elevated / Severe) and a modeled annual crop-damage
projection labeled as supplementary context.

We do not claim damage dollars as a pipeline output. The relationship
between hog density and parcel-scale crop loss is poorly characterized
in the literature (producer-survey recall bias, state-level
extrapolations that break down at parcel scale). What we publish is the
verified density + tier + projection — each clearly labeled according
to whether it came out of the pipeline or a downstream model. The loan
committee can use the tier as a binary go/no-go signal or feed the
density into its own internal collateral valuation without adopting
our damage model.

## Estimator: Random Encounter Model (REM)

Rowcliffe, Field, Turvey & Carbone 2008 (*Journal of Applied Ecology*):

```
D = (y/t) · π / (v · r · (2 + θ))
```

| Term | Meaning | Source |
|------|---------|--------|
| `D` | Density (animals / km²) | Output |
| `y/t` | Detections per camera-day | Computed from camera trap data |
| `v` | Mean daily travel distance (km/day) | Per-species, published |
| `r` | Camera detection radius (km) | Spec: 0.015 km (15 m) for medium IR |
| `θ` | Camera detection angle (radians) | Spec: 0.7 rad (~40°) for medium IR |

**Why REM, not capture-recapture or N-mixture?** REM does not require
individual identification, which is unreliable at population scale for
species without natural marks (feral hog, deer at distance, raccoon).
It also does not require closed-population assumptions, which are
violated by transient species at parcel scale.

### Per-species movement parameters

Hard-coded in `config/settings.py` (`SPECIES_MOVEMENT`):

| Species             | v (km/day) | sd  | Source                              |
|---------------------|-----------:|----:|-------------------------------------|
| Feral hog           | 6.0        | 2.5 | Kay et al. 2017; McClure et al. 2015 |
| White-tailed deer   | 1.5        | 0.8 | Webb et al. 2010                    |
| Axis deer           | 3.0        | 1.2 | Literature range (TX-specific scarce) |
| Coyote              | 10.0       | 4.0 | Andelt 1985                         |

For species without a published `v` (e.g. raccoon, opossum), we report
the raw detection rate (events per camera-day) as an unscaled index
and explicitly omit the density estimate. The recommendation flag
reads "insufficient data" with a method note explaining why.

## Confidence intervals

Bootstrap 95% via 1000 iterations:
- **Camera bootstrap**: resample cameras with replacement (the design's
  primary stochastic source per Rowcliffe 2012).
- **Movement-distance perturbation**: per-iteration `v_sample` ∼ N(v, sd),
  truncated to [0.5·v, 1.5·v]. Truncation prevents the upper CI tail
  from inflating ~10× under physically implausible v < 0.5·v_published
  values; the published `sd` captures inter-individual / inter-region
  variation, not within-survey uncertainty.

## Bias correction

Camera placement is non-random in operational deployments (feeders,
trails, water, crossings inflate detection rates by up to 9.7× per
Kolowski & Forrester 2017). We correct via inverse propensity weighting
on `placement_context`:

```
weighted_rate = sum_i (rate_i / P(placement_i | covariates_i))
              / sum_i (1 / P(placement_i | covariates_i))
```

Each camera carries a `placement_context` value from the user during
camera setup. Residual confounding is reported as a caveat in the
dashboard output.

(Implementation note: the bias module ships with the next release.
Tonight's dashboard reports unweighted rates with the placement caveat
surfaced explicitly.)

## Recommendation logic

Per species, per survey period:

| Condition                                                    | Flag                               |
|--------------------------------------------------------------|------------------------------------|
| `< 100` total camera-days OR `< 20` total events             | `insufficient_data`                |
| CI upper / CI lower ratio `> 1.5`                            | `recommend_supplementary_survey`   |
| Otherwise                                                    | `sufficient_for_decision`          |

Thresholds are tunable in `config/settings.py`:
`MIN_CAMERA_DAYS_FOR_DENSITY`, `MIN_DETECTIONS_FOR_DENSITY`,
`DENSITY_CI_RATIO_THRESHOLD`.

## What the loan-review committee gets

For each species on each parcel for each survey period, both the
lender dashboard (`/lender/<slug>/parcel/<id>`) and the JSON API
(`/lender/api/<slug>/parcel/<id>/exposure`) return a structured
record suitable for import into the lender's internal portfolio-
management system:

```json
{
  "species_key":              "feral_hog",
  "common_name":              "Feral Hog",
  "tier":                     "Elevated",
  "score_0_100":              50.6,
  "density_animals_per_km2":  5.13,
  "density_ci_low":           1.29,
  "density_ci_high":          16.64,
  "dollar_projection_annual_usd":       25561,
  "dollar_projection_ci_low_usd":        6432,
  "dollar_projection_ci_high_usd":      82963,
  "crop_modifier":            1.30,
  "n_cameras":                3,
  "total_camera_days":        174.0,
  "total_detections":         69,
  "recommendation":           "recommend_supplementary_survey",
  "caveats": [
    "Cameras at non-random placements (feeder, trail) violate REM's
     movement-independence assumption. Inverse propensity weighting
     (Kolowski & Forrester 2017) corrects for residual bias but does
     not eliminate it."
  ],
  "method_notes": [
    "Daily travel distance: v = 6.0 km/day (sd 2.5). Source: Kay et al. 2017.",
    "Dollar projection is a MODELED ESTIMATE, not a pipeline output..."
  ]
}
```

Audit trail is retained at **camera-day granularity**: individual
detection timestamps, SpeciesNet inference confidence per photo, and
the raw ZIP the landowner submitted. Available for any downstream
review the lender or its auditor runs.

## Pricing

- **Per parcel-verification:** $1,500 per report. One-time per survey window.
- **Portfolio unlimited:** $5,000 / month. Unlimited parcels in the lender's portfolio.

The alternative is a ~$40,000 independent field-biologist survey that's
point-in-time and goes stale inside six months. Basal is ~25× cheaper
at the per-parcel tier and continuously refreshable rather than stale.

## What we do not claim

- We do not estimate damage dollars.
- We do not estimate density for species without published movement
  parameters.
- We do not infer presence outside the camera's detection cone.
- We do not extrapolate beyond the surveyed property without explicit
  habitat-similarity tooling (separate product line).

## References

1. Rowcliffe JM, Field J, Turvey ST, Carbone C. 2008. Estimating animal
   density using camera traps without the need for individual recognition.
   *Journal of Applied Ecology* 45: 1228–1236.
2. Rowcliffe JM, Carbone C, Jansen PA, Kays R, Kranstauber B. 2011.
   Quantifying the sensitivity of camera traps using an adapted
   distance sampling approach. *Methods in Ecology and Evolution* 2: 464–476.
3. Kolowski JM, Forrester TD. 2017. Camera trap placement and the potential
   for bias due to trails and other features. *PLOS ONE* 12: e0186679.
4. Kay SL et al. 2017. Quantifying drivers of wild pig movement across
   multiple spatial and temporal scales. *Movement Ecology* 5: 14.
5. McClure ML et al. 2015. Modeling and mapping the probability of
   occurrence of invasive wild pigs across the contiguous United States.
   *PLOS ONE* 10: e0133771.
6. Webb SL, Hewitt DG, Hellickson MW. 2010. Survival and cause-specific
   mortality of mature male white-tailed deer. *Journal of Wildlife
   Management* 74: 1416–1421.
7. Andelt WF. 1985. Behavioral ecology of coyotes in south Texas.
   *Wildlife Monographs* 94: 3–45.
