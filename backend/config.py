"""
Central configuration — all paths relative to project root, all secrets from env.
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# backend/config.py lives one level below the project root
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

DATA_DIR      = PROJECT_ROOT / "data"
SCHEMAS_DIR   = PROJECT_ROOT / "schemas" / "prism"
DB_PATH       = DATA_DIR / "db" / "edgar_extraction.db"
FILINGS_DIR   = DATA_DIR / "filings"
EXPORTS_DIR   = DATA_DIR / "exports"
LOGS_DIR      = PROJECT_ROOT / "logs"

PRISM_SCHEMA_FILE    = SCHEMAS_DIR / "prism-v1.schema.json"
CUSIP_MAPPING_FILE   = SCHEMAS_DIR / "CUSIP_PRISM_Mapping.xlsx"
PRISM_SCHEMA_URL         = os.environ.get("PRISM_SCHEMA_URL", "http://10.10.21.57:30080/api/schema/json")
PRISM_SCHEMA_PENDING_DIR = SCHEMAS_DIR / "pending"
PRISM_SCHEMA_ARCHIVE_DIR = SCHEMAS_DIR / "archive"

# ---------------------------------------------------------------------------
# API keys — never written to disk
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Microsoft Entra ID (Azure AD) — SSO
# ---------------------------------------------------------------------------
AZURE_TENANT_ID: str = os.environ.get("AZURE_TENANT_ID", "")
AZURE_CLIENT_ID: str = os.environ.get("AZURE_CLIENT_ID", "")


# ---------------------------------------------------------------------------
# Claude model registry
#
# Pricing in USD per million tokens.
# cache_write_per_m = 1.25× input rate (cache population)
# cache_read_per_m  = 0.10× input rate (cache hit)
#
# Add newer models here — the Admin UI and cost calculations derive from this dict.
# ---------------------------------------------------------------------------
CLAUDE_MODEL_REGISTRY: dict[str, dict] = {
    "claude-sonnet-4-6": {
        "display_name":       "Claude Sonnet 4.6 (latest)",
        "input_price_per_m":  3.00,
        "output_price_per_m": 15.00,
        "cache_write_per_m":  3.75,
        "cache_read_per_m":   0.30,
        "context_tokens":     1_000_000,
        "note": "1M context window. Training cutoff Jan 2026.",
    },
    "claude-sonnet-4-5-20250929": {
        "display_name":       "Claude Sonnet 4.5",
        "input_price_per_m":  3.00,
        "output_price_per_m": 15.00,
        "cache_write_per_m":  3.75,
        "cache_read_per_m":   0.30,
        "context_tokens":     200_000,
        "note": "200k context. Extended to 1M via beta header (tokens >200k priced at $6/M).",
    },
    "claude-sonnet-4-20250514": {
        "display_name":       "Claude Sonnet 4",
        "input_price_per_m":  3.00,
        "output_price_per_m": 15.00,
        "cache_write_per_m":  3.75,
        "cache_read_per_m":   0.30,
        "context_tokens":     200_000,
        "note": "Original project default. Training cutoff March 2025.",
    },
}

CLAUDE_MODEL_DEFAULT = "claude-sonnet-4-6"
CLAUDE_MODEL = CLAUDE_MODEL_DEFAULT   # backward-compat alias; prefer CLAUDE_MODEL_DEFAULT in new code

# Maximum characters of filing HTML sent to Claude (manages token cost).
# Large filings can be 2–10 MB; we truncate the stripped text.
MAX_FILING_CHARS = 120_000

# Characters of stripped filing text sent in the FIRST classification pass.
# The cover page (product title + bullet points) is almost always within 4 K
# and is the strongest classification signal.  A second targeted pass is made
# if stage-1 confidence falls below CLASSIFICATION_CONFIDENCE_THRESHOLD.
CLASSIFICATION_CHARS = 4_000

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75   # below → stage-2 pass / needs_review
CLASSIFICATION_MIN_CONFIDENCE       = 0.60   # below this → force "unknown" regardless
CLASSIFICATION_GATE_CONFIDENCE      = 0.80   # below this → needs_classification_review, blocks extraction
EXTRACTION_CONFIDENCE_THRESHOLD     = 0.80   # below → field highlighted in UI

# ---------------------------------------------------------------------------
# Section-by-section extraction
# ---------------------------------------------------------------------------
SECTIONED_EXTRACTION: bool = False       # set True (or env SECTIONED_EXTRACTION=true) to enable

# Per-section text window sizes (characters of stripped filing text per section call)
SECTION_MAX_CHARS_IDENTIFIERS    = 8_000
SECTION_MAX_CHARS_PRODUCT        = 15_000
SECTION_MAX_CHARS_UNDERLYING     = 12_000
SECTION_MAX_CHARS_PROTECTION     = 10_000  # barrier + downsideRisk (renamed from BARRIER)
SECTION_MAX_CHARS_AUTOCALL       = 10_000
SECTION_MAX_CHARS_COUPON         = 10_000
SECTION_MAX_CHARS_PARTIES        = 8_000

# Minimum confidence delta to prefer a section result over a prior value for the same field
SECTION_MERGE_CONFIDENCE_DELTA   = 0.15

# ---------------------------------------------------------------------------
# EDGAR
# ---------------------------------------------------------------------------
# SEC EDGAR fair-access policy requires a meaningful User-Agent with org name + email.
# Format: "CompanyName ToolName contact@company.com"
# Exceeding 10 req/sec per IP may result in blocks. Off-peak (21:00–06:00 ET) for bulk runs.
EDGAR_USER_AGENT  = "LuchtProbstAssociates EDGAR-Extraction-Mapping admin@lpa-research.com"
EDGAR_RATE_LIMIT_DELAY = 0.20   # seconds between requests (~5 req/s, well below 10 req/s cap)
EDGAR_RETRY_MAX        = 4
EDGAR_RETRY_BASE_DELAY = 2.0    # seconds, doubles on each retry (max ~30 s)

# ---------------------------------------------------------------------------
# Underlying Data Module
# ---------------------------------------------------------------------------
UNDERLYING_FIELD_CONFIG_FILE    = PROJECT_ROOT / "files" / "underlying_field_config.yaml"
COMPANY_TICKERS_CACHE_FILE      = PROJECT_ROOT / "files" / "company_tickers_cache.json"
COMPANY_TICKERS_CACHE_TTL       = 7 * 24 * 3600          # 7 days in seconds
COMPANY_TICKERS_URL             = "https://www.sec.gov/files/company_tickers.json"

OPENFIGI_API_URL                = "https://api.openfigi.com/v3/mapping"
OPENFIGI_RATE_LIMIT_DELAY       = 2.5                     # seconds (~25 req/min free tier)

MARKET_DATA_PRICE_SERIES_YEARS  = 5                       # years of daily history to store
UNDERLYING_INGEST_MAX_CSV_ROWS  = 500
UNDERLYING_JOB_POLL_INTERVAL    = 3                       # seconds (used by frontend)

# Characters of stripped annual-report text passed to the Tier 2 LLM extraction
# prompt.  Used as the fallback window when Item 1 Business cannot be located in
# the full filing text (e.g. 20-F filers with a different section structure).
UNDERLYING_EXTRACTION_CHARS     = 8_000

# Smart Item 1 / Business section window extraction (10-K / 20-F).
# find_item1_window() searches the full downloaded filing text, locates the
# "ITEM 1  BUSINESS" heading and returns a focused window instead of the first
# UNDERLYING_EXTRACTION_CHARS chars (which often cover only the table of
# contents and forward-looking-statement disclaimers for large-cap filers).
UNDERLYING_ITEM1_CONTEXT_BEFORE = 300    # chars of context kept before the header
UNDERLYING_ITEM1_WINDOW_CHARS   = 6_000  # chars extracted after the Item 1 header

# Characters of 424B2 filing text searched when applying the level-3 fallback
# for brief_description (last resort when yfinance and 10-K LLM both fail).
UNDERLYING_424B2_SEARCH_CHARS   = 20_000

# Filing-deadline days by SEC filer category for currentness checks.
# Keys must match the `category` field in EDGAR submissions JSON (case-insensitive compare).
FILING_DEADLINE_DAYS: dict[str, dict[str, int | None]] = {
    "large accelerated filer":  {"10-K": 60,  "10-Q": 40, "20-F": 120, "NT_EXTENSION": 15},
    "accelerated filer":        {"10-K": 75,  "10-Q": 40, "20-F": 120, "NT_EXTENSION": 15},
    "non-accelerated filer":    {"10-K": 90,  "10-Q": 45, "20-F": 120, "NT_EXTENSION": 15},
    "smaller reporting company":{"10-K": 90,  "10-Q": 45, "20-F": 120, "NT_EXTENSION": 15},
    # Foreign private issuers file 20-F only — no 10-Q requirement.
    # None signals the currentness engine to skip the 10-Q check entirely.
    "foreign private issuer":   {"10-K": 120, "10-Q": None, "20-F": 120, "NT_EXTENSION": 15},
}
# Fallback when category is not recognised
FILING_DEADLINE_DAYS_DEFAULT: dict[str, int] = {
    "10-K": 90, "10-Q": 45, "20-F": 120, "NT_EXTENSION": 15,
}

# Tolerance (days) when matching period-end dates to account for 52/53-week fiscal years
CURRENTNESS_PERIOD_TOLERANCE_DAYS = 7

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Allow env override: SECTIONED_EXTRACTION=true
import os as _os
if _os.environ.get("SECTIONED_EXTRACTION", "").lower() == "true":
    SECTIONED_EXTRACTION = True


def filing_folder(accession_number: str) -> Path:
    """Absolute path to the folder for a specific filing."""
    return FILINGS_DIR / accession_number.replace("-", "")


def ensure_dirs() -> None:
    """Create all required data directories if they don't exist."""
    for d in (DATA_DIR / "db", FILINGS_DIR, EXPORTS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def filing_deadlines(category: str) -> dict[str, int]:
    """Return the filing deadline config for a given filer category (case-insensitive).

    Falls back to *FILING_DEADLINE_DAYS_DEFAULT* when the category is unrecognised.
    """
    return FILING_DEADLINE_DAYS.get(category.lower(), FILING_DEADLINE_DAYS_DEFAULT)
