"""PDF styling — editorial voice, to match basal.eco.

Design language inherited from the website:

  * Fraunces (Display + 9pt) — display type, titles, pull quotes
  * Inter — body copy and captions
  * JetBrains Mono — eyebrows, data, tabular figures

Palette:

  * Ink        #0c0d0a — near-black
  * Bone       #f4f1ea — warm paper
  * Forest     #1c2118 — deep forest, used for section rules
  * Forest-lit #8a9a74 — one green accent; data highlights
  * Stone-*    neutral gray ramp for secondary ink and tables

The page is bone paper with ink type. Color is reserved for data —
the voice stays restrained. One accent (forest-lit) per page at most.

Legacy constants (BRAND_NAVY, BRAND_BLUE, RISK_* …) are preserved as
aliases pointing at the new tokens so the eight section modules keep
rendering without edits.
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ═══════════════════════════════════════════════════════════════════════════
# Font registration — Fraunces + Inter + JetBrains Mono
# ═══════════════════════════════════════════════════════════════════════════

_FONT_DIR = Path(__file__).parent / "assets" / "fonts"


def _register(name: str, filename: str) -> bool:
    try:
        pdfmetrics.registerFont(TTFont(name, str(_FONT_DIR / filename)))
        return True
    except Exception:
        return False


_FRAUNCES_OK = all([
    _register("Fraunces",         "Fraunces-Regular.ttf"),
    _register("Fraunces-Bold",    "Fraunces-Bold.ttf"),
    _register("Fraunces-Italic",  "Fraunces-Italic.ttf"),
    _register("Fraunces-Display", "Fraunces-Display.ttf"),
])
_INTER_OK = all([
    _register("Inter",            "Inter-Regular.ttf"),
    _register("Inter-Medium",     "Inter-Medium.ttf"),
    _register("Inter-SemiBold",   "Inter-SemiBold.ttf"),
    _register("Inter-Italic",     "Inter-Italic.ttf"),
])
_MONO_OK = all([
    _register("JetBrainsMono",        "JetBrainsMono-Regular.ttf"),
    _register("JetBrainsMono-Medium", "JetBrainsMono-Medium.ttf"),
])

if _FRAUNCES_OK:
    pdfmetrics.registerFontFamily(
        "Fraunces",
        normal="Fraunces", bold="Fraunces-Bold",
        italic="Fraunces-Italic", boldItalic="Fraunces-Bold",
    )
if _INTER_OK:
    pdfmetrics.registerFontFamily(
        "Inter",
        normal="Inter", bold="Inter-SemiBold",
        italic="Inter-Italic", boldItalic="Inter-SemiBold",
    )

# Font-name aliases (logical role → physical font)
SERIF_DISPLAY = "Fraunces-Display" if _FRAUNCES_OK else "Times-Bold"
SERIF_REGULAR = "Fraunces"         if _FRAUNCES_OK else "Times-Roman"
SERIF_BOLD    = "Fraunces-Bold"    if _FRAUNCES_OK else "Times-Bold"
SERIF_ITALIC  = "Fraunces-Italic"  if _FRAUNCES_OK else "Times-Italic"
SANS_REGULAR  = "Inter"            if _INTER_OK    else "Helvetica"
SANS_MEDIUM   = "Inter-Medium"     if _INTER_OK    else "Helvetica"
SANS_BOLD     = "Inter-SemiBold"   if _INTER_OK    else "Helvetica-Bold"
SANS_ITALIC   = "Inter-Italic"     if _INTER_OK    else "Helvetica-Oblique"
MONO_REGULAR  = "JetBrainsMono"        if _MONO_OK else "Courier"
MONO_MEDIUM   = "JetBrainsMono-Medium" if _MONO_OK else "Courier-Bold"

# ═══════════════════════════════════════════════════════════════════════════
# Palette — editorial, from basal.eco
# ═══════════════════════════════════════════════════════════════════════════

COLORS = {
    # Surfaces — official white paper, ink cover
    "page_bg":  "#ffffff",  # white paper (content pages)
    "cover_bg": "#0c0d0a",  # ink (cover page, full-bleed)
    # Ink
    "text_primary":   "#0c0d0a",
    "text_secondary": "#5a5a5a",  # neutral mid gray
    "text_muted":     "#8a8a8a",  # neutral light gray
    # Accent — single green, used sparingly
    "forest":      "#1c2118",  # deep forest (section rules, data strokes)
    "forest_lit":  "#6a7a54",  # forest-lit (single data accent, muted)
    # Legacy-named aliases so section modules keep rendering
    # (they reference BRAND_NAVY, BRAND_BLUE, BRAND_TEAL, etc.)
    "brand_navy":       "#0c0d0a",  # redirected to ink
    "brand_navy_deep":  "#0c0d0a",
    "brand_blue":       "#8a9a74",  # redirected to forest-lit
    "brand_blue_light": "#d8dcc8",  # pale forest tint
    "brand_teal":       "#8a9a74",
    "brand_accent":     "#8a9a74",
    # Risk ramp — ink descent (deep → pale forest tint)
    "risk_critical":  "#0c0d0a",
    "risk_high":      "#2b2d29",
    "risk_elevated":  "#595650",
    "risk_moderate":  "#8a9a74",
    "risk_low":       "#d8dcc8",
    # Chart series
    "chart_primary":   "#0c0d0a",  # ink — primary subject
    "chart_secondary": "#8a9a74",  # forest-lit — secondary
    "chart_tertiary":  "#bdbdb4",  # warm gray — tertiary
    "chart_neutral":   "#c8c5bd",  # warm gridline
    # Back-compat
    "chart_unmanaged": "#0c0d0a",
    "chart_managed":   "#8a9a74",
    "chart_avoidable": "#c8c5bd",
    # Structure
    "gridline":         "#d8d8d8",  # hairline on white
    "border_light":     "#c8c8c8",
    "table_header_bg":  "#ffffff",
    "table_header_text": "#0c0d0a",
    "table_alt_row":    "#f4f4f4",
    "section_bar_bg":   "#0c0d0a",  # black eyebrow bar (editorial)
    "section_bar_text": "#ffffff",
    "background":       "#ffffff",
}

# ReportLab color objects
PAGE_BG        = colors.HexColor(COLORS["page_bg"])
COVER_BG       = colors.HexColor(COLORS["cover_bg"])
INK            = colors.HexColor(COLORS["text_primary"])
BONE           = colors.HexColor(COLORS["page_bg"])
FOREST         = colors.HexColor(COLORS["forest"])
FOREST_LIT     = colors.HexColor(COLORS["forest_lit"])
BRAND_NAVY      = INK
BRAND_NAVY_DEEP = INK
BRAND_BLUE      = FOREST_LIT
BRAND_BLUE_LIGHT = colors.HexColor(COLORS["brand_blue_light"])
BRAND_TEAL      = FOREST_LIT
BRAND_ACCENT    = FOREST_LIT
TEXT_PRIMARY    = INK
TEXT_SECONDARY  = colors.HexColor(COLORS["text_secondary"])
TEXT_MUTED      = colors.HexColor(COLORS["text_muted"])
RISK_CRITICAL   = colors.HexColor(COLORS["risk_critical"])
RISK_HIGH       = colors.HexColor(COLORS["risk_high"])
RISK_ELEVATED   = colors.HexColor(COLORS["risk_elevated"])
RISK_LOW        = colors.HexColor(COLORS["risk_low"])
TABLE_HEADER_BG = colors.HexColor(COLORS["table_header_bg"])
TABLE_HEADER_TEXT = INK
TABLE_ALT_ROW   = colors.HexColor(COLORS["table_alt_row"])
GRIDLINE        = colors.HexColor(COLORS["gridline"])
BORDER_LIGHT    = colors.HexColor(COLORS["border_light"])
SECTION_BAR_BG  = INK
SECTION_BAR_TEXT = BONE

# Cover palette
COVER_TEXT  = colors.HexColor("#f4f1ea")  # bone on ink
COVER_MUTED = colors.HexColor("#8a877f")
COVER_RULE  = colors.HexColor("#2b2d29")
COVER_ACCENT = colors.HexColor(COLORS["forest_lit"])

FONTS = {
    # Legacy role map — kept so sections that read FONTS[...] still work
    "heading":       SERIF_BOLD,
    "body":          SANS_REGULAR,
    "italic":        SERIF_ITALIC,
    "mono":          MONO_REGULAR,
    "display":       SERIF_DISPLAY,
    "serif_regular": SERIF_REGULAR,
    "serif_bold":    SERIF_BOLD,
    "serif_italic":  SERIF_ITALIC,
    "sans_regular":  SANS_REGULAR,
    "sans_bold":     SANS_BOLD,
    "mono_regular":  MONO_REGULAR,
    "mono_medium":   MONO_MEDIUM,
}

# ═══════════════════════════════════════════════════════════════════════════
# Page dimensions (US Letter)
# ═══════════════════════════════════════════════════════════════════════════

PAGE_WIDTH    = 8.5 * inch
PAGE_HEIGHT   = 11  * inch
MARGIN_LEFT   = 0.85 * inch
MARGIN_RIGHT  = 0.85 * inch
MARGIN_TOP    = 0.85 * inch
MARGIN_BOTTOM = 0.85 * inch
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# ═══════════════════════════════════════════════════════════════════════════
# Paragraph styles — editorial hierarchy
#
# Display type is Fraunces (72pt-SemiBold). Body is Inter. Eyebrows
# and data are JetBrains Mono, uppercased with tight tracking.
# ═══════════════════════════════════════════════════════════════════════════

STYLE_TITLE = ParagraphStyle(
    "ReportTitle",
    fontName=SERIF_DISPLAY, fontSize=32, leading=38,
    textColor=INK, alignment=TA_LEFT, spaceAfter=6,
)

STYLE_SUBTITLE = ParagraphStyle(
    "ReportSubtitle",
    fontName=SERIF_ITALIC, fontSize=13, leading=18,
    textColor=TEXT_SECONDARY, alignment=TA_LEFT, spaceAfter=12,
)

STYLE_H1 = ParagraphStyle(
    "H1",
    fontName=SERIF_DISPLAY, fontSize=22, leading=26,
    textColor=INK, spaceBefore=0, spaceAfter=4,
)

# Reserved name — used inside the numbered header strip.
# Now a mono eyebrow, not a centered serif on navy.
STYLE_H1_BAR = ParagraphStyle(
    "H1Bar",
    fontName=MONO_REGULAR, fontSize=9, leading=12,
    textColor=INK, alignment=TA_LEFT,
    spaceBefore=0, spaceAfter=0,
)

STYLE_H2 = ParagraphStyle(
    "H2",
    fontName=SERIF_BOLD, fontSize=12, leading=15,
    textColor=INK,
    spaceBefore=12, spaceAfter=3,
)

STYLE_H3 = ParagraphStyle(
    "H3",
    fontName=SANS_BOLD, fontSize=9.5, leading=12,
    textColor=INK,
    spaceBefore=8, spaceAfter=2,
)

STYLE_EYEBROW = ParagraphStyle(
    "Eyebrow",
    fontName=SANS_ITALIC, fontSize=8, leading=10,
    textColor=TEXT_SECONDARY, alignment=TA_LEFT,
    spaceBefore=0, spaceAfter=3,
)

STYLE_BODY = ParagraphStyle(
    "Body",
    fontName=SANS_REGULAR, fontSize=9.5, leading=13,
    textColor=INK, alignment=TA_JUSTIFY, spaceAfter=5,
    # Prevent a single orphan line bleeding to the next page at the
    # top and a single widow line left behind at the bottom.
    allowOrphans=0, allowWidows=0,
)

STYLE_BODY_SMALL = ParagraphStyle(
    "BodySmall",
    fontName=SANS_REGULAR, fontSize=8, leading=11,
    textColor=TEXT_SECONDARY, alignment=TA_JUSTIFY, spaceAfter=3,
)

STYLE_CAPTION = ParagraphStyle(
    "Caption",
    fontName=MONO_REGULAR, fontSize=7.5, leading=10,
    textColor=TEXT_SECONDARY, alignment=TA_LEFT,
    spaceAfter=4, spaceBefore=2,
)

STYLE_METRIC_LARGE = ParagraphStyle(
    "MetricLarge",
    fontName=SERIF_DISPLAY, fontSize=48, leading=52,
    textColor=INK, alignment=TA_CENTER,
)

STYLE_METRIC_LABEL = ParagraphStyle(
    "MetricLabel",
    fontName=MONO_REGULAR, fontSize=8, leading=11,
    textColor=TEXT_SECONDARY, alignment=TA_CENTER,
)

STYLE_FOOTNOTE = ParagraphStyle(
    "Footnote",
    fontName=SANS_ITALIC, fontSize=7.5, leading=10,
    textColor=TEXT_SECONDARY, alignment=TA_LEFT, spaceBefore=8,
)

STYLE_CITATION = ParagraphStyle(
    "Citation",
    fontName=SANS_REGULAR, fontSize=8, leading=11,
    textColor=TEXT_SECONDARY, alignment=TA_LEFT,
    leftIndent=14, firstLineIndent=-14, spaceAfter=4,
)

# ═══════════════════════════════════════════════════════════════════════════
# Cover page styles — ink ground, bone type, forest-lit accents
# ═══════════════════════════════════════════════════════════════════════════

STYLE_COVER_WORDMARK = ParagraphStyle(
    "CoverWordmark",
    fontName=MONO_REGULAR, fontSize=9, leading=12,
    textColor=COVER_TEXT, alignment=TA_LEFT,
)

STYLE_COVER_LABEL = ParagraphStyle(
    "CoverLabel",
    fontName=MONO_REGULAR, fontSize=8, leading=11,
    textColor=COVER_MUTED, alignment=TA_LEFT,
)

STYLE_COVER_EYEBROW = ParagraphStyle(
    "CoverEyebrow",
    fontName=MONO_REGULAR, fontSize=9, leading=12,
    textColor=COVER_ACCENT, alignment=TA_LEFT,
    spaceAfter=10,
)

STYLE_COVER_TITLE = ParagraphStyle(
    "CoverTitle",
    fontName=SERIF_DISPLAY, fontSize=40, leading=46,
    textColor=COVER_TEXT, alignment=TA_LEFT,
    spaceAfter=8,
)

STYLE_COVER_SUBTITLE = ParagraphStyle(
    "CoverSubtitle",
    fontName=SERIF_ITALIC, fontSize=14, leading=20,
    textColor=COVER_TEXT, alignment=TA_LEFT,
    spaceAfter=6,
)

STYLE_COVER_META_KEY = ParagraphStyle(
    "CoverMetaKey",
    fontName=MONO_REGULAR, fontSize=7.5, leading=11,
    textColor=COVER_MUTED, alignment=TA_LEFT,
)

STYLE_COVER_META_VAL = ParagraphStyle(
    "CoverMetaVal",
    fontName=SANS_MEDIUM, fontSize=10, leading=13,
    textColor=COVER_TEXT, alignment=TA_LEFT,
)

STYLE_COVER_CAPTION = ParagraphStyle(
    "CoverCaption",
    fontName=MONO_REGULAR, fontSize=7.5, leading=10,
    textColor=COVER_MUTED, alignment=TA_LEFT,
)

STYLE_COVER_FOOTER = ParagraphStyle(
    "CoverFooter",
    fontName=MONO_REGULAR, fontSize=7.5, leading=11,
    textColor=COVER_MUTED, alignment=TA_LEFT,
)

# ═══════════════════════════════════════════════════════════════════════════
# Table style — hairline rules, tabular mono numerals
# ═══════════════════════════════════════════════════════════════════════════

def base_table_style(n_rows: int) -> list:
    """Editorial table — hairline top + bottom, mono numerals.

    Header: tiny mono uppercase with a thin ink rule above and hair
    rule below. Body rows: Inter sans, hairline separators. Close with
    a thin ink bottom rule. The whole table reads as a block of
    financial-editorial tabular type, not a colored matrix.
    """
    cmds = [
        # Header
        ("FONTNAME",  (0, 0), (-1, 0), MONO_REGULAR),
        ("FONTSIZE",  (0, 0), (-1, 0), 7.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_SECONDARY),
        ("LINEABOVE", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.25, INK),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING",    (0, 0), (-1, 0), 6),
        # Body
        ("FONTNAME",  (0, 1), (-1, -1), SANS_REGULAR),
        ("FONTSIZE",  (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        # Layout
        ("ALIGN",  (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 2),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 2),
        # Row separators + closing rule
        ("LINEBELOW", (0, 1), (-1, -2), 0.2, GRIDLINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.8, INK),
    ]
    return cmds


def risk_color(rating: str) -> colors.HexColor:
    """Return an ink-descending color for a risk rating string.

    CRITICAL is deepest ink; LOW fades to pale forest tint. The ramp
    stays monochromatic (one warm neutral family) so it reads as a
    single visual system.
    """
    r = (rating or "").upper()
    if "CRITICAL" in r:
        return RISK_CRITICAL
    if "HIGH" in r:
        return RISK_HIGH
    if "ELEVATED" in r or "MODERATE" in r:
        return RISK_ELEVATED
    return RISK_LOW


def grade_color(grade: str) -> str:
    """Hex for a confidence grade (ink-descending ramp)."""
    if grade.startswith("A"):
        return COLORS["risk_critical"]  # ink
    if grade.startswith("B"):
        return COLORS["risk_high"]
    if grade.startswith("C"):
        return COLORS["risk_elevated"]
    return COLORS["text_secondary"]


def section_bar(title: str, width: float):
    """Institutional section header — title over hairline rule.

    Two rows:
      row 1: Fraunces display title, sentence case (e.g. "Executive
             Summary"), left-aligned
      row 2: thin ink rule across the full content width

    Deliberately restrained. No uppercase mono eyebrow, no numeric
    prefix, no colored bar — the title itself carries the hierarchy.
    This is the idiom used by Goldman Sachs research and McKinsey
    Global Institute reports, where the running chrome stays quiet
    and the display type does the work.
    """
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

    style = ParagraphStyle(
        "SectionTitle",
        fontName=SERIF_DISPLAY, fontSize=18, leading=22,
        textColor=INK, alignment=TA_LEFT,
    )
    p = Paragraph(title, style)
    t = Table(
        [[p], [""]],
        colWidths=[width],
        rowHeights=[0.30 * inch, 0.02 * inch],
    )
    t.setStyle(TableStyle([
        ("LINEBELOW",     (0, 1), (-1, 1), 0.5, INK),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return t


# ═══════════════════════════════════════════════════════════════════════════
# Matplotlib — editorial chart style
# ═══════════════════════════════════════════════════════════════════════════

_MPL_CONFIGURED = False


def setup_chart_style() -> None:
    """rcParams so charts feel like they belong in this document.

    Fraunces for titles, Inter for labels (via matplotlib's fallback
    chain — we register what we have). Bone figure face, warm gray
    gridlines, ink axes. Data series use the COLORS['chart_*'] ramp.
    """
    global _MPL_CONFIGURED
    if _MPL_CONFIGURED:
        return

    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager, rcParams

    # Register any TTFs we have with matplotlib so serif/sans resolve.
    if _FRAUNCES_OK or _INTER_OK or _MONO_OK:
        for fname in _FONT_DIR.glob("*.ttf"):
            try:
                font_manager.fontManager.addfont(str(fname))
            except Exception:
                pass

    rcParams["font.family"] = "serif"
    rcParams["font.serif"]  = ["Fraunces", "Times New Roman", "serif"]
    rcParams["font.sans-serif"] = ["Inter", "Helvetica", "Arial", "sans-serif"]

    rcParams["figure.facecolor"] = COLORS["page_bg"]
    rcParams["axes.facecolor"]   = COLORS["page_bg"]
    rcParams["savefig.facecolor"] = COLORS["page_bg"]
    rcParams["savefig.edgecolor"] = COLORS["page_bg"]
    rcParams["text.color"]       = COLORS["text_primary"]
    rcParams["axes.labelcolor"]  = COLORS["text_secondary"]
    rcParams["axes.edgecolor"]   = COLORS["text_primary"]
    rcParams["xtick.color"]      = COLORS["text_secondary"]
    rcParams["ytick.color"]      = COLORS["text_secondary"]
    rcParams["grid.color"]       = COLORS["gridline"]
    rcParams["axes.titlecolor"]  = COLORS["text_primary"]
    rcParams["axes.titleweight"] = "bold"
    rcParams["legend.frameon"]   = False
    rcParams["axes.spines.top"]   = False
    rcParams["axes.spines.right"] = False

    _MPL_CONFIGURED = True


# Apply on import so any section that pulls from report.styles picks
# it up automatically; sections can still call setup_chart_style()
# defensively.
setup_chart_style()
