"""
SQLAlchemy setup, ORM models, and database initialisation.

All tables mirror the schema defined in DATA_MODEL.md exactly.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
    create_engine, event, text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, relationship

import config


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _db_url() -> str:
    return f"sqlite:///{config.DB_PATH}"


engine = create_engine(
    _db_url(),
    connect_args={"check_same_thread": False},
    echo=False,
)

# Enable WAL mode for better concurrency with FastAPI
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# ORM Models
# ---------------------------------------------------------------------------

class Filing(Base):
    __tablename__ = "filings"

    id                         = Column(String, primary_key=True, default=_uuid)
    cusip                      = Column(String, index=True)
    cik                        = Column(String)
    accession_number           = Column(String, unique=True, nullable=False)
    issuer_name                = Column(String)
    filing_date                = Column(String)          # ISO date YYYY-MM-DD
    edgar_filing_url           = Column(String)
    filing_folder_path         = Column(String)          # relative path
    raw_html_path              = Column(String)          # relative path
    ingest_timestamp           = Column(String, nullable=False, default=_now)
    ingest_started_at          = Column(String)   # when EDGAR download begins
    status                     = Column(String, nullable=False, default="ingested")
    # ingested | classified | needs_classification_review | extracted | needs_review | approved | exported
    payout_type_id             = Column(String)
    classification_confidence  = Column(Float)
    matched_schema_version     = Column(String)
    classified_at              = Column(String)
    classification_title_excerpt      = Column(Text)    # quoted product title from page 1
    classification_product_features   = Column(Text)    # JSON: {type, features, underlyings}

    extraction_results = relationship("ExtractionResult", back_populates="filing", cascade="all, delete-orphan")
    edit_log           = relationship("EditLog", back_populates="filing", cascade="all, delete-orphan")
    classification_feedback = relationship("ClassificationFeedback", back_populates="filing", cascade="all, delete-orphan")


class ExtractionResult(Base):
    __tablename__ = "extraction_results"

    id                   = Column(String, primary_key=True, default=_uuid)
    filing_id            = Column(String, ForeignKey("filings.id"), nullable=False)
    prism_model_id       = Column(String, nullable=False)
    prism_model_version  = Column(String, nullable=False)
    extracted_at         = Column(String, nullable=False, default=_now)
    field_count          = Column(Integer)
    fields_found         = Column(Integer)
    fields_null          = Column(Integer)
    extraction_mode      = Column(String, default="single")  # "single" | "sectioned"

    filing       = relationship("Filing", back_populates="extraction_results")
    field_results = relationship("FieldResult", back_populates="extraction", cascade="all, delete-orphan")


class FieldResult(Base):
    __tablename__ = "field_results"

    id               = Column(String, primary_key=True, default=_uuid)
    extraction_id    = Column(String, ForeignKey("extraction_results.id"), nullable=False)
    filing_id        = Column(String, ForeignKey("filings.id"), nullable=False)
    field_name       = Column(String, nullable=False)   # dot-path, e.g. "barrier.triggerDetails.triggerLevelRelative"
    extracted_value  = Column(Text)                     # JSON-encoded
    confidence_score = Column(Float)
    source_excerpt   = Column(Text)
    not_found        = Column(Integer, default=0)       # 1 if not found
    reviewed_value   = Column(Text)                     # JSON-encoded, set by reviewer
    review_status    = Column(String, default="pending")
    # pending | accepted | corrected | rejected | schema_error
    reviewed_at      = Column(String)
    validation_error = Column(Text)                     # set when value violates schema enum/const
    source           = Column(String, default="llm")    # llm | html_table | registry | html_title

    __table_args__ = (UniqueConstraint("extraction_id", "field_name"),)

    extraction = relationship("ExtractionResult", back_populates="field_results")


class EditLog(Base):
    __tablename__ = "edit_log"

    id         = Column(String, primary_key=True, default=_uuid)
    filing_id  = Column(String, ForeignKey("filings.id"), nullable=False)
    field_name = Column(String, nullable=False)
    old_value  = Column(Text)
    new_value  = Column(Text)
    action     = Column(String, nullable=False)  # edited | accepted | rejected | approved | exported
    edited_at  = Column(String, nullable=False, default=_now)

    filing = relationship("Filing", back_populates="edit_log")


class ClassificationFeedback(Base):
    """
    Stores manual corrections to classification results.
    Used to build a feedback loop: approved corrections become few-shot
    examples in future classification prompts.
    """
    __tablename__ = "classification_feedback"

    id                    = Column(String, primary_key=True, default=_uuid)
    filing_id             = Column(String, ForeignKey("filings.id"), nullable=False)
    original_payout_type  = Column(String, nullable=False)   # what the classifier returned
    corrected_payout_type = Column(String, nullable=False)   # what the reviewer says it is
    correction_reason     = Column(Text)                     # free text from reviewer
    corrected_by          = Column(String)                   # reviewer identifier (future auth)
    corrected_at          = Column(String, nullable=False, default=_now)
    used_as_example       = Column(Boolean, default=False)   # True once included in prompts

    filing = relationship("Filing", back_populates="classification_feedback")


class LabelMissLog(Base):
    """
    Tracks label strings that html_extractor saw in Key Terms tables but could
    not resolve to a PRISM field path.  Used to surface unmapped labels in the
    Expert > Label Map editor so the user can add them without editing YAML by hand.
    """
    __tablename__ = "label_miss_log"

    id               = Column(String, primary_key=True, default=_uuid)
    label_norm       = Column(String, nullable=False, unique=True)  # normalized (lowercase, stripped)
    label_raw        = Column(String, nullable=False)               # representative raw form
    sample_value     = Column(String)                               # sample value from the filing
    issuer_name      = Column(String)                               # most recent issuer
    filing_id        = Column(String)                               # most recent filing
    occurrence_count = Column(Integer, default=1)
    first_seen_at    = Column(String, nullable=False, default=_now)
    last_seen_at     = Column(String, nullable=False, default=_now)
    dismissed        = Column(Integer, default=0)  # 1 = user dismissed without adding a mapping


class ApiUsageLog(Base):
    __tablename__ = "api_usage_log"

    id                = Column(String, primary_key=True, default=_uuid)
    filing_id         = Column(String, ForeignKey("filings.id"), nullable=True)
    call_type         = Column(String, nullable=False)   # classify | extract
    model             = Column(String, nullable=False)
    prompt_tokens      = Column(Integer)
    completion_tokens  = Column(Integer)
    duration_seconds   = Column(Float)    # wall-clock time for the API call
    cache_read_tokens  = Column(Integer)  # tokens served from prompt cache (0.10× input rate)
    cache_write_tokens = Column(Integer)  # tokens written to prompt cache  (1.25× input rate)
    called_at          = Column(String, nullable=False, default=_now)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

def init_db() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    config.ensure_dirs()
    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Add new columns to existing tables without dropping data."""
    migrations = [
        # v1 columns
        ("filings",       "ingest_started_at",                  "TEXT"),
        ("api_usage_log", "duration_seconds",                   "REAL"),
        # v2 columns — classification audit trail
        ("filings",       "classification_title_excerpt",        "TEXT"),
        ("filings",       "classification_product_features",     "TEXT"),
        # v2 columns — extraction schema validation
        ("field_results", "validation_error",                    "TEXT"),
        # v3 columns — section-by-section extraction
        ("extraction_results", "extraction_mode",                "TEXT"),
        # v4 columns — prompt caching token tracking
        ("api_usage_log",      "cache_read_tokens",              "INTEGER"),
        ("api_usage_log",      "cache_write_tokens",             "INTEGER"),
        # v5 columns — hybrid extraction source tracking
        ("field_results",      "source",                         "TEXT"),
        # v6 columns — label miss log deduplication
        ("label_miss_log",     "dismissed",                      "INTEGER"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except OperationalError:
                pass  # column already exists — SQLite raises OperationalError on duplicate ADD COLUMN


def get_session() -> Session:
    """
    Return a new SQLAlchemy Session.

    Use as a context manager so the session is automatically closed on exit:

        with database.get_session() as session:
            obj = session.get(Model, pk)
            session.commit()
    """
    return Session(engine)
