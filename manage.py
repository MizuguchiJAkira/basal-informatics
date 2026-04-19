#!/usr/bin/env python3
"""Basal Informatics CLI — entry point for all pipeline operations."""

import os
import sys

import click

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


@click.group()
def cli():
    """Basal Informatics pipeline management."""
    pass


# --- Database commands ---

@cli.group()
def db():
    """Database management commands."""
    pass


@db.command("init")
def db_init():
    """Initialize PostGIS schema."""
    from db.connection import get_connection, release_connection

    schema_path = os.path.join(os.path.dirname(__file__), "db", "schema.sql")
    with open(schema_path) as f:
        sql = f.read()

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        click.echo("Schema initialized successfully.")
    except Exception as e:
        conn.rollback()
        click.echo(f"Error initializing schema: {e}", err=True)
        sys.exit(1)
    finally:
        release_connection(conn)


@db.command("migrate")
@click.option("--status", is_flag=True,
              help="Show applied / pending migrations without applying.")
@click.option("--db-url", default=None,
              help="Database URL (overrides DATABASE_URL).")
def db_migrate(status, db_url):
    """Apply pending SQL migrations from db/migrations/.

    Wraps scripts/migrate.py — use this from the DO App Platform
    console (``python manage.py db migrate``) to evolve the prod
    schema for changes that db.create_all() can't handle
    (new columns on existing tables, etc.).
    """
    from scripts import migrate as _migrate

    rc = _migrate.run(db_url=db_url, status_only=status)
    sys.exit(rc)


@db.command("seed")
def db_seed():
    """Generate Edwards Plateau demo data and insert into PostGIS."""
    from demo.generate_demo_data import generate, seed_to_db

    click.echo("Generating demo data...")
    data = generate()

    click.echo("Inserting into database...")
    try:
        seed_to_db(data)
        click.echo("Database seeded successfully.")
    except Exception as e:
        click.echo(f"Database insertion failed: {e}", err=True)
        click.echo("Demo data files still written to demo/demo_data/.")
        click.echo("Start PostGIS with: docker-compose up -d db")


# --- Strecker commands ---

@cli.group()
def strecker():
    """Strecker photo processing pipeline."""
    pass


@strecker.command("process")
@click.option("--demo", is_flag=True, help="Use demo data instead of real images")
def strecker_process(demo):
    """Run full Strecker pipeline: ingest → classify → sort → report."""
    from strecker.ingest import ingest
    from strecker.classify import classify
    from strecker.sort import sort_detections
    from strecker.report import generate_report

    click.echo("=" * 60)
    click.echo("Strecker Pipeline" + (" [DEMO MODE]" if demo else ""))
    click.echo("=" * 60)

    # ── Step 1: Ingest ──
    click.echo("\n1. Ingesting detections...")
    detections = ingest(demo=demo)
    click.echo(f"   Loaded {len(detections):,} raw photo-level detections")

    n_bursts = len(set(d.burst_group_id for d in detections))
    n_events = len(set(d.independent_event_id for d in detections))
    click.echo(f"   Burst groups: {n_bursts:,}")
    click.echo(f"   Independent events: {n_events:,}")
    click.echo(f"   Photo:event ratio: {len(detections)/n_events:.2f}:1")

    # ── Step 2: Classify ──
    click.echo("\n2. Classifying (post-processing)...")
    detections = classify(detections, demo=demo)

    n_review = sum(1 for d in detections if d.review_required)
    click.echo(f"   Temperature scaling: T={1.08}")
    click.echo(f"   Temporal priors applied")
    click.echo(f"   Review flagged: {n_review:,} ({n_review/len(detections)*100:.1f}%)")

    # Per-species summary
    species_stats = {}
    for d in detections:
        sp = d.species_key
        if sp not in species_stats:
            species_stats[sp] = {"photos": 0, "events": set(),
                                 "cameras": set(), "conf_sum": 0.0,
                                 "cal_sum": 0.0, "review": 0}
        species_stats[sp]["photos"] += 1
        species_stats[sp]["events"].add(d.independent_event_id)
        species_stats[sp]["cameras"].add(d.camera_id)
        species_stats[sp]["conf_sum"] += d.confidence
        species_stats[sp]["cal_sum"] += d.confidence_calibrated
        if d.review_required:
            species_stats[sp]["review"] += 1

    click.echo(f"\n{'Species':<25s} {'Photos':>7s} {'Events':>7s} "
               f"{'Cams':>5s} {'Raw':>6s} {'Cal':>6s} {'Review':>7s}")
    click.echo("-" * 70)
    for sp in sorted(species_stats, key=lambda s: -species_stats[s]["photos"]):
        st = species_stats[sp]
        n = st["photos"]
        ne = len(st["events"])
        nc = len(st["cameras"])
        raw_mean = st["conf_sum"] / n
        cal_mean = st["cal_sum"] / n
        click.echo(f"  {sp:<23s} {n:>7,d} {ne:>7,d} {nc:>5d} "
                   f"{raw_mean:>6.3f} {cal_mean:>6.3f} {st['review']:>7,d}")

    # ── Step 3: Sort ──
    click.echo("\n3. Sorting photos into species folders...")
    sort_dir = "demo/output/sorted" if demo else "output/sorted"
    manifest_path = sort_detections(detections, output_dir=sort_dir, demo=demo)
    n_species = len(set(d.species_key for d in detections))
    click.echo(f"   {n_species} species folders created")
    click.echo(f"   Manifest: {manifest_path}")

    # ── Step 4: Report ──
    click.echo("\n4. Generating Game Inventory Report PDF...")
    pdf_path = "demo/output/game_inventory_report.pdf" if demo else "output/game_inventory_report.pdf"
    output_pdf = generate_report(
        detections, output_path=pdf_path,
        property_name="Edwards Plateau Ranch", demo=demo)
    click.echo(f"   PDF: {output_pdf}")

    # ── Step 5: Seed feedback system ──
    if demo:
        import json
        from strecker.feedback import (
            seed_demo_detections, seed_demo_corrections,
            get_regional_accuracy, get_review_queue, reset_demo_db,
        )

        click.echo("\n5. Seeding feedback system...")
        reset_demo_db()  # Fresh state each run

        cam_path = os.path.join(os.path.dirname(__file__),
                                "demo", "demo_data", "cameras.json")
        with open(cam_path) as f:
            cameras_json = json.load(f)

        seed_demo_detections(detections, cameras_json)
        n_corrections = seed_demo_corrections()
        click.echo(f"   {n_corrections} demo corrections seeded")

        # Show review queue summary
        queue = get_review_queue(limit=5)
        click.echo(f"   Review queue: {len(get_review_queue(limit=1000))} "
                   f"detections awaiting review")
        if queue:
            click.echo(f"   Top uncertainty: {queue[0]['predicted_species']} "
                       f"(entropy={queue[0]['softmax_entropy']}, "
                       f"conf={queue[0]['calibrated_confidence']})")

        # Show regional accuracy
        hu_id = cameras_json[0].get("habitat_unit_id", "UNKNOWN")
        accuracy = get_regional_accuracy(hu_id)
        if accuracy:
            click.echo(f"\n   Regional accuracy ({hu_id}):")
            for sp_acc in sorted(accuracy,
                                 key=lambda x: -(x["total_predictions"] or 0)):
                click.echo(
                    f"     {sp_acc['common_name']:<25s} "
                    f"{sp_acc['accuracy_pct']:>5.1f}%  "
                    f"({sp_acc['total_corrections']} corrections / "
                    f"{sp_acc['total_predictions']} predictions)  "
                    f"[{sp_acc['validation_status']}]")

    click.echo(f"\nPipeline complete. {len(detections):,} detections processed.")


@strecker.command("ingest")
@click.option("--demo", is_flag=True, help="Use demo data")
def strecker_ingest(demo):
    """Ingest trail camera photos (step 1 only)."""
    from strecker.ingest import ingest
    detections = ingest(demo=demo)
    n_bursts = len(set(d.burst_group_id for d in detections))
    n_events = len(set(d.independent_event_id for d in detections))
    click.echo(f"Ingested {len(detections):,} detections → "
               f"{n_bursts:,} bursts → {n_events:,} events")


@strecker.command("classify")
def strecker_classify():
    """Run species classification on ingested photos."""
    click.echo("strecker classify: not yet implemented (use 'strecker process --demo')")


@strecker.command("sort")
@click.option("--demo", is_flag=True, help="Use demo data")
def strecker_sort(demo):
    """Sort classified photos for hunter delivery."""
    from strecker.ingest import ingest
    from strecker.classify import classify
    from strecker.sort import sort_detections

    detections = ingest(demo=demo)
    detections = classify(detections, demo=demo)
    sort_dir = "demo/output/sorted" if demo else "output/sorted"
    manifest = sort_detections(detections, output_dir=sort_dir, demo=demo)
    click.echo(f"Sorted {len(detections):,} photos → {manifest}")


# --- Habitat commands ---

@cli.group()
def habitat():
    """Habitat delineation and unit modeling."""
    pass


@habitat.command("fingerprint")
@click.option("--demo", is_flag=True, help="Use demo data")
def habitat_fingerprint(demo):
    """Generate habitat fingerprints for camera stations."""
    from habitat.fingerprint import fingerprint_cameras
    fps = fingerprint_cameras(demo=demo)
    click.echo(f"Fingerprinted {len(fps)} camera stations")
    for fp in fps:
        click.echo(f"  {fp['camera_id']:8s} → {fp['nlcd_class']} "
                   f"({fp['ecoregion_iv_name']}, HUC {fp['huc10']})")


@habitat.command("analyze")
@click.option("--demo", is_flag=True, help="Use demo data")
def habitat_analyze(demo):
    """Run full habitat analysis: fingerprint → units → corridors → confidence → gaps."""
    from habitat.store import reset_db
    from habitat.fingerprint import fingerprint_cameras
    from habitat.units import delineate_units
    from habitat.corridors import generate_corridors
    from habitat.confidence import compute_confidence
    from habitat.gaps import analyze_gaps, get_top_gaps
    from strecker.ingest import ingest
    from strecker.classify import classify

    click.echo("=" * 60)
    click.echo("Habitat Analysis Pipeline" + (" [DEMO MODE]" if demo else ""))
    click.echo("=" * 60)

    reset_db()

    # Step 1: Fingerprint
    click.echo("\n1. Fingerprinting cameras...")
    fps = fingerprint_cameras(demo=demo)
    click.echo(f"   {len(fps)} cameras fingerprinted")

    # Step 2: Delineate units
    click.echo("\n2. Delineating habitat units...")
    units = delineate_units(demo=demo)
    for u in units:
        click.echo(f"   {u['id']}: {u['nlcd_class']} — "
                   f"{u['camera_count']} cameras, "
                   f"{u['total_camera_nights']:,} camera-nights, "
                   f"{u['monitoring_months']} months")

    # Step 3: Generate corridors
    click.echo("\n3. Generating corridors...")
    corridors = generate_corridors(demo=demo)
    from collections import Counter
    type_counts = Counter(c["corridor_type"] for c in corridors)
    total_km = sum(c["length_km"] for c in corridors)
    click.echo(f"   {len(corridors)} corridor segments, "
               f"{total_km:.1f} km total")
    for ctype, n in sorted(type_counts.items()):
        type_km = sum(c["length_km"] for c in corridors
                      if c["corridor_type"] == ctype)
        click.echo(f"     {ctype:<25s} {n:>2d} segments, {type_km:.2f} km")

    # Step 4: Compute confidence (needs detections)
    click.echo("\n4. Computing species confidence...")
    if demo:
        detections = ingest(demo=True)
        detections = classify(detections, demo=True)
    else:
        detections = None
    confidence = compute_confidence(detections=detections, demo=demo)
    click.echo(f"   {len(confidence)} species × habitat unit scores")

    # Display per-unit
    hu_groups = {}
    for c in confidence:
        hu_groups.setdefault(c["habitat_unit_id"], []).append(c)

    for hu_id in sorted(hu_groups):
        click.echo(f"\n   {hu_id}:")
        click.echo(f"   {'Species':<25s} {'Events':>6s} {'Cams':>5s} "
                   f"{'Corr%':>6s} {'Temp':>5s} {'Det':>5s} "
                   f"{'Conf%':>6s} {'Grade':>5s}")
        click.echo("   " + "-" * 65)
        for c in sorted(hu_groups[hu_id],
                        key=lambda x: -x["overall_confidence_pct"]):
            click.echo(
                f"   {c['common_name']:<25s} "
                f"{c['total_detections']:>6d} "
                f"{c['cameras_detected']:>3d}/{c['cameras_total']:<1d} "
                f"{c['corridor_coverage_pct']:>5.1f}% "
                f"{c['temporal_modifier']:>5.2f} "
                f"{c['detection_freq_modifier']:>5.2f} "
                f"{c['overall_confidence_pct']:>5.1f}% "
                f"{c['confidence_grade']:>5s}")

    # Step 5: Gap analysis
    click.echo("\n5. Analyzing monitoring gaps...")
    gaps = analyze_gaps(demo=demo)
    click.echo(f"   {len(gaps)} gaps > {200}m identified")
    top_gaps = get_top_gaps(limit=5)
    if top_gaps:
        click.echo("\n   Top gaps by projected confidence increase:")
        for g in top_gaps:
            ref = {}
            from config.species_reference import SPECIES_REFERENCE
            ref = SPECIES_REFERENCE.get(g["species_most_affected"], {})
            common = ref.get("common_name", g["species_most_affected"])
            click.echo(
                f"     {g['corridor_type']:<25s} "
                f"{g['gap_length_m']:>6.0f}m  "
                f"affects {common:<25s} "
                f"+{g['projected_confidence_increase_pct']:.1f}% conf  "
                f"({g['cameras_needed']} cameras needed)")

    click.echo(f"\nHabitat analysis complete.")


@habitat.command("units")
@click.option("--demo", is_flag=True, help="Use demo data")
def habitat_units(demo):
    """Delineate habitat units from fingerprints."""
    from habitat.fingerprint import fingerprint_cameras
    from habitat.units import delineate_units
    fingerprint_cameras(demo=demo)
    units = delineate_units(demo=demo)
    for u in units:
        click.echo(f"{u['id']}: {u['nlcd_class']} — "
                   f"{u['camera_count']} cameras")


@habitat.command("corridors")
@click.option("--demo", is_flag=True, help="Use demo data")
def habitat_corridors(demo):
    """Identify wildlife corridors."""
    from habitat.fingerprint import fingerprint_cameras
    from habitat.units import delineate_units
    from habitat.corridors import generate_corridors
    fingerprint_cameras(demo=demo)
    delineate_units(demo=demo)
    corridors = generate_corridors(demo=demo)
    click.echo(f"Generated {len(corridors)} corridor segments")


# --- Bias correction commands ---

@cli.group()
def bias():
    """Camera placement bias correction (IPW)."""
    pass


@bias.command("correct")
@click.option("--demo", is_flag=True, help="Use demo data")
def bias_correct(demo):
    """Run full bias correction pipeline on detection data."""
    from bias.ipw import run_bias_correction
    from config.species_reference import SPECIES_REFERENCE

    click.echo("=" * 60)
    click.echo("Bias Correction Pipeline" + (" [DEMO MODE]" if demo else ""))
    click.echo("=" * 60)

    # Load detections for species frequency computation
    detections = None
    if demo:
        from strecker.ingest import ingest
        from strecker.classify import classify
        detections = ingest(demo=True)
        detections = classify(detections, demo=True)

    click.echo("\n1. Building covariate matrix...")
    result = run_bias_correction(detections=detections, demo=demo)

    click.echo(f"   {result['n_cameras']} cameras vs "
               f"{result['n_reference_points']} reference points")
    click.echo(f"   Propensity model AUC: {result['propensity_model_auc']}")
    click.echo(f"   Bias correction applied: {result['bias_correction_applied']}")

    # Covariate comparison
    if "covariate_comparison" in result:
        click.echo("\n2. Covariate comparison (camera vs landscape):")
        for cov, stats in result["covariate_comparison"].items():
            arrow = "↓" if stats["ratio"] < 0.9 else ("↑" if stats["ratio"] > 1.1 else "≈")
            click.echo(f"   {cov:<25s} camera={stats['camera_mean']:>7.1f}  "
                       f"landscape={stats['landscape_mean']:>7.1f}  "
                       f"ratio={stats['ratio']:.2f} {arrow}")

    # Top predictors
    click.echo("\n3. Top placement predictors:")
    for pred in result["top_placement_predictors"][:5]:
        click.echo(f"   {pred['covariate']:<35s} "
                   f"coef={pred['coefficient']:>7.4f}  "
                   f"{pred['interpretation']}")

    # Per-species results
    click.echo(f"\n4. Species detection frequency (raw → adjusted):")
    click.echo(f"   {'Species':<25s} {'Raw%':>6s} {'Adj%':>6s} "
               f"{'Delta':>7s} {'Ratio':>6s} {'Cams':>5s}")
    click.echo("   " + "-" * 60)
    for sp_key in sorted(result["per_species"],
                         key=lambda s: -result["per_species"][s]["raw_detection_frequency_pct"]):
        sp = result["per_species"][sp_key]
        delta_str = f"{sp['delta_pct']:+.1f}"
        click.echo(
            f"   {sp['common_name']:<25s} "
            f"{sp['raw_detection_frequency_pct']:>5.1f}% "
            f"{sp['adjusted_detection_frequency_pct']:>5.1f}% "
            f"{delta_str:>7s} "
            f"{sp['adjustment_ratio']:>5.3f} "
            f"{sp['n_cameras_detected']:>3d}/{sp['n_cameras_total']}")

    # Camera weights
    if "camera_weights" in result:
        click.echo(f"\n5. Camera weights:")
        click.echo(f"   {'Camera':<10s} {'Context':<12s} {'Propensity':>10s} "
                   f"{'Weight':>8s}")
        click.echo("   " + "-" * 45)
        for cw in sorted(result["camera_weights"],
                         key=lambda x: -x["trimmed_weight"]):
            click.echo(
                f"   {cw['camera_id']:<10s} {cw['placement_context']:<12s} "
                f"{cw['propensity_score']:>10.4f} "
                f"{cw['trimmed_weight']:>8.4f}")

    click.echo("\nBias correction complete.")


# --- Risk commands ---

@cli.group()
def risk():
    """Risk synthesis engine."""
    pass


@risk.command("assess")
@click.option("--parcel-id", default="TX-KIM-2024-04817",
              help="Parcel identifier")
@click.option("--acreage", default=2340, type=float,
              help="Parcel acreage")
@click.option("--county", default="Kimble", help="County name")
@click.option("--state", default="TX", help="State abbreviation")
@click.option("--demo", is_flag=True, help="Use demo data")
def risk_assess(parcel_id, acreage, county, state, demo):
    """Run full risk assessment for a parcel."""
    import json as _json
    from risk.synthesis import run_risk_assessment

    click.echo("=" * 60)
    click.echo("Risk Synthesis Engine" + (" [DEMO MODE]" if demo else ""))
    click.echo("=" * 60)
    click.echo(f"\nParcel: {parcel_id}")
    click.echo(f"Acreage: {acreage:,.0f}  County: {county}  State: {state}")

    click.echo("\n1. Running upstream pipeline (Strecker + Habitat + Bias)...")
    assessment = run_risk_assessment(
        parcel_id=parcel_id, acreage=acreage,
        county=county, state=state, demo=demo)

    if "error" in assessment:
        click.echo(f"\nError: {assessment['error']}", err=True)
        sys.exit(1)

    click.echo(f"   Pipeline complete.")

    # ── Species inventory ──
    click.echo(f"\n2. Species Inventory ({len(assessment['species_inventory'])} species):")
    click.echo(f"   {'Species':<25s} {'Det%':>6s} {'Conf':>5s} {'Flag'}")
    click.echo("   " + "-" * 60)
    for sp in assessment["species_inventory"]:
        flag = sp.get("risk_flag") or ""
        click.echo(
            f"   {sp['common_name']:<25s} "
            f"{sp['detection_frequency_pct']:>5.1f}% "
            f"  {sp['confidence_grade']:<4s} "
            f"{flag}")

    # ── Damage projections ──
    click.echo(f"\n3. Damage Projections:")
    for sp_key, proj in assessment["damage_projections"].items():
        click.echo(f"\n   {proj['common_name']}:")
        click.echo(f"     Base rate:       ${proj['base_cost_per_acre']:.2f}/acre/yr")
        click.echo(f"     Ecoregion cal:   {proj['ecoregion_calibration_factor']:.2f}x")
        click.echo(f"     Freq scale:      {proj['frequency_scale']:.4f} "
                   f"(det freq {proj['detection_frequency_pct']:.1f}%)")
        click.echo(f"     Annual loss:     ${proj['estimated_annual_loss']:,.0f}")
        click.echo(f"     10-year NPV:     ${proj['ten_year_npv']:,.0f}")
        click.echo(f"     CI ({proj['confidence_grade']}, "
                   f"±{proj['confidence_interval_pct']:.0f}%): "
                   f"${proj['confidence_interval_low']:,.0f} — "
                   f"${proj['confidence_interval_high']:,.0f}")

    # ── Feral hog exposure score ──
    fh = assessment.get("feral_hog_exposure_score")
    if fh:
        click.echo(f"\n4. Feral Hog Exposure Score: {fh['score']}/100")
        click.echo(f"   Detection freq component:  {fh['detection_frequency_component']:.1f}")
        click.echo(f"   Recency component:         {fh['recency_component']:.1f}")
        click.echo(f"   Spatial extent component:  {fh['spatial_extent_component']:.1f}")
        click.echo(f"   {fh['interpretation']}")

    # ── Regulatory risk ──
    reg = assessment["regulatory_risk"]
    click.echo(f"\n5. Regulatory Risk:")
    click.echo(f"   ESA species present: {', '.join(reg['esa_species_present']) or 'None'}")
    click.echo(f"   Consultation required: {reg['consultation_required']}")
    if reg["species_details"]:
        for sd in reg["species_details"]:
            click.echo(f"   {sd['common_name']} ({sd['esa_status']}): "
                       f"~{sd['estimated_habitat_overlap_acres']:.0f} ac overlap, "
                       f"${sd['estimated_compliance_cost_low']:,.0f}–"
                       f"${sd['estimated_compliance_cost_high']:,.0f}")

    # ── Overall ──
    click.echo(f"\n6. Overall Risk Rating: {assessment['overall_risk_rating']}")

    # ── Data confidence ──
    dc = assessment["data_confidence"]
    click.echo(f"\n7. Data Confidence:")
    click.echo(f"   Overall grade:        {dc['overall_grade']}")
    click.echo(f"   Monitoring months:    {dc['monitoring_months']}")
    click.echo(f"   Camera density:       {dc['camera_density_per_km2']:.2f}/km²")
    if dc.get("top_data_gaps"):
        click.echo(f"   Top gaps:")
        for g in dc["top_data_gaps"]:
            click.echo(f"     {g['corridor_type']} in {g['habitat_unit_id']}: "
                       f"{g['gap_length_m']:.0f}m, "
                       f"needs {g['cameras_needed']} camera(s)")

    # ── Full JSON output ──
    click.echo(f"\n{'=' * 60}")
    click.echo("Full Assessment JSON:")
    click.echo("=" * 60)
    click.echo(_json.dumps(assessment, indent=2, default=str))


# --- Report commands ---

@cli.group()
def report():
    """Enterprise PDF report generation."""
    pass


@report.command("generate")
@click.option("--parcel-id", default="TX-KIM-2024-04817",
              help="Parcel identifier")
@click.option("--demo", is_flag=True, help="Use demo data")
@click.option("--output", default=None, help="Output PDF path")
def report_generate(parcel_id, demo, output):
    """Generate enterprise Nature Exposure Report PDF."""
    import json as _json
    from risk.synthesis import run_risk_assessment
    from report.generator import generate_report

    click.echo("=" * 60)
    click.echo("Enterprise PDF Report Generator"
               + (" [DEMO MODE]" if demo else ""))
    click.echo("=" * 60)

    click.echo(f"\n1. Running risk assessment for {parcel_id}...")
    assessment = run_risk_assessment(
        parcel_id=parcel_id, demo=demo)

    if "error" in assessment:
        click.echo(f"\nError: {assessment['error']}", err=True)
        sys.exit(1)

    # Get detections for temporal charts
    detections = None
    if demo:
        try:
            from strecker.ingest import ingest
            from strecker.classify import classify
            photos = ingest(demo=True)
            detections = classify(photos, demo=True)
            click.echo(f"   {len(detections)} detections for temporal charts.")
        except Exception as e:
            click.echo(f"   Warning: Could not load detections: {e}")

    click.echo(f"\n2. Generating PDF...")
    pdf_path = generate_report(
        assessment=assessment,
        output_path=output,
        detections=detections,
    )

    # File size
    import os as _os
    size_kb = _os.path.getsize(pdf_path) / 1024
    click.echo(f"\n   PDF generated: {pdf_path}")
    click.echo(f"   Size: {size_kb:.0f} KB")
    click.echo(f"\n   Overall risk: {assessment['overall_risk_rating']}")
    hog = assessment.get('damage_projections', {}).get('feral_hog', {})
    if hog:
        click.echo(f"   Feral hog annual loss: "
                   f"${hog['estimated_annual_loss']:,.0f}")
    click.echo(f"\nDone.")


# --- Demo commands ---

@cli.group()
def demo():
    """Demo data and pipeline runs."""
    pass


@demo.command("generate")
def demo_generate():
    """Generate demo data files (no database required)."""
    from demo.generate_demo_data import generate
    generate()
    click.echo("Demo data written to demo/demo_data/")


@demo.command("run")
def demo_run():
    """Run full end-to-end pipeline on demo data."""
    from demo.run_full_pipeline import run_full_pipeline
    run_full_pipeline()


# --- Web commands ---

@cli.group()
def web():
    """Web interface."""
    pass


@web.command("run")
@click.option("--demo", is_flag=True, help="Seed demo data before starting")
@click.option("--port", default=None, type=int,
              help="Port to run on (defaults to $PORT env var, else 5000)")
def web_run(demo, port):
    """Start Flask development server with feedback endpoints."""
    from web.app import create_app

    if port is None:
        port = int(os.environ.get("PORT", "5000"))

    if demo:
        # Run the full pipeline to seed the feedback database
        import json
        from strecker.ingest import ingest
        from strecker.classify import classify
        from strecker.feedback import (
            reset_demo_db, seed_demo_detections,
            seed_demo_corrections,
        )

        click.echo("Seeding demo data for web server...")
        reset_demo_db()
        detections = ingest(demo=True)
        detections = classify(detections, demo=True)

        cam_path = os.path.join(os.path.dirname(__file__),
                                "demo", "demo_data", "cameras.json")
        with open(cam_path) as f:
            cameras_json = json.load(f)

        seed_demo_detections(detections, cameras_json)
        n = seed_demo_corrections()
        click.echo(f"Seeded {len(detections):,} detections + {n} corrections")

    app = create_app(demo=demo)
    click.echo(f"Starting Flask on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)


if __name__ == "__main__":
    cli()
