"""Demo routes — interactive demo for prospective enterprise clients.

GET  /demo     — Demo page with parcel info and "Run Assessment" button
POST /demo/run — Triggers the full insurer pipeline on demo data, returns JSON
GET  /demo/download-pdf — Serve the generated enterprise PDF
"""

import logging
import os
import time

from flask import Blueprint, jsonify, render_template, send_file


logger = logging.getLogger(__name__)

demo_bp = Blueprint("demo", __name__, url_prefix="/demo")

# Store last generated assessment and PDF path
_last_assessment = {}
_last_pdf_path = None


@demo_bp.route("")
def demo_page():
    """Interactive demo page for the insurer pipeline."""
    return render_template("demo.html")


@demo_bp.route("/run", methods=["POST"])
def run_assessment():
    """Run the full insurer pipeline on demo data.

    Returns JSON with the risk assessment summary, PDF download link,
    and processing time.
    """
    global _last_assessment, _last_pdf_path

    start = time.time()

    try:
        # Run risk synthesis (includes upstream pipeline)
        from risk.synthesis import run_risk_assessment
        assessment = run_risk_assessment(
            parcel_id="TX-KIM-2024-04817",
            acreage=2340,
            county="Kimble",
            state="TX",
            demo=True,
        )

        if "error" in assessment:
            return jsonify({"error": assessment["error"]}), 500

        # Generate enterprise PDF
        from report.generator import generate_report
        from strecker.ingest import ingest
        from strecker.classify import classify

        detections = None
        try:
            photos = ingest(demo=True)
            detections = classify(photos, demo=True)
        except Exception:
            # Detection generation is best-effort here — the PDF
            # renderer falls back to placeholder figures when None.
            # Still surface the failure so a real regression doesn't
            # hide behind a silent fallback.
            logger.exception("demo ingest+classify failed; PDF will use fallback")

        pdf_path = generate_report(
            assessment=assessment,
            detections=detections,
        )

        elapsed = time.time() - start

        # Store for download
        _last_assessment = assessment
        _last_pdf_path = pdf_path

        # Build response
        pdf_size_kb = (os.path.getsize(pdf_path) / 1024
                       if os.path.exists(pdf_path) else 0)

        response = dict(assessment)
        response["pdf_path"] = pdf_path
        response["pdf_size_kb"] = f"{pdf_size_kb:.0f}"
        response["processing_time_sec"] = round(elapsed, 1)

        return jsonify(response)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@demo_bp.route("/download-pdf")
def download_pdf():
    """Serve the last generated enterprise PDF."""
    if _last_pdf_path and os.path.exists(_last_pdf_path):
        return send_file(
            _last_pdf_path,
            as_attachment=True,
            download_name="nature_exposure_TX-KIM-2024-04817.pdf",
        )
    return "No PDF generated yet. Run the assessment first.", 404
