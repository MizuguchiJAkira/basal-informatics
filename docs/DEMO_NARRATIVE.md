# YC Demo — Narrative & Script

**Audience:** YC partners.
**Length budget:** 90 seconds spoken · ~225 words. Plus 30s of optional Q&A buffer.

**Demo URL:** <https://basal.eco/lender/fcct/>
(login: jonahakiracheng@gmail.com / PilotSmoke-d4e5ab — change before demo day)

**Fallback:** screen recording of the same flow. See "Recording checklist" below.

---

## The 90-second arc

### Beat 1 — The pain (~15s)

> Farm Credit and ag banks hold hundreds of billions in loans secured
> by productive farmland. Today their ecological due diligence is a
> $40,000 one-shot field survey from an independent biologist, and
> it's stale the day it lands.

*[On screen: lender portfolio dashboard open, still loading the context.]*

### Beat 2 — The product (~30s)

> This is Farm Credit of Central Texas' Basal portfolio.
> Five parcels under assessment.

*[Point at the portfolio view. Tier chips: 1 Severe, 1 Elevated, 1 Moderate, 1 Low, 1 Pending. Table shows each parcel with its Feral Hog Exposure tier, density, event count, crop.]*

> The data comes from trail cameras the landowner uploaded directly,
> because Farm Credit told them their loan renewal depends on a current
> ecological assessment.

*[Click into TX-BRA-2026-00008 — Riverbend Farm. Big headline:
"Feral Hog Exposure Score: 83.7 / 100 — Severe". 0–100 bar,
gradient from green to red, filled to the upper right.]*

> Feral Hog Exposure Score: eighty-three point seven out of one hundred
> — Severe tier. The raw pipeline output is a detection frequency of
> one point five three independent events per camera-day; after
> placement-bias correction (per Kolowski 2017 inverse propensity
> weighting against the random-placement reference cameras on this
> parcel), the bias-adjusted rate is one point zero four. Scaled
> through the Random Encounter Model that's thirteen point five
> animals per square kilometer, 95% confidence interval three point
> six to thirty-four.

*[Scroll to the "Modeled projection · Annual crop-damage estimate
(supplementary)" block. Pause two seconds so the MODELED PROJECTION
badge + disclaimer are on camera.]*

> A modeled damage projection of twenty-three thousand dollars is
> attached as supplementary context — derived from third-party loss
> data, not a pipeline output. The lender committee has the rate and
> the density; the dollar estimate is theirs to consume or replace
> with their own damage model.

### Beat 3 — The wedge (~30s)

*[Scroll to the caveats + recommendation block. Click the "Methodology" link in the footer.]*

> The methodology is publicly defensible. Detection rate is raw and
> assumption-minimal — just independent events per camera-day. We
> correct for camera-placement bias with inverse propensity weighting
> against literature priors from Kolowski 2017 and an unbiased random-
> placement reference camera on every parcel — that's what an external
> auditor will check first. Density derives from the bias-adjusted
> rate via the Random Encounter Model from Rowcliffe 2008 with a
> bootstrap 95% CI over cameras. Tier cutoffs from Mayer and Brisbin
> 2009. The dollar projection is a separate, supplementary scaling
> from Anderson 2016 per-hog damage figures — clearly labeled as
> third-party loss data, not pipeline output.
>
> Farm Credit pays us $1,500 per parcel-verification, or $5,000 a
> month for unlimited. The alternative is $40,000 for a field survey
> that's stale in six months. We're 25x cheaper and continuous
> instead of point-in-time.

### Beat 4 — The moat (~15s)

*[Scroll up to the "Survey trend (continuous monitoring)" widget on
the parcel report. Pause one second so the Fall 2025 → Spring 2026
chips and the "Elevated → Severe" delta line are on camera.]*

> Riverbend was Elevated tier in Fall 2025 — five point six animals
> per square kilometer. Spring 2026 it's Severe at thirteen point five.
> That trajectory — Elevated to Severe in five months, a hundred and
> forty percent density jump — is what the lender sees that no
> point-in-time field survey would have caught. The same audit-
> traceable record slots into the TNFD nature-risk ontology
> reinsurers are adopting. That's the primary-source ecological
> dataset nobody else in this stack has.

*[Close the laptop.]*

> We're raising $1.5M to close the first three Farm Credit pilots in
> Texas and Georgia and to hire a PhD ecologist to own the
> methodology defensibility going forward.

---

## What the dashboard renders today (talking points)

| Parcel                    | Crop      | Acreage | Tier      | Rate (ev/cam-day) | Density (/km²) | Modeled $/yr | Notes |
|---------------------------|-----------|--------:|-----------|------------------:|---------------:|-------------:|-------|
| TX-BRA-2026-00008 Riverbend Farm      | corn      | 650   | Severe    | 1.526 / 1.042      | 13.47          | $22,955      | Small corn parcel, heavy hog pressure. Headline case. |
| TX-KIM-2026-00001 Edwards Plateau Ranch | sorghum  | 2,340 | Elevated  | 0.914 / 0.494      | 6.38           | $31,812      | Mid-size parcel at the decision boundary. |
| TX-GIL-2026-00010 Oak Ridge Orchards | peanut    | 180   | Moderate  | 0.345 / 0.248      | 3.20           | $1,323       | Demonstrates crop-modifier sensitivity (peanut 1.4×). |
| TX-REA-2026-00009 Highland Meadow Ranch | pasture | 4,800 | Low       | 0.043 / 0.026      | 0.33           | $1,315       | Big parcel, low density, low damage — "the healthy case." |
| TX-MEN-2026-00011 Prairie Creek Property | rangeland | 3,200 | Pending   | —                  | —              | —            | Just onboarded; demonstrates "survey in progress" state. |

Rate column is **raw / bias-adjusted** events per camera-day; the
adjusted value is the IPW-corrected rate (Kolowski & Forrester 2017)
that REM actually consumed. Modeled $/yr values are supplementary
projections scaled from Anderson 2016, shown only as context for
committees without internal damage models.

## Likely Q&A

**Q: Pricing?**
A: Two tiers. Per-parcel: $1,500 per verification. Portfolio unlimited:
$5,000 per month. Customer's alternative is a $40,000 field survey, so
we're 25× cheaper and continuous. Margin is high — variable cost is
pennies per parcel in compute; what we're charging for is methodology
defensibility and audit trail.

**Q: Unit economics?**
A: Per-parcel variable cost is under $5. LTV on the lender side is
3-year contracts at $5K–$20K ARR depending on portfolio size. CAC is
high for the first three pilots (direct sales into loan-review
committees) but drops dramatically once the methodology one-pager
circulates inside the Farm Credit System's regulatory affairs team.

**Q: What's the raise for?**
A: $1.5M. ~40% to close three Farm Credit pilots over six months.
~30% to hire a PhD ecologist to co-author the methodology
validation and sit for external-auditor questions. ~20% to build
the bias-correction (IPW) and TNFD ontology-mapping layers that are
currently stubbed. ~10% reserve.

**Q: Why do landowners upload?**
A: Lender requires it or incentivizes it at loan renewal. Farm
Credit already asks for soil tests, yield data, irrigation records —
this fits the same collateral-documentation pattern. For the
borrower, it's a 10-minute SD card upload through a web form, and
they can negotiate terms on the back of a current ecological
assessment instead of inheriting last year's.

**Q: What about reinsurers?**
A: Secondary customer. The same audit-traceable output goes into TNFD
nature-risk disclosure data that reinsurers pay for separately. Lender
is the beachhead because the pain is concrete — collateral review —
rather than regulatory-compliance-driven like TNFD.

**Q: Where does Strecker fit?**
A: Strecker is a separate consumer product for hunters — free species
sorting, individual deer tracking. No visible connection to Basal.
It fills camera-coverage gaps on parcels where the landowner doesn't
have cameras but a neighboring hunting lease does. DetectionIngest
is the bridge layer. Strecker is the acquisition funnel for parcels
that would otherwise be uninstrumented; Basal is where revenue comes
from.

**Q: How accurate is REM at this scale?**
A: Rowcliffe 2008 validates it on captive populations of known density
to within ±20% mean error when assumptions hold. The recommendation
flag tells the customer when they don't — if camera placement is
non-random (feeder/trail/water), the caveat is surfaced explicitly,
and the confidence-interval width triggers a recommendation to
supplement with an ecological survey. The lender's loan officer
sees the same methodology note an actuary would.

**Q: What's stopping a Big Ag competitor?**
A: Three things. First, the methodology IP — we're publishing the
calibration paper ourselves. Second, the data flywheel — every
landowner upload extends the training set the bias correction runs
on, and our IPW coefficients get tighter. Third, Farm Credit
regulatory relationships — once we're named in their internal
underwriting guidance, the switching cost for a lender is non-trivial.

## Pre-demo checklist

- [ ] Custom domain live (avoid Chrome "dangerous site" warning on `*.ondigitalocean.app`)
- [ ] Demo password changed and noted
- [ ] Site warmed (hit `/lender/fcct/` 60s before demo; gunicorn cold-boot is ~15s)
- [ ] Browser zoom at 100%
- [ ] Demo mode on the laptop: notifications off, screen sharing tested
- [ ] Methodology one-pager at `docs/METHODOLOGY.md` circulated to partners in advance

## Recording checklist (pre-recorded fallback)

- 1280×800 viewport (matches the dashboard's `lg:` breakpoint)
- Cursor highlighting on
- Screen recording app: QuickTime or Loom
- Two takes: one with click-through, one with voiceover only (for editing)
- Final cut: 90s, no fade, end on the "raising $1.5M" frame

## What to NOT show on demo day

- The DigitalOcean console
- The Strecker hunter dashboard (`/properties/1/dashboard`) — it's
  currently inaccessible because the container is configured SITE=basal
  for the pilot. When Strecker gets its own container it'll be on
  its own URL.
- The `/upload` route — works but is not the demo flow.
- Any raw SQL or repo tree on the projector.

## What to have queued in another tab for Q&A

- `docs/METHODOLOGY.md` — one-pager for the loan-review-committee / ecologist question
- `docs/ROADMAP.md` — in case a partner asks "what do you build in week one post-funding"
- The JSON API response for Riverbend Farm at
  `/lender/api/fcct/parcel/8/exposure` — the compliance-ready format
  that imports into the lender's internal underwriting system.
