# ⚠️ SYNTHETIC DEMO DATA — NOT A REAL RANCH

Everything in this directory is **fabricated data** used for product
demonstration, automated tests, and visual mockups. It is NOT:

- A real ranch or parcel
- Real trail-camera photographs
- The output of a real landowner submission
- Production customer data
- Representative of the statistical performance of the production
  pipeline on real photos

### What's in here

| File / dir | What it is |
|---|---|
| `demo_data/cameras.json` | Fabricated camera-station metadata (six cameras in a hypothetical "Edwards Plateau Ranch" layout) |
| `demo_data/detections.json` | Pre-generated detections matching the fabricated cameras — used by `DEMO_MODE=1` to populate the dashboard without running the ML pipeline |
| `demo_data/parcel.geojson` | Fabricated parcel-boundary polygon |
| `generate_demo_data.py` | The generator that produces all of the above deterministically from a fixed random seed |
| `seed/` | One-shot scripts that insert the fabricated data into a local Postgres for demo mode |
| `output/` | Where the demo pipeline writes sorted photos + reports during a demo run |

### Why it exists

Three reasons:

1. **Offline demos.** A potential lender / reinsurer / YC partner can
   clone the repo and see the end-to-end product behavior without
   needing real SD cards, GPU workers, or live customer data.
2. **Test fixtures.** A deterministic dataset lets the pipeline test
   suite assert specific expected outputs against a known input.
3. **Visual mockup.** The Basal editorial landing page and the
   sample Nature Exposure Report PDF at
   `web/static/sample/nature_exposure_sample.pdf` use this data to
   show what a real report looks like structurally — without
   exposing any actual customer parcel.

### Production data

Actual Farm Credit pilot parcels, actual hunter uploads through
Strecker, and actual density estimates live in the production
Postgres and Spaces bucket, not in this repository.

### If you reference demo output anywhere

Please carry the "synthetic — demo only" label forward. We never
present fabricated ranch data as real in pitches, reports, or press.
The sample Nature Exposure Report PDF, for example, is watermarked
accordingly in its cover page.
