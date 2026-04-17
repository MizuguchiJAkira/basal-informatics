# YC Demo — Narrative & Script

**Audience:** YC partners.
**Length budget:** 90 seconds spoken · ~225 words. Plus 30s of optional Q&A buffer.

**Demo URL:** <https://monkfish-app-ju2lv.ondigitalocean.app/lender/fcct/>
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

*[Click into TX-BRA-2026-00002 — Riverbend Farm. Big headline:
"Feral Hog Exposure Score: 91.5 / 100 — Severe". 0–100 bar,
gradient from green to red, filled to the upper right.]*

> Feral Hog Exposure Score: 91.5 out of 100 — Severe.
> 16.6 animals per square kilometer, 95% confidence interval 10.7 to 33.8.
> Modeled annual damage: $28,000 on a 650-acre corn parcel —
> that's the loan review committee's number, clearly labeled a modeled
> projection, not a pipeline output.

### Beat 3 — The wedge (~30s)

*[Scroll to the caveats + recommendation block. Click the "Methodology" link in the footer.]*

> The methodology is publicly defensible. Random Encounter Model
> from Rowcliffe 2008. Bootstrap 95% CI over cameras. Tier cutoffs
> from Mayer and Brisbin 2009. Dollar projections scaled from
> Anderson 2016 per-hog damage figures times a crop-specific modifier.
> Every number has a method note.
>
> Farm Credit pays us $1,500 per parcel-verification, or $5,000 a
> month for unlimited. The alternative is $40,000 for a field survey
> that's stale in six months. We're 25x cheaper and continuous
> instead of point-in-time.

### Beat 4 — The moat (~15s)

> The report is audit-traceable at camera-day granularity, and the
> same output slots into the TNFD nature-risk ontology that reinsurers
> are adopting. That's the primary-source ecological dataset nobody
> else in this stack has.

*[Close the laptop.]*

> We're raising $1.5M to close the first three Farm Credit pilots in
> Texas and Georgia and to hire a PhD ecologist to own the
> methodology defensibility going forward.

---

## What the dashboard renders today (talking points)

| Parcel                    | Crop      | Acreage | Tier      | Density (/km²) | Damage/yr | Notes |
|---------------------------|-----------|--------:|-----------|---------------:|----------:|-------|
| TX-BRA-2026-00002 Riverbend Farm      | corn      | 650   | Severe    | 16.61          | $28,306   | Small corn parcel, heavy hog pressure. Headline case. |
| TX-KIM-2026-00001 Edwards Plateau Ranch | sorghum  | 2,340 | Elevated  | 5.13           | $25,561   | Mid-size parcel at the decision boundary. |
| TX-GIL-2026-00004 Oak Ridge Orchards | peanut    | 180   | Moderate  | 3.34           | $1,381    | Demonstrates crop-modifier sensitivity (peanut 1.4×). |
| TX-REA-2026-00003 Highland Meadow Ranch | pasture | 4,800 | Low       | 0.56           | $2,192    | Big parcel, low density, low damage — "the healthy case." |
| TX-MEN-2026-00005 Prairie Creek Property | rangeland | 3,200 | Pending  | —              | —         | Just onboarded; demonstrates "survey in progress" state. |

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

- `docs/METHODOLOGY.md` — one-pager for the actuary/ecologist question
- `docs/ROADMAP.md` — in case a partner asks "what do you build in week one post-funding"
- The JSON API response for Riverbend Farm at
  `/lender/api/fcct/parcel/2/exposure` — the compliance-ready format
  that imports into the lender's internal underwriting system.
