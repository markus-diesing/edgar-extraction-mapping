"""
SQLAlchemy setup, ORM models, and database initialisation.

All tables mirror the schema defined in DATA_MODEL.md exactly.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
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


# ---------------------------------------------------------------------------
# Underlying Data Module — ORM models
# ---------------------------------------------------------------------------

class UnderlyingSecurity(Base):
    """
    Master record for one underlying reference security (one row per share class).

    A company with multiple listed classes (e.g. Alphabet GOOGL / GOOG) produces
    two separate rows sharing the same ``cik`` but with different ``ticker`` values.
    The ``UniqueConstraint("cik", "ticker")`` enforces this de-duplication.
    """
    __tablename__ = "underlying_securities"

    id                       = Column(String, primary_key=True, default=_uuid)

    # ── Identification ────────────────────────────────────────────────────────
    cik                      = Column(String, index=True)
    ticker                   = Column(String, index=True)
    ticker_bb                = Column(String)           # Bloomberg ticker (user-supplied)
    all_tickers              = Column(Text)             # JSON array: all tickers for this CIK (incl. preferred/note series)
    source_identifier        = Column(String)           # raw value the user typed
    source_identifier_type   = Column(String)           # ticker|isin|cusip|cik|name|bb_ticker

    # ── Company metadata (Tier 1 — submissions API) ───────────────────────────
    company_name             = Column(String)
    legal_name               = Column(String)           # registrant name from 10-K cover (Tier 2 LLM)
    share_class_name         = Column(String)           # from 10-K cover page
    share_type               = Column(String)           # derived: "Domestic Common Stock" | "ADR" | …
    reporting_form           = Column(String)           # "10-K" | "20-F" | "40-F"
    filer_category           = Column(String)
    fiscal_year_end          = Column(String)           # MMDD, e.g. "0630"
    exchange                 = Column(String)
    sic_code                 = Column(String)
    sic_description          = Column(String)
    state_of_incorporation   = Column(String)
    entity_type              = Column(String)           # raw from submissions
    adr_flag                 = Column(Boolean, default=False)

    # ── Filing references ─────────────────────────────────────────────────────
    last_10k_accession       = Column(String)
    last_10k_filed           = Column(String)           # ISO date YYYY-MM-DD
    last_10k_period          = Column(String)           # report period end date
    last_10q_accession       = Column(String)
    last_10q_filed           = Column(String)
    last_10q_period          = Column(String)

    # ── Currentness (computed from submissions data) ──────────────────────────
    current_status           = Column(String)           # current|late_nt|delinquent|unknown
    nt_flag                  = Column(Boolean, default=False)
    next_expected_filing     = Column(String)           # ISO date of next required form
    next_expected_form       = Column(String)           # "10-K" | "10-Q" | "20-F"

    # ── XBRL structured facts (Tier 1) ────────────────────────────────────────
    shares_outstanding       = Column(Float)
    shares_outstanding_date  = Column(String)
    public_float_usd         = Column(Float)
    public_float_date        = Column(String)

    # ── Market data (Tier 3 — yfinance, user-editable) ───────────────────────
    closing_value            = Column(Float)
    closing_value_date       = Column(String)
    initial_value            = Column(Float)
    initial_value_date       = Column(String)           # date the user chose for lookup
    hist_data_series         = Column(Text)             # JSON: [{"date": …, "close": …}, …]
    market_data_source       = Column(String, default="yahoo_finance")
    market_data_fetched_at   = Column(String)

    # ── Tier 2 LLM token usage ────────────────────────────────────────────────
    llm_input_tokens         = Column(Integer)          # prompt tokens for Tier 2 extraction call
    llm_output_tokens        = Column(Integer)          # completion tokens
    llm_cost_usd             = Column(Float)            # estimated cost at list-price rates

    # ── 10-K source text (for human validation) ───────────────────────────────
    last_10k_text            = Column(Text)             # first UNDERLYING_EXTRACTION_CHARS chars of stripped text
    last_10k_primary_doc     = Column(String)           # primary document filename (e.g. "msft-20250630.htm")

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    # ingested → fetching → fetched → needs_review → approved | archived
    status                   = Column(String, nullable=False, default="ingested", index=True)
    ingest_timestamp         = Column(String, nullable=False, default=_now, index=True)
    last_fetched_at          = Column(String)
    field_config_version     = Column(String)           # config snapshot at ingest time
    fetch_error              = Column(Text)             # last error message if fetch failed

    __table_args__ = (
        # Named constraint so it appears clearly in schema introspection tools.
        # SQLite automatically creates a B-tree index to enforce this constraint,
        # so no separate composite Index is needed for the filter_by(cik=…, ticker=…) hot-path.
        UniqueConstraint("cik", "ticker", name="uq_underlying_cik_ticker"),
    )

    field_results = relationship(
        "UnderlyingFieldResult",
        back_populates="underlying",
        cascade="all, delete-orphan",
    )
    edit_log = relationship(
        "UnderlyingEditLog",
        back_populates="underlying",
        cascade="all, delete-orphan",
    )
    links = relationship(
        "UnderlyingLink",
        back_populates="underlying",
        cascade="all, delete-orphan",
    )


class UnderlyingFieldResult(Base):
    """
    Per-field extracted value for one underlying security.

    Mirrors the shape of ``FieldResult`` used in the extraction pipeline so
    that the same review UI patterns apply. One row per (underlying, field_name).
    """
    __tablename__ = "underlying_field_results"

    id               = Column(String, primary_key=True, default=_uuid)
    underlying_id    = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    field_name       = Column(String, nullable=False)
    extracted_value  = Column(Text)             # JSON-encoded
    confidence_score = Column(Float)            # 1.0 for Tier 1; model score for Tier 2
    source_excerpt   = Column(Text)             # supporting text snippet (Tier 2 only)
    # submissions_api | xbrl_dei | 10k_cover | 10k_item1 | manual | yahoo_finance
    source_type      = Column(String, default="manual")
    is_approximate   = Column(Boolean, default=False)   # True for market data fields
    # pending | accepted | corrected | rejected
    review_status    = Column(String, default="pending")
    reviewed_value   = Column(Text)             # JSON-encoded analyst override
    reviewed_at      = Column(String)
    field_config_version = Column(String)

    __table_args__ = (
        UniqueConstraint("underlying_id", "field_name", name="uq_field_result_underlying_field"),
    )

    underlying = relationship("UnderlyingSecurity", back_populates="field_results")


class UnderlyingEditLog(Base):
    """Audit trail for all review actions on underlying field values."""
    __tablename__ = "underlying_edit_log"

    id             = Column(String, primary_key=True, default=_uuid)
    underlying_id  = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    field_name     = Column(String, nullable=False)
    old_value      = Column(Text)
    new_value      = Column(Text)
    # edited | accepted | rejected | approved | refetched
    action         = Column(String, nullable=False)
    edited_at      = Column(String, nullable=False, default=_now)

    underlying = relationship("UnderlyingSecurity", back_populates="edit_log")


class UnderlyingLink(Base):
    """
    Many-to-many join between 424B2 filings and underlying securities.

    Populated automatically from ``classification_product_features.underlyings``
    when a filing is classified, and also manually via the UI.
    """
    __tablename__ = "underlying_links"

    id             = Column(String, primary_key=True, default=_uuid)
    filing_id      = Column(String, ForeignKey("filings.id"), nullable=False)
    underlying_id  = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    linked_at      = Column(String, nullable=False, default=_now)
    # "classification_features" | "manual"
    link_source    = Column(String, default="manual")

    __table_args__ = (UniqueConstraint("filing_id", "underlying_id"),)

    filing     = relationship("Filing")
    underlying = relationship("UnderlyingSecurity", back_populates="links")


class UnderlyingJob(Base):
    """
    Background ingest job tracker.

    One row per queued ingest request. The frontend polls
    ``GET /api/underlying/jobs/{job_id}`` to follow progress.
    """
    __tablename__ = "underlying_jobs"

    id           = Column(String, primary_key=True, default=_uuid)
    # pending | running | done | error
    status       = Column(String, nullable=False, default="pending")
    total        = Column(Integer, default=0)    # total identifiers queued
    done         = Column(Integer, default=0)    # completed (success + error)
    success      = Column(Integer, default=0)
    errors       = Column(Integer, default=0)
    results      = Column(Text)                  # JSON: [{identifier, underlying_id?, error?}, …]
    created_at   = Column(String, nullable=False, default=_now)
    updated_at   = Column(String, nullable=False, default=_now)


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
    """Create all tables and apply pending Alembic migrations.

    Strategy
    --------
    * **Fresh install** (no ``alembic_version`` table): ``create_all()`` builds
      the complete schema — tables, indexes, and named constraints — from the ORM
      models.  We then *stamp* Alembic at ``head`` so it won't re-apply
      migrations that are already reflected in the schema.
    * **Existing install** (``alembic_version`` present): ``create_all()`` is a
      no-op for existing tables; Alembic's ``upgrade head`` applies any
      outstanding migrations in order.

    The legacy ``_migrate()`` call is kept as a safety net for databases that
    predate Alembic (all its ``ALTER TABLE ADD COLUMN`` operations are idempotent
    and swallow ``OperationalError`` when the column already exists).
    """
    config.ensure_dirs()
    is_fresh = not _alembic_version_exists()
    Base.metadata.create_all(engine)   # idempotent: creates new tables only
    if is_fresh:
        # Stamp without running migrations — create_all() already produced the
        # full schema (including H3 indexes).
        _alembic_stamp("head")
    else:
        # Apply any migrations that haven't been applied yet.
        _alembic_upgrade()
    _migrate()   # legacy ADD COLUMN safety net (all calls are idempotent no-ops)


# ---------------------------------------------------------------------------
# Alembic helpers (imported lazily to avoid circular imports: env.py → database)
# ---------------------------------------------------------------------------

def _alembic_cfg():
    """Return an AlembicConfig pointed at our alembic.ini."""
    from pathlib import Path as _Path
    from alembic.config import Config as _AlembicConfig
    _ini = _Path(__file__).parent / "alembic.ini"
    _cfg = _AlembicConfig(str(_ini))
    _cfg.set_main_option("sqlalchemy.url", f"sqlite:///{config.DB_PATH}")
    return _cfg


def _alembic_upgrade() -> None:
    """Apply all pending Alembic migrations (``alembic upgrade head``)."""
    import logging as _logging
    from alembic import command as _cmd
    _log = _logging.getLogger(__name__)
    try:
        _cmd.upgrade(_alembic_cfg(), "head")
    except Exception as exc:
        _log.error("Alembic upgrade failed: %s", exc, exc_info=True)
        raise


def _alembic_stamp(revision: str) -> None:
    """Stamp the database at *revision* without running migrations."""
    import logging as _logging
    from alembic import command as _cmd
    _log = _logging.getLogger(__name__)
    try:
        _cmd.stamp(_alembic_cfg(), revision)
    except Exception as exc:
        _log.error("Alembic stamp failed: %s", exc, exc_info=True)
        raise


def _alembic_version_exists() -> bool:
    """Return True if the ``alembic_version`` table exists in the database."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'")
        ).scalar()
        return row is not None


def _migrate() -> None:
    """Legacy ADD COLUMN migrations — kept for pre-Alembic databases.

    Each entry is idempotent: SQLite raises ``OperationalError`` if the column
    already exists and we swallow it silently.  New schema changes should be
    added as proper Alembic revision files instead.
    """
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
        # v7 columns — underlying data module
        ("underlying_securities", "fetch_error",                 "TEXT"),
        ("underlying_securities", "next_expected_form",          "TEXT"),
        ("underlying_jobs",       "success",                     "INTEGER"),
        ("underlying_jobs",       "errors",                      "INTEGER"),
        # v8 columns — legal name + LLM token cost tracking
        ("underlying_securities", "legal_name",                  "TEXT"),
        ("underlying_securities", "llm_input_tokens",            "INTEGER"),
        ("underlying_securities", "llm_output_tokens",           "INTEGER"),
        ("underlying_securities", "llm_cost_usd",                "REAL"),
        # v9 columns — 10-K source text for human validation
        ("underlying_securities", "last_10k_text",               "TEXT"),
        ("underlying_securities", "last_10k_primary_doc",        "TEXT"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except OperationalError:
                pass  # column already exists — swallow silently


def get_session() -> Session:
    """
    Return a new SQLAlchemy Session.

    Use as a context manager so the session is automatically closed on exit:

        with database.get_session() as session:
            obj = session.get(Model, pk)
            session.commit()
    """
    return Session(engine)
