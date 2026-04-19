"""Methodology appendix — bound into every parcel report.

A loan-review committee or external reviewer flips here to confirm the
finding is defensible. The page mirrors docs/METHODOLOGY.md but
compressed for a two-page PDF spread:

  Page 1 — What we measure, REM density, placement-bias correction
  Page 2 — Confidence intervals, recommendation logic, limitations,
           references.

Cites: Rowcliffe 2008, Mayer & Brisbin 2009, Kolowski & Forrester 2017,
Cassel-Sarndal-Wretman 1976, Hájek 1971, Cole & Hernán 2008,
Kish 1965, Anderson 2016, Kay 2017, Webb 2010.
"""

from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    CondPageBreak, Paragraph, Spacer, Table, TableStyle,
)

from report.styles import (
    CONTENT_WIDTH, STYLE_H2, STYLE_BODY, STYLE_CITATION, section_bar,
)

# ── Compact local styles ──
_H2_TIGHT = ParagraphStyle(
    "H2Methodology", parent=STYLE_H2,
    fontSize=12, leading=15, spaceBefore=9, spaceAfter=3,
)

_BODY_TIGHT = ParagraphStyle(
    "BodyMethodology", parent=STYLE_BODY,
    fontSize=9, leading=13, spaceAfter=4,
)

_BODY_MONO = ParagraphStyle(
    "BodyMethodologyMono", parent=_BODY_TIGHT,
    fontName="Courier", fontSize=9, leading=12,
    leftIndent=14, spaceAfter=6,
)

_CITATION_TIGHT = ParagraphStyle(
    "CitationTight", parent=STYLE_CITATION,
    fontSize=7.5, leading=10,
    leftIndent=10, firstLineIndent=-10,
    spaceAfter=5,
)


def _factor_table() -> Table:
    """Per-species placement-context inflation factors used for Method 1.

    Mirrors bias.placement_ipw.DEFAULT_INFLATION_FACTORS so what the
    PDF shows is what the pipeline actually applied.
    """
    data = [
        ["Context",   "Feral hog", "WT deer", "Coyote"],
        ["feeder",    "10.0\u00d7", "4.0\u00d7", "1.5\u00d7"],
        ["food_plot", "6.0\u00d7",  "3.0\u00d7", "1.2\u00d7"],
        ["water",     "3.0\u00d7",  "2.0\u00d7", "2.0\u00d7"],
        ["trail",     "4.0\u00d7",  "3.0\u00d7", "5.0\u00d7"],
        ["random",    "1.0\u00d7",  "1.0\u00d7", "1.0\u00d7"],
        ["other",     "1.5\u00d7",  "1.2\u00d7", "1.3\u00d7"],
    ]
    col_w = [1.2 * inch, 0.95 * inch, 0.95 * inch, 0.95 * inch]
    t = Table(data, colWidths=col_w, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, (0.4, 0.4, 0.4)),
        ("BACKGROUND", (0, 0), (-1, 0), (0.95, 0.95, 0.95)),
    ]))
    return t


def render(assessment: dict) -> list:
    """Return flowables for the methodology appendix."""
    el = []

    el.append(section_bar("Methodology", CONTENT_WIDTH))
    el.append(Spacer(1, 0.18 * inch))

    # ── Outputs ──
    el.append(Paragraph("What This Report Measures", _H2_TIGHT))
    el.append(Paragraph(
        "Three pipeline outputs, in order of methodological primacy: "
        "<b>(1) detection frequency</b>, the raw events per camera-day "
        "\u2014 a relative abundance index requiring no movement "
        "assumption; <b>(2) density</b> in animals per square kilometer, "
        "derived from the bias-adjusted detection frequency through "
        "the Random Encounter Model (Rowcliffe et al. 2008); and "
        "<b>(3) tier</b> (Low / Moderate / Elevated / Severe), the "
        "binary-decision-grade classification per Mayer &amp; Brisbin "
        "(2009) hog-density bins. The composite Exposure Score (0\u2013100) "
        "is a piecewise-linear transform of density anchored on the "
        "tier cutoffs for visual legibility on a single gauge.",
        _BODY_TIGHT))
    el.append(Paragraph(
        "<b>Damage dollars are not a pipeline output.</b> The "
        "supplementary annual-loss projection on the cover page is "
        "scaled from third-party per-hog damage figures (Anderson "
        "et al. 2016) \u00d7 parcel area \u00d7 crop modifier and is "
        "labeled MODELED PROJECTION throughout. A loan committee "
        "with an internal damage model should consume the density "
        "and rate above and replace our dollar figure with their own.",
        _BODY_TIGHT))

    # ── Detection pipeline ──
    el.append(Paragraph("Detection Pipeline", _H2_TIGHT))
    el.append(Paragraph(
        "Camera-trap images are processed in two stages: Microsoft "
        "MegaDetector v5 locates animals (minimum confidence 0.3); "
        "Google SpeciesNet performs taxonomic classification. Both "
        "models are deployed without site-specific fine-tuning. Raw "
        "detections are grouped into independent events using a "
        "two-threshold scheme: photos within 60 seconds of one "
        "another from the same camera/species form a trigger burst, "
        "and bursts within 30 minutes of one another consolidate into "
        "one event. The 30-minute independence threshold is standard "
        "in camera-trap ecology and prevents repeat-counting of the "
        "same individual. All metrics in this report use independent "
        "event counts, never raw photo counts.",
        _BODY_TIGHT))

    # ── REM density ──
    el.append(Paragraph("Density Estimation (REM)", _H2_TIGHT))
    el.append(Paragraph(
        "Density is estimated using the Random Encounter Model "
        "(Rowcliffe et al. 2008), which does not require individual "
        "identification \u2014 essential for hogs and deer at distance, "
        "where natural marks are unreliable at population scale:",
        _BODY_TIGHT))
    el.append(Paragraph(
        "D = (y / t) \u00d7 \u03c0 / (v \u00d7 r \u00d7 (2 + \u03b8))",
        _BODY_MONO))
    el.append(Paragraph(
        "where <i>y/t</i> is detections per camera-day, <i>v</i> is "
        "the species-specific mean daily travel distance, <i>r</i> is "
        "the camera detection radius (0.015 km), and <i>\u03b8</i> is "
        "the camera detection angle (0.7 rad). Daily-distance values "
        "are sourced per species from the literature: 6.0 km/day for "
        "feral hog (Kay et al. 2017), 1.5 km/day for white-tailed "
        "deer (Webb et al. 2010), 10.0 km/day for coyote (Andelt "
        "1985). Species without a published <i>v</i> are reported as "
        "detection-rate index only, with the density estimate omitted.",
        _BODY_TIGHT))

    # ── Placement bias correction ──
    el.append(Paragraph("Placement-Bias Correction", _H2_TIGHT))
    el.append(Paragraph(
        "Cameras placed at feeders, trails, water, or food plots "
        "violate REM\u2019s movement-independence assumption. "
        "Kolowski &amp; Forrester (2017) document detection inflation "
        "of 1.4\u20139.7\u00d7 over random placement depending on "
        "species and context. The pipeline applies two complementary "
        "corrections to the per-camera detection rate <i>before</i> "
        "it enters REM, and reports both alongside the raw rate.",
        _BODY_TIGHT))
    el.append(Paragraph(
        "<b>Method 1 \u2014 Literature-prior ratio adjustment "
        "(primary).</b> For each camera, deflate the observed rate "
        "by the per-species inflation factor for its placement "
        "context, then average across cameras. Factor table (mirrors "
        "the values applied by the pipeline):",
        _BODY_TIGHT))
    el.append(_factor_table())
    el.append(Spacer(1, 0.05 * inch))
    el.append(Paragraph(
        "<b>Method 2 \u2014 Hájek IPW with empirical propensities "
        "(diagnostic).</b> The textbook IPW estimator (Hájek 1971; "
        "Cassel\u2013S\u00e4rndal\u2013Wretman 1976) reweights to a "
        "target placement-context distribution (default: uniform "
        "across observed contexts). Reported alongside the primary "
        "method for transparency; not fed into REM. The two methods "
        "agree closely when the deployment is balanced and diverge "
        "when one context dominates \u2014 which is exactly the case "
        "where bias correction matters most.",
        _BODY_TIGHT))

    # ── Page break before CI / limitations ──
    el.append(CondPageBreak(10 * inch))

    # ── Confidence intervals ──
    el.append(Paragraph("Confidence Intervals", _H2_TIGHT))
    el.append(Paragraph(
        "95% confidence intervals are computed by nonparametric "
        "bootstrap over cameras (1000 iterations, the design\u2019s "
        "primary stochastic source per Rowcliffe 2012). Each "
        "iteration also draws a perturbed daily-distance value "
        "<i>v\u2019 ~ N(v, sd)</i> truncated to [0.5\u00b7v, 1.5\u00b7v] "
        "to propagate inter-individual movement variability without "
        "letting physically implausible draws inflate the upper tail. "
        "The bias-correction weights are recomputed on each bootstrap "
        "resample so IPW uncertainty also feeds into the CI.",
        _BODY_TIGHT))
    el.append(Paragraph(
        "<b>Diagnostics:</b> Kish (1965) effective sample size "
        "ESS = (\u03a3w)\u00b2 / \u03a3(w\u00b2), and the maximum-"
        "weight ratio max(w)/mean(w). Caveats fire automatically when "
        "ESS &lt; n/2, max-weight ratio &gt; 5\u00d7 (Cole &amp; "
        "Hern\u00e1n 2008 stabilization threshold), or no random-"
        "placement cameras anchor the deployment.",
        _BODY_TIGHT))

    # ── Recommendation logic ──
    el.append(Paragraph("Recommendation Logic", _H2_TIGHT))
    el.append(Paragraph(
        "Per species per survey period the pipeline emits one of "
        "three flags:",
        _BODY_TIGHT))
    rec_data = [
        ["Condition", "Recommendation"],
        ["< 100 camera-days OR < 20 events",
            "insufficient_data"],
        ["CI upper / lower ratio > 1.5",
            "recommend_supplementary_survey"],
        ["Otherwise",
            "sufficient_for_decision"],
    ]
    rec_t = Table(rec_data,
                  colWidths=[3.2 * inch, 2.6 * inch],
                  hAlign="LEFT")
    rec_t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING",    (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, (0.4, 0.4, 0.4)),
        ("BACKGROUND", (0, 0), (-1, 0), (0.95, 0.95, 0.95)),
    ]))
    el.append(rec_t)

    # ── Limitations ──
    el.append(Spacer(1, 0.10 * inch))
    el.append(Paragraph("Limitations", _H2_TIGHT))
    el.append(Paragraph(
        "<b>Detection frequency is a relative abundance index.</b> "
        "Conversion to absolute density via REM rests on the daily-"
        "distance values and detection-cone parameters above; both "
        "carry inter-region uncertainty not fully captured by the "
        "bootstrap CI. <b>Damage projections are model-based, not "
        "observed losses.</b> They are scaled from third-party per-"
        "hog figures and a crop-class modifier, and should not be "
        "treated as a primary pipeline output. <b>Tier classification "
        "is defined for feral hog only at v1.</b> Other species "
        "appear with detection rate and density (where v is "
        "available) but no tier; tier extension to deer and coyote "
        "requires per-species cutoff literature review.",
        _BODY_TIGHT))

    return el


def render_references(width: float = None) -> list:
    """Return flowables for the References block, rendered separately
    from the methodology body so they can be stitched onto the back
    cover instead of taking their own page.
    """
    from reportlab.lib.units import inch as _inch
    el: list = []
    if width is None:
        width = CONTENT_WIDTH

    el.append(Paragraph("References", _H2_TIGHT))

    refs = [
        "Andelt, W.F. (1985). Behavioral ecology of coyotes in south "
        "Texas. Wildlife Monographs, 94, 3\u201345.",

        "Anderson, A. et al. (2016). Economic estimates of feral "
        "swine damage and control in 11 US states. Crop Protection, "
        "89, 89\u201394.",

        "Cassel, C.M., S\u00e4rndal, C.E. &amp; Wretman, J.H. (1976). "
        "Some results on generalized difference estimation. "
        "Biometrika, 63, 615\u2013620.",

        "Cole, S.R. &amp; Hern\u00e1n, M.A. (2008). Constructing "
        "inverse probability weights for marginal structural models. "
        "Am. J. Epidemiology, 168, 656\u2013664.",

        "H\u00e1jek, J. (1971). Discussion of \u201cAn essay on the "
        "logical foundations of survey sampling, part one\u201d by D. "
        "Basu. Foundations of Statistical Inference.",

        "Kay, S.L. et al. (2017). Quantifying drivers of wild pig "
        "movement across multiple spatial and temporal scales. "
        "Movement Ecology, 5, 14.",

        "Kish, L. (1965). Survey Sampling. Wiley.",

        "Kolowski, J.M. &amp; Forrester, T.D. (2017). Camera trap "
        "placement and the potential for bias due to trails and "
        "other features. PLOS ONE, 12, e0186679.",

        "Mayer, J.J. &amp; Brisbin, I.L. (2009). Wild Pigs: Biology, "
        "Damage, Control Techniques and Management. Savannah River "
        "National Laboratory.",

        "Rowcliffe, J.M., Field, J., Turvey, S.T. &amp; Carbone, C. "
        "(2008). Estimating animal density using camera traps "
        "without the need for individual recognition. J. Appl. "
        "Ecol., 45, 1228\u20131236.",

        "Rowcliffe, J.M. et al. (2012). Bias in estimating animal "
        "travel distance: the effect of sampling frequency. "
        "Methods in Ecol. Evol., 3, 653\u2013662.",

        "Webb, S.L., Hewitt, D.G. &amp; Hellickson, M.W. (2010). "
        "Survival and cause-specific mortality of mature male "
        "white-tailed deer. J. Wildlife Mgmt., 74, 1416\u20131421.",
    ]

    half = (len(refs) + 1) // 2
    left_col = [Paragraph(r, _CITATION_TIGHT) for r in refs[:half]]
    right_col = [Paragraph(r, _CITATION_TIGHT) for r in refs[half:]]
    while len(right_col) < len(left_col):
        right_col.append(Spacer(1, 0.01 * inch))

    gutter = 0.25 * inch
    col_w = (width - gutter) / 2
    refs_table = Table(
        [[left_col, right_col]],
        colWidths=[col_w, col_w],
    )
    refs_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), gutter / 2),
        ("LEFTPADDING", (1, 0), (1, 0), gutter / 2),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    el.append(refs_table)

    return el
