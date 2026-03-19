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

# ---------------------------------------------------------------------------
# API keys — never written to disk
# ---------------------------------------------------------------------------
ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")

# ---------------------------------------------------------------------------
# Claude model
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-20250514"

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
