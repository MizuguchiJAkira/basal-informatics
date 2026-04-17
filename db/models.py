"""SQLAlchemy models for Basal Informatics hunter-facing web app.

Phase 5 data infrastructure — persistent storage layer.
SQLite for development, swap to PostGIS later.
"""

import uuid
from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120))
    is_owner = db.Column(db.Boolean, default=False)  # Basal Informatics admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    properties = db.relationship("Property", backref="owner", lazy="dynamic")
    uploads = db.relationship("Upload", backref="uploader", lazy="dynamic")
    share_cards = db.relationship("ShareCard", backref="creator", lazy="dynamic")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

    def __repr__(self):
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# Property
# ---------------------------------------------------------------------------

class Property(db.Model):
    """A parcel of land.

    Same row serves both sides of the product:
      - Strecker (hunter-facing): calls it a "property", renders in /properties/*
      - Basal Informatics (lender-facing): calls it a "parcel", renders in /lender/*

    Parcel is associated with a LenderClient (the Farm Credit branch that holds
    the loan) through ``lender_client_id``. A parcel with ``lender_client_id=NULL``
    is hunter-only (no loan-backed assessment in flight). Crop type and
    parcel_id display-format are additive fields used only on the Basal side;
    Strecker ignores them.
    """
    __tablename__ = "properties"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    county = db.Column(db.String(100))
    state = db.Column(db.String(2))
    acreage = db.Column(db.Float)
    # GeoJSON as string for SQLite; swap to PostGIS Geometry later
    boundary_geojson = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- Basal-side additive fields (nullable; hunter-side ignores) ---
    lender_client_id = db.Column(
        db.Integer, db.ForeignKey("lender_clients.id"), nullable=True, index=True
    )
    # Major crop class at time of assessment. Drives APHIS/RMA damage modeling.
    # Values: corn, sorghum, rice, cotton, peanut, wheat, soybean, hay, pasture,
    # rangeland, mixed, other. Free-form for now; could move to an enum later.
    crop_type = db.Column(db.String(40), nullable=True)
    # Loan details stay at LenderClient level for MVP — not per-parcel — since
    # a single lender client is one Farm Credit branch per the v1 spec.

    # Relationships
    cameras = db.relationship("Camera", backref="property", lazy="dynamic")
    seasons = db.relationship("Season", backref="property", lazy="dynamic")
    uploads = db.relationship("Upload", backref="property", lazy="dynamic")
    coverage_scores = db.relationship(
        "CoverageScore", backref="property", lazy="dynamic"
    )
    share_cards = db.relationship("ShareCard", backref="property", lazy="dynamic")

    @property
    def parcel_id(self) -> str:
        """Display-formatted parcel identifier.

        Format: ``<STATE>-<COUNTY3>-<YEAR>-<SEQ>`` e.g. ``TX-KIM-2024-04817``.
        Derived, not stored — keeps the column count honest. If state/county
        are missing we fall back to a stable numeric form so callers never
        get None.
        """
        state = (self.state or "XX").upper()[:2]
        county = "".join(c for c in (self.county or "") if c.isalpha()).upper()[:3] or "XXX"
        year = self.created_at.year if self.created_at else 2026
        return f"{state}-{county}-{year}-{self.id:05d}"

    def __repr__(self):
        return f"<Property {self.name}>"


# ---------------------------------------------------------------------------
# LenderClient — a Farm Credit branch or ag bank that buys Basal's reports
# ---------------------------------------------------------------------------

class LenderClient(db.Model):
    """One Farm Credit branch / ag bank / lender that commissions Nature
    Exposure Reports on parcels in its loan portfolio.

    MVP grain = one row per BRANCH. A regional Farm Credit System entity
    with 40 branches = 40 rows. Parent-child relationships between branches
    and holdings are deferred to post-pilot.

    A Property (= parcel) has one current LenderClient via
    ``Property.lender_client_id``. Historical loan transfers (parcel X moved
    from lender A to lender B) are NOT tracked separately — we just update
    the FK. If audit history becomes required we'll add a
    ``parcel_lender_assignments`` table later.
    """
    __tablename__ = "lender_clients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)        # "Farm Credit of Central Texas"
    slug = db.Column(db.String(80), unique=True)            # "farm-credit-central-texas" — URL-safe, stable
    parent_org = db.Column(db.String(200), nullable=True)   # "AgFirst FCS", "FCS of America", etc.
    state = db.Column(db.String(2), nullable=True)          # primary operating state
    hq_address = db.Column(db.Text, nullable=True)
    contact_email = db.Column(db.String(255), nullable=True)
    # Billing / plan. Left as text for MVP; can harden to enum later.
    plan_tier = db.Column(db.String(40), default="per_parcel")   # per_parcel | portfolio_unlimited
    per_parcel_rate_usd = db.Column(db.Numeric(10, 2), nullable=True)   # if per_parcel
    portfolio_rate_usd_monthly = db.Column(db.Numeric(10, 2), nullable=True)  # if unlimited
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Reverse relationship: all parcels currently under this lender.
    # We do NOT backref on Property.lender_client to avoid polluting the
    # Strecker-side model introspection; the Basal routes query explicitly.
    parcels = db.relationship(
        "Property",
        primaryjoin="Property.lender_client_id == LenderClient.id",
        foreign_keys="Property.lender_client_id",
        lazy="dynamic",
        viewonly=True,
    )

    def __repr__(self):
        return f"<LenderClient {self.name}>"


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

class Camera(db.Model):
    __tablename__ = "cameras"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    camera_label = db.Column(db.String(50))  # e.g. "CAM-F01"
    name = db.Column(db.String(120))  # friendly name e.g. "South Feeder"
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    placement_context = db.Column(
        db.String(30)
    )  # feeder/trail/food_plot/water/random/other
    camera_model = db.Column(db.String(100))
    installed_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    detection_summaries = db.relationship(
        "DetectionSummary", backref="camera", lazy="dynamic"
    )

    def __repr__(self):
        return f"<Camera {self.camera_label}>"


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class Upload(db.Model):
    __tablename__ = "uploads"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    season_id = db.Column(db.Integer, db.ForeignKey("seasons.id"), nullable=True)
    status = db.Column(
        db.String(20), default="pending"
    )  # pending/processing/complete/error
    photo_count = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<Upload {self.id} status={self.status}>"


# ---------------------------------------------------------------------------
# Season
# ---------------------------------------------------------------------------

class Season(db.Model):
    __tablename__ = "seasons"

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    name = db.Column(db.String(100))  # e.g. "Spring 2025"
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    detection_summaries = db.relationship(
        "DetectionSummary", backref="season", lazy="dynamic"
    )
    uploads = db.relationship("Upload", backref="season", lazy="dynamic")
    coverage_scores = db.relationship(
        "CoverageScore", backref="season", lazy="dynamic"
    )
    share_cards = db.relationship("ShareCard", backref="season", lazy="dynamic")

    def __repr__(self):
        return f"<Season {self.name}>"


# ---------------------------------------------------------------------------
# DetectionSummary
# ---------------------------------------------------------------------------

class DetectionSummary(db.Model):
    __tablename__ = "detection_summaries"
    __table_args__ = (
        db.UniqueConstraint(
            "season_id", "camera_id", "species_key",
            name="uq_detection_summary_season_camera_species",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    season_id = db.Column(
        db.Integer, db.ForeignKey("seasons.id"), nullable=False
    )
    camera_id = db.Column(
        db.Integer, db.ForeignKey("cameras.id"), nullable=False
    )
    species_key = db.Column(db.String(80), nullable=False)
    total_photos = db.Column(db.Integer)
    independent_events = db.Column(db.Integer)
    avg_confidence = db.Column(db.Float)
    first_seen = db.Column(db.DateTime)
    last_seen = db.Column(db.DateTime)
    buck_count = db.Column(db.Integer)
    doe_count = db.Column(db.Integer)
    peak_hour = db.Column(db.Integer)  # 0-23
    # JSON string of 24 hourly counts
    hourly_distribution = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DetectionSummary {self.species_key} cam={self.camera_id}>"


# ---------------------------------------------------------------------------
# CoverageScore
# ---------------------------------------------------------------------------

class CoverageScore(db.Model):
    __tablename__ = "coverage_scores"
    __table_args__ = (
        db.UniqueConstraint(
            "property_id", "season_id",
            name="uq_coverage_score_property_season",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    season_id = db.Column(
        db.Integer, db.ForeignKey("seasons.id"), nullable=False
    )
    overall_score = db.Column(db.Float)  # 0-100
    density_score = db.Column(db.Float)
    diversity_score = db.Column(db.Float)
    distribution_score = db.Column(db.Float)
    temporal_score = db.Column(db.Float)
    grade = db.Column(db.String(2))  # A through F
    recommendations = db.Column(db.Text)  # JSON array
    calculated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CoverageScore property={self.property_id} grade={self.grade}>"


# ---------------------------------------------------------------------------
# ShareCard
# ---------------------------------------------------------------------------

class ShareCard(db.Model):
    __tablename__ = "share_cards"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    species_key = db.Column(db.String(80))
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    season_id = db.Column(
        db.Integer, db.ForeignKey("seasons.id"), nullable=False
    )
    card_image_path = db.Column(db.String(500))
    share_token = db.Column(
        db.String(64), unique=True, default=lambda: uuid.uuid4().hex
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<ShareCard {self.share_token[:8]}>"


# ---------------------------------------------------------------------------
# DeerIndividual — re-ID tracked deer
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ProcessingJob — persisted upload/processing jobs
# ---------------------------------------------------------------------------

class ProcessingJob(db.Model):
    """Tracks upload processing jobs across server restarts."""
    __tablename__ = "processing_jobs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(8), unique=True, nullable=False, index=True)
    # Property-scoped link (nullable — pre-property-scoping jobs have neither).
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=True, index=True
    )
    upload_id = db.Column(
        db.Integer, db.ForeignKey("uploads.id"), nullable=True, index=True
    )
    property_name = db.Column(db.String(200))
    state = db.Column(db.String(2))
    status = db.Column(db.String(20), default="queued", index=True)  # queued/processing/classifying/reporting/complete/error
    error_message = db.Column(db.Text)
    n_photos = db.Column(db.String(20))
    n_species = db.Column(db.Integer)
    n_events = db.Column(db.String(20))
    # Legacy filesystem paths (kept for backward compat, read by older jobs).
    report_path = db.Column(db.String(500))
    appendix_path = db.Column(db.String(500))
    # Object-storage keys (Spaces). Preferred over *_path going forward.
    zip_key = db.Column(db.String(500))          # uploaded ZIP location
    report_key = db.Column(db.String(500))       # generated PDF location
    appendix_key = db.Column(db.String(500))     # events CSV location
    # Worker claim fields (DB-polling job queue).
    worker_id = db.Column(db.String(64))         # hostname of worker that claimed job
    claimed_at = db.Column(db.DateTime)
    demo = db.Column(db.Boolean, default=False)  # demo jobs run inline in web
    species_json = db.Column(db.Text)  # JSON array of species stats
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)

    def to_dict(self):
        import json
        d = {
            "job_id": self.job_id,
            "property_name": self.property_name,
            "status": self.status,
            "error_message": self.error_message,
            "n_photos": self.n_photos,
            "n_species": self.n_species,
            "n_events": self.n_events,
            "report_path": self.report_path,
            "appendix_path": self.appendix_path,
            "zip_key": self.zip_key,
            "report_key": self.report_key,
            "appendix_key": self.appendix_key,
            "species": json.loads(self.species_json) if self.species_json else [],
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }
        return d

    def __repr__(self):
        return f"<ProcessingJob {self.job_id} status={self.status}>"


class DeerIndividual(db.Model):
    """A recognized individual deer tracked via re-identification."""
    __tablename__ = "deer_individuals"

    id = db.Column(db.Integer, primary_key=True)
    individual_id = db.Column(db.String(20), unique=True, nullable=False)  # DEER-a3f8c2
    property_id = db.Column(
        db.Integer, db.ForeignKey("properties.id"), nullable=False
    )
    species_key = db.Column(db.String(80), nullable=False)
    display_name = db.Column(db.String(120))  # User-assigned, e.g. "Split G2"
    sex = db.Column(db.String(10))  # buck / doe / unknown
    age_class = db.Column(db.String(20))  # spike, 2.5yr, 3.5yr, 4.5yr+, unknown
    first_seen = db.Column(db.DateTime)
    last_seen = db.Column(db.DateTime)
    sighting_count = db.Column(db.Integer, default=0)
    profile_photo_url = db.Column(db.String(500))  # Best photo for display
    notes = db.Column(db.Text)
    is_confirmed = db.Column(db.Boolean, default=False)  # User confirmed
    # Centroid embedding stored as JSON array of floats
    centroid_embedding = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    sightings = db.relationship("DeerSighting", backref="individual", lazy="dynamic")

    def __repr__(self):
        name = self.display_name or self.individual_id
        return f"<DeerIndividual {name}>"


# ---------------------------------------------------------------------------
# DeerSighting — individual observation record
# ---------------------------------------------------------------------------

class DeerSighting(db.Model):
    """A single observation of a tracked individual deer."""
    __tablename__ = "deer_sightings"

    id = db.Column(db.Integer, primary_key=True)
    individual_id = db.Column(
        db.String(20), db.ForeignKey("deer_individuals.individual_id"), nullable=False
    )
    image_filename = db.Column(db.String(255), nullable=False)
    camera_id = db.Column(db.String(50))  # CAM-F01
    timestamp = db.Column(db.DateTime)
    confidence = db.Column(db.Float)  # Re-ID cosine similarity
    species_key = db.Column(db.String(80))
    is_confirmed = db.Column(db.Boolean, default=False)  # User confirmed match
    photo_url = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DeerSighting {self.individual_id} @ {self.camera_id}>"
