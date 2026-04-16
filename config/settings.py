"""Central configuration for Basal Informatics.

All thresholds, paths, API keys, and model configs.
Reads from environment variables with sensible defaults.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Database ---
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", 5432))
DB_NAME = os.environ.get("DB_NAME", "basal")
DB_USER = os.environ.get("DB_USER", "basal")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "basal_dev")

# --- Strecker thresholds ---
BURST_THRESHOLD_SECONDS = 60        # Photos within this window = same trigger burst
INDEPENDENCE_THRESHOLD_MINUTES = 30  # Standard independence threshold for camera trap ecology
REVIEW_ENTROPY_THRESHOLD = 0.59     # Binary entropy threshold calibrated for ~8% review rate
                                     # (Norouzzadeh 0.5 was for full K-class; binary max = ln(2) ≈ 0.693)
MIN_MEGADETECTOR_CONFIDENCE = 0.3    # Below this, skip classification entirely
MEGADETECTOR_MODEL = os.environ.get("MEGADETECTOR_MODEL", "MDV5A")  # MDV5A or MDV5B
MEGADETECTOR_CONFIDENCE_THRESHOLD = float(os.environ.get("MEGADETECTOR_CONFIDENCE_THRESHOLD", "0.15"))
SPECIESNET_MODEL = os.environ.get("SPECIESNET_MODEL", "kaggle:google/speciesnet/pyTorch/v4.0.2a/1")

# --- Classification ---
MODEL_PATH = os.environ.get("MODEL_PATH", "./models/species_classifier.pt")
MEGADETECTOR_PATH = os.environ.get("MEGADETECTOR_PATH", "./models/megadetector_v5.pt")
CONFIDENCE_CALIBRATION_METHOD = "temperature_scaling"  # Dussert et al. 2025
SPECIESNET_CONFIDENCE_THRESHOLD = 0.7  # Below this = "Unknown"
TEMPERATURE_SCALING_T = 1.08           # Softens overconfident predictions ~5-10%

# --- Detection radii by body size (meters) ---
DETECTION_RADIUS = {"large": 200, "medium": 150, "small": 100}

# --- Bias correction ---
PLACEMENT_CONTEXTS = ["trail", "feeder", "food_plot", "water", "random", "other"]
TRAIL_FEEDER_INFLATION_FACTOR = 9.7  # Kolowski & Forrester 2017

# --- Population estimation (Random Encounter Model, Rowcliffe et al. 2008) ---
# REM: D = (y/t) * pi / (v * r * (2 + theta))
#   y/t = detections per camera-day (computed)
#   v   = avg daily travel distance, km/day (per species, below)
#   r   = camera detection radius, km (typical IR trail cam ~15 m)
#   theta = camera detection angle, radians (typical IR ~40 deg = 0.7 rad)
#
# Density output is animals/km^2.
# Sources cite published per-species daily-distance estimates; sd captures
# inter-individual variability used in bootstrap CI.
SPECIES_MOVEMENT = {
    "feral_hog":         {"v_km_day": 6.0,  "v_sd": 2.5, "source": "Kay et al. 2017; McClure et al. 2015"},
    "white_tailed_deer": {"v_km_day": 1.5,  "v_sd": 0.8, "source": "Webb et al. 2010"},
    "axis_deer":         {"v_km_day": 3.0,  "v_sd": 1.2, "source": "literature range; TX-specific scarce"},
    "coyote":            {"v_km_day": 10.0, "v_sd": 4.0, "source": "Andelt 1985"},
    # Species without a published v fall back to detection-rate index only
    # (no density output; recommendation flag explains).
}
CAMERA_DETECTION_RADIUS_M  = 15.0   # meters; default for medium IR trail cams
CAMERA_DETECTION_ANGLE_RAD = 0.7    # ~40 degrees
REM_BOOTSTRAP_N            = 1000   # nonparametric bootstrap iterations
MIN_CAMERA_DAYS_FOR_DENSITY = 100   # below: insufficient_data
MIN_DETECTIONS_FOR_DENSITY  = 20
DENSITY_CI_RATIO_THRESHOLD  = 1.5   # CI upper/lower > this => recommend supplementary survey

# --- Financial modeling ---
DISCOUNT_RATE = 0.05  # For 10-year NPV projections

# --- Habitat ---
HABITAT_UNIT_ID_FORMAT = "HU-{huc10}-{ecoregion_iv}-{nlcd}"

# --- Corridor defaults (meters) ---
RIPARIAN_BUFFER_M = 100
RIDGE_BUFFER_M = 50
EDGE_BUFFER_M = 30

# --- Paths ---
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOAD_DIR = os.path.abspath(os.environ.get("STRECKER_UPLOAD_DIR", os.path.join(_project_root, "uploads")))
REPORT_OUTPUT_DIR = os.path.abspath(os.path.join(_project_root, "reports"))
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")

# --- Flask ---
_default_secret = "dev-only-key-not-for-production"
FLASK_SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", _default_secret)
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# Block startup if SECRET_KEY is still the default in production
if not FLASK_DEBUG and FLASK_SECRET_KEY == _default_secret:
    import warnings
    warnings.warn(
        "FLASK_SECRET_KEY not set! Set it via environment variable before deploying.",
        RuntimeWarning,
        stacklevel=2,
    )

# --- SQLAlchemy ---
# DO App Platform: use Managed Postgres (DATABASE_URL is auto-injected when
# the DB is bound as a component). Locally: SQLite inside instance/.
# Note: DO sometimes gives `postgres://` URLs; SQLAlchemy 2.x wants `postgresql://`.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///basal.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]
SECRET_KEY = FLASK_SECRET_KEY

# Connection pooling — App Platform containers share a small pool with the DB.
SQLALCHEMY_ENGINE_OPTIONS = {
    "pool_size": int(os.environ.get("DB_POOL_SIZE", "5")),
    "max_overflow": int(os.environ.get("DB_MAX_OVERFLOW", "5")),
    "pool_pre_ping": True,        # recycle dead connections transparently
    "pool_recycle": 1800,         # 30 min — below Postgres idle timeout
}

# --- Object storage (DO Spaces / S3-compatible) ---
# Set these to enable Spaces-backed uploads. If SPACES_BUCKET is empty,
# the app falls back to local filesystem (dev only — App Platform's FS is
# ephemeral and the worker runs on a separate box, so prod MUST use Spaces).
SPACES_BUCKET = os.environ.get("SPACES_BUCKET", "")
SPACES_REGION = os.environ.get("SPACES_REGION", "nyc3")
SPACES_ENDPOINT = os.environ.get(
    "SPACES_ENDPOINT",
    f"https://{os.environ.get('SPACES_REGION', 'nyc3')}.digitaloceanspaces.com",
)
SPACES_KEY = os.environ.get("SPACES_KEY", "")
SPACES_SECRET = os.environ.get("SPACES_SECRET", "")
SPACES_PRESIGN_TTL = int(os.environ.get("SPACES_PRESIGN_TTL", "3600"))  # 1h

# --- PDF styling ---
PDF_COLORS = {
    "brand_teal": "#0D7377",
    "text_primary": "#1A1A1A",
    "text_secondary": "#5A6B7F",
    "risk_high": "#C43B31",
    "risk_moderate": "#D4880F",
    "risk_low": "#2A7D3F",
    "table_header_bg": "#0D7377",
    "table_header_text": "#FFFFFF",
    "table_alt_row": "#F5F7F9",
}
PDF_FONTS = {"heading": "Helvetica-Bold", "body": "Helvetica", "mono": "Courier"}

# --- Re-ID (individual deer tracking) ---
REID_ENABLED_SPECIES = ["white_tailed_deer", "axis_deer"]  # Species with re-ID support
REID_MODEL_PATH = os.environ.get("REID_MODEL_PATH", "./models/deer_reid_encoder.pt")
REID_EMBEDDING_DIM = 128  # Feature vector dimensionality
REID_MATCH_THRESHOLD = 0.75  # Cosine sim above this = auto-match
REID_CANDIDATE_THRESHOLD = 0.55  # Above this = candidate for user review
REID_TEMPORAL_BOOST = 0.05  # Similarity boost for same camera within 2 hours
REID_MIN_CROP_SIZE = 64  # Minimum crop dimension (pixels) for reliable embedding
REID_ANTLER_SEASON_MONTHS = [5, 6, 7, 8, 9, 10, 11]  # May-Nov (hardened antlers)
