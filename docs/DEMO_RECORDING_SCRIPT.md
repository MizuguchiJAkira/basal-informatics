# YC Demo — Recording Script

**Target:** 90-second MP4, 1080p minimum, recorded via QuickTime or Loom.
**Audience:** YC partners.
**Purpose:** pitch-grade fallback if the live demo fails on the day.

Pair with `DEMO_NARRATIVE.md` for the voiceover text.

---

## Pre-flight (2 minutes before you hit record)

1. **Warm the site.** Open https://basal.eco/lender/fcct/ in Chrome. If
   DNS isn't live yet, use https://monkfish-app-ju2lv.ondigitalocean.app/lender/fcct/.
   This pre-warms gunicorn; cold-start adds ~15s and will be visible in
   the recording if you skip this.
2. **Log in.** `jonahakiracheng@gmail.com` / `PilotSmoke-d4e5ab` (change
   before publishing publicly).
3. **Close all other tabs** in the recording window. Hide bookmarks bar.
4. **Browser zoom = 100%.** Cmd+0 to reset.
5. **macOS:** notifications off (Control Center → Focus → Do Not Disturb).
6. **Recording app:** QuickTime "New Screen Recording", use the selection
   rectangle around the browser window only (exclude dock, menu bar, tab
   strip). Or Loom with "Current Tab" mode.
7. **Cursor highlighting:** Loom has it built in. QuickTime doesn't —
   either add `Mouseposé` (free, macOS App Store) or accept bare cursor.
8. **Microphone:** internal mic is fine for a rehearsal; use AirPods or a
   USB mic for the publish take. Speaker off to avoid feedback.

## The shoot

**Target length:** 85–95 seconds. Cut ruthlessly in post if you overshoot.

### Beat 1 — Pain (0:00 – 0:12)

*You are on* `/lender/fcct/` (the portfolio page).

Script:
> "Farm Credit and ag banks hold hundreds of billions in loans secured
> by productive farmland. Today their ecological due diligence is a
> forty-thousand-dollar one-shot field survey that's stale the day it
> lands."

Cursor behavior: don't click. Keep cursor roughly center-of-screen.

### Beat 2 — Product (0:12 – 0:48)

*Still on* `/lender/fcct/`.

Script:
> "This is Farm Credit of Central Texas' Basal portfolio. Five parcels
> under assessment."

Action at 0:18: Hover the cursor over the tier-tally chips (`1 Severe
· 1 Elevated · 1 Moderate · 1 Low`), pause for 1 second. Do NOT click.
Then briefly drift right across the `Hog rate (events/cam-day)` column
— this is the pipeline-native relative abundance index; have the cursor
read that column top-to-bottom so the viewer sees 1.526 → 0.914 → 0.345
→ 0.043 scaling with tier.

Script continues:
> "The data comes from trail cameras the landowner uploaded directly,
> because Farm Credit told them their loan renewal depends on a current
> ecological assessment."

Action at 0:26: click the `TX-BRA-2026-00008` link (Riverbend Farm,
Severe tier). Page transitions to the parcel report.

**Wait 0.5 sec** for layout to settle.

Script:
> "Feral Hog Exposure Score: eighty-three point seven out of one hundred
> — Severe tier."

Action at 0:34: cursor hovers the density + detection-frequency lines
under the score, then pauses one second on the *Bias-adjusted rate*
line specifically (the second line below the density).

Script:
> "Raw detection frequency is one point five three independent events
> per camera-day; the bias-adjusted rate, after inverse propensity
> weighting against the random-placement reference cameras on this
> parcel, is one point zero four. Scaled through the Random Encounter
> Model that's thirteen point five animals per square kilometer,
> ninety-five percent confidence interval three point six to thirty-
> four."

Action at 0:40: cursor scrolls past the density block and pauses on
the "Modeled projection · Annual crop-damage estimate (supplementary)"
block. The MODELED PROJECTION badge + the "Not a pipeline output" +
"third-party loss data" disclaimer need to be on camera for ~1.5 sec.

Script:
> "A modeled damage projection of twenty-three thousand dollars is
> attached as supplementary context — derived from third-party loss
> data, not a pipeline output. The committee has the rate and the
> density; the dollar estimate is theirs to consume or replace with
> their own damage model."

### Beat 3 — Wedge (0:48 – 1:18)

Script:
> "The methodology is publicly defensible. Detection rate is raw and
> assumption-minimal. We correct for camera-placement bias with
> inverse propensity weighting against literature priors from
> Kolowski 2017 and a random-placement reference camera on every
> parcel — that's what an external auditor checks first. Density
> derives from the bias-adjusted rate via the Random Encounter Model
> from Rowcliffe 2008, bootstrap ninety-five percent CI over cameras.
> Tier cutoffs from Mayer and Brisbin 2009. The dollar projection is
> a separate, supplementary scaling from Anderson 2016 per-hog
> damage figures — clearly labeled as third-party loss data, not
> pipeline output."

Action at 0:55: scroll down to the methodology footer (bottom of the
page). Pause 1 second so the reference list is legible.

Script:
> "Farm Credit pays us fifteen hundred dollars per parcel-verification,
> or five thousand a month for unlimited. The alternative is forty
> thousand dollars for a field survey that's stale in six months.
> We're twenty-five times cheaper and continuous instead of point-in-
> time."

### Beat 4 — Moat (1:18 – 1:30)

Action at 1:18: scroll back UP the parcel report to the "Survey trend
(continuous monitoring)" widget. Pause one second so the Fall 2025 →
Spring 2026 chips and the "Elevated → Severe" delta line are on camera.

Script:
> "Riverbend was Elevated tier in Fall 2025 — five point six animals
> per square kilometer. Spring 2026 it's Severe at thirteen point five.
> That trajectory — Elevated to Severe in five months — is what the
> lender sees that no point-in-time field survey would have caught.
> The same audit-traceable record slots into the TNFD nature-risk
> ontology reinsurers are adopting. Primary-source ecological data
> nobody else in this stack has."

Action at 1:26: click back to the portfolio (top-left arrow) to end on
a wide shot of the five parcels, tier diversity, the Farm Credit
client name in the header.

Script (the close):
> "We're raising one and a half million to close the first three Farm
> Credit pilots in Texas and Georgia and hire a PhD ecologist to own
> the methodology defensibility."

*Fade to end card.* Optional: "Strecker & Basal Informatics · basal.eco"

## Post

- Trim head/tail dead space in QuickTime (Edit → Trim) or iMovie.
- Loud-normalize audio if using external mic.
- Export at H.264 / 1080p30, target < 20 MB.
- Upload to Loom/Vimeo/private-unlisted-YouTube — whichever is embeddable
  in your YC deck or the post-pitch follow-up email.

## Known gotchas

- **Cold-start:** if you skipped the warmup, the first page load can take
  10–15 seconds. Watch the first frame of the recording and cut anything
  longer than 0.3s of blank tab.
- **Scroll jitter:** Chrome's smooth-scroll can look janky at 30fps.
  Test with Loom (60fps) if you have access.
- **Number edits:** if the headline number drifts (e.g. a fresh re-seed
  changes density), re-record Beat 2 rather than narrating over stale
  numbers.
