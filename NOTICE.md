# Pre-public-flip checklist

**Status: NOT YET PUBLIC. The list below must be cleared before the
repository is flipped from private to public.**

## Demo data / IP

- [x] **TNDeer trail-cam photo overlay reverted (2026-05-10).**
  `demo/seed/install_tndeer_photos.py` overlays the species directories
  under `demo/output/sorted/` with TNDeer-licensed JPEGs. On 2026-05-10
  the 321 locally-overlaid photos were reverted with
  `git checkout HEAD -- demo/output/sorted/`, restoring the tracked
  state: 308 zero-byte placeholder files plus 13 owned curated photos
  that pre-date the overlay. The placeholder files are rendered at
  request time by `web/app.py:serve_photo`, which generates a
  synthetic IR-night-vision image with species name, camera stamp,
  and simulated temperature. No third-party imagery ships in the
  public repo. To re-run the TNDeer overlay locally for in-house
  demos, the install script remains in `demo/seed/`; **do not
  commit its output.**

- [ ] **Demo lender name is a placeholder.** The portfolio renders
  "Acme Agricultural Credit" (slug `acme`) — a fictional placeholder.
  Original name was scrubbed pre-public; the seed file
  (`demo/seed/seed_lender_portfolio.py`) carries an inline comment
  confirming this. Real lender names are introduced only inside
  signed pilot agreements; never commit one to this repo.

- [ ] **Demo parcels are clearly synthetic.** Three parcels ship in
  the demo: Edwards Plateau Ranch (Kimble Co.), Riverbend Farm
  (Brazos Co.), Llano Highlands (Llano Co.). All three are
  fictional. Coordinates are deliberately positioned in remote
  uninhabited ranchland — they do not overlap real CAD records,
  airports, or named ranches. CAD snapshots in
  `valuation/adapters/cad/<county>_tx.py` are hand-curated and
  marked accordingly.

## Credentials / secrets

- [x] **No API keys, tokens, or secrets in git history.** Audited
  via targeted `git log -p` scan against text-only files for
  AWS/GitHub/Slack/Anthropic/SSH key patterns. Result: clean.
  Settings module reads everything from environment variables.

- [x] **Demo password literals (`owner123`, `demo123`) only seed
  under `DEMO_MODE=True`.** Production deploys set
  `DEMO_MODE=False` (see `wsgi.py`); the seed branch never fires.
  The strings are visible in `web/app.py` and that's acceptable —
  anyone running the demo benefits from knowing the credentials.

## License

- [x] **`LICENSE` file present.** "All rights reserved" with an
  inline note that public visibility is for lender-pilot
  auditability, not a usage grant. See `LICENSE` for details.
