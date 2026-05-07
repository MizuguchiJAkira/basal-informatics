"""Stage 7 — Texas wildlife valuation risk module.

Texas-only. Edwards Plateau and Post Oak Savannah counties first.

Sub-packages:

    reference/   Static datasets parsed from the Texas Comptroller's
                 Manual for the Appraisal of Agricultural Land and the
                 TPWD Comprehensive Wildlife Management Planning
                 Guidelines. Hand-curated YAML, not LLM-generated.

    adapters/    Per-county CAD adapters returning hardcoded snapshots
                 for v1. Plug-in pattern: ``adapters.cad.get(slug)``.

Top-level surface:

    compute(parcel, *, as_of_date=None) -> ValuationRiskResult
        Orchestrates CAD lookup, scoring, exposure, remediation; writes
        ``parcel_valuation_status`` and ``valuation_risk_factors`` rows.
        Returns the same dict shape that the JSON contract documents.

The compute() entry point is the only thing the lender route wires up.
Internals (scoring, exposure, remediation) are independently importable
and unit-testable.
"""
