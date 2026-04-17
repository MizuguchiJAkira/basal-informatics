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

Pipeline outputs — **index + density + tier**, in that order of
primacy:

1. **Detection frequency** (events per camera-day): the raw relative
   abundance index, computed directly from independent-event counts.
   This is the pre-REM, minimum-assumption quantity. Two parcels
   surveyed with identical camera deployments can be compared on this
   number alone without invoking any movement-distance assumption.
2. **Density estimate** (animals/km²): the REM-scaled per-area
   population derived from the detection rate using per-species daily
   travel distance. Reported with a bootstrap 95% confidence interval.
3. **Tier** (Low / Moderate / Elevated / Severe, feral hog only v1):
   the binary-decision-grade classification per Mayer & Brisbin 2009
   hog-density bins. Drives the loan-review committee's
   go / condition / no-go / survey-required decision path.

Alongside these we also publish an **Exposure Score** (0–100,
piecewise-linear anchored on the tier cutoffs) for visual legibility
on a single gauge, and a **modeled annual crop-damage projection** as
supplementary context — but those are derivations, not the primary
outputs.

Damage dollars are NOT a pipeline output. The relationship between hog
density and parcel-scale crop loss is poorly characterized in the
literature (producer-survey recall bias, state-level extrapolations
that break down at parcel scale). We produce the density + rate + tier
with methodology-defensible confidence intervals; the dollar-scaling
is attached separately under a `supplementary_projection` object in
the JSON API, with its own disclaimer. A loan committee with an
internal damage model should consume the pipeline outputs directly
and ignore our dollar block; committees without an internal model can
use our dollar figure as a convenience projection, clearly labeled.

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

Camera placement is non-random in operational deployments. Feeders,
trails, water sources, and food plots inflate per-camera detection
rates by 1.4-9.7× depending on species and context (Kolowski &
Forrester 2017). Without correction, REM density inherits this
inflation directly. The pipeline applies two complementary corrections
on the per-camera detection rate before it enters REM, and reports
both alongside the raw rate.

### Method 1 — Literature-prior ratio adjustment (PRIMARY)

For each camera at a non-random context, deflate the observed
per-camera rate by a per-species, per-context inflation factor sourced
from the literature, then average across cameras:

```
adjusted_rate = mean_i ( rate_i / inflation_factor[species, context_i] )
```

Inflation factors for feral hog (`config/settings.py` →
`bias.placement_ipw.DEFAULT_INFLATION_FACTORS`):

| Context    | Feral hog | White-tailed deer | Coyote | Source |
|------------|----------:|------------------:|-------:|--------|
| feeder     | 10.0×     | 4.0×              | 1.5×   | Kolowski 2017; Mayer & Brisbin 2009 |
| food_plot  |  6.0×     | 3.0×              | 1.2×   | Kolowski 2017 |
| water      |  3.0×     | 2.0×              | 2.0×   | Kolowski 2017 |
| trail      |  4.0×     | 3.0×              | 5.0×   | Kolowski 2017 |
| random     |  1.0×     | 1.0×              | 1.0×   | reference category |
| other      |  1.5×     | 1.2×              | 1.3×   | conservative midpoint |

This is the only sound correction when no random-placement cameras
exist in the deployment, which is typical for hunter-style camera
arrays. Trade-off: sensitive to inflation-factor accuracy. Default
factors are mid-range estimates; project-specific calibration tightens
them.

### Method 2 — Hájek IPW with empirical propensities (DIAGNOSTIC)

The textbook IPW estimator (Hájek 1971; Cassel-Särndal-Wretman 1976)
reweights the sample to a target placement-context distribution:

```
weighted_rate = Σ_i ( w_i · rate_i ) / Σ_i w_i
where w_i = q(context_i) / p(context_i)
```

`p` is the empirical propensity (proportion of cameras at each
context); `q` is the target marginal (default: uniform across contexts
present). Empirical IPW alone cannot correct bias when the entire
sample is biased — there is no unbiased anchor. It is reported as a
sanity-check companion to the literature-prior method, not fed into
REM.

### Diagnostics

For each survey period the pipeline reports Kish's effective sample
size, ESS = (Σw)² / Σ(w²) (Kish 1965), and the maximum-weight ratio
max(w) / mean(w). Caveats fire automatically when:

- ESS drops below `n / 2` (significant statistical-power loss from
  weighting).
- max-weight ratio exceeds 5× (one camera dominates the estimate;
  Cole & Hernán 2008 recommend stabilization or trimming).
- No random-placement cameras in the deployment (literature-prior
  factors carry the entire correction; cannot be cross-validated).

Each camera carries a `placement_context` value supplied by the
landowner at setup. Both the raw and bias-adjusted rates appear in the
dashboard and JSON API. REM density is derived from the adjusted rate;
the raw rate is reported alongside for transparency.

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

The record shape explicitly separates pipeline outputs from
supplementary modeled projections, so downstream importers cannot
accidentally treat the damage dollar figure as a pipeline output:

```json
{
  "species_key": "feral_hog",

  "pipeline": {
    "tier":                           "Elevated",
    "score_0_100":                    50.6,
    "density_animals_per_km2":        5.13,
    "density_ci_low":                 1.29,
    "density_ci_high":                16.64,
    "detection_rate_per_camera_day":           0.397,
    "detection_rate_adjusted_per_camera_day":  0.099,
    "recommendation":                          "recommend_supplementary_survey",
    "caveats": [
      "Cameras at non-random placements (feeder, trail) violate REM's
       movement-independence assumption. Inverse propensity weighting
       (Kolowski & Forrester 2017) corrects for residual bias but does
       not eliminate it."
    ],
    "method_notes": [
      "Daily travel distance: v = 6.0 km/day (sd 2.5). Source: Kay et al. 2017."
    ]
  },

  "supplementary_projection": {
    "label":                     "MODELED PROJECTION",
    "source":                    "Anderson et al. 2016; APHIS Wildlife Services annual Program Data Reports",
    "annual_damage_usd":         25561,
    "annual_damage_ci_low_usd":   6421,
    "annual_damage_ci_high_usd": 82980,
    "crop_modifier":             1.30,
    "per_hog_annual_usd":        405,
    "disclaimer": "Not a pipeline output. Derived from third-party loss
                   data (Anderson et al. 2016 per-hog damage figures
                   × parcel area × crop modifier). Intended as context
                   for loan-review committees that have not yet built
                   their own damage model; a committee with an internal
                   model should consume the pipeline outputs above
                   instead."
  }
}
```

The parallel under `stats` also includes `n_cameras`, `total_camera_days`, and `total_detections` at the property-level summary.

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
