# DATA_MODEL.md
# EDGAR Extraction & Mapping — Data Model

> **Audience:** Claude Code (development agent)
> **Last updated:** 2026-03-19

---

## 1. Overview

All application state is stored in a single **SQLite** database at `data/db/edgar_extraction.db`. Raw filing HTML is stored as flat files under `data/raw/`. Exports are written to `data/exports/`.

SQLAlchemy (with SQLite dialect) is used as the ORM. Alembic is used for schema migrations.

---

## 2. SQLite Schema

### 2.1 `filings` table

Stores one record per ingested EDGAR filing.

```sql
CREATE TABLE filings (
    id                  TEXT PRIMARY KEY,        -- UUID
    cusip               TEXT,
    cik                 TEXT,
    accession_number    TEXT UNIQUE NOT NULL,
    issuer_name         TEXT,
    filing_date         TEXT,                    -- ISO date string YYYY-MM-DD
    edgar_filing_url    TEXT,                    -- original EDGAR URL
    filing_folder_path  TEXT,                    -- relative: data/filings/{accession_no_dashes}/
    raw_html_path       TEXT,                    -- relative: data/filings/{accession_no_dashes}/raw.html
    ingest_timestamp    TEXT NOT NULL,           -- ISO datetime
    status              TEXT NOT NULL DEFAULT 'ingested',
                        -- enum: ingested | classified | extracted | approved | exported
    payout_type_id      TEXT,                    -- set after classification
    classification_confidence  REAL,
    matched_schema_version     TEXT,
    classified_at       TEXT                     -- ISO datetime
);
```

### 2.2 `extraction_results` table

Stores the full extraction output for a filing. One record per filing.

```sql
CREATE TABLE extraction_results (
    id                  TEXT PRIMARY KEY,        -- UUID
    filing_id           TEXT NOT NULL REFERENCES filings(id),
    prism_model_id      TEXT NOT NULL,
    prism_model_version TEXT NOT NULL,
    extracted_at        TEXT NOT NULL,           -- ISO datetime
    field_count         INTEGER,
    fields_found        INTEGER,
    fields_null         INTEGER
);
```

### 2.3 `field_results` table

Stores one record per extracted field, per filing.

```sql
CREATE TABLE field_results (
    id                  TEXT PRIMARY KEY,        -- UUID
    extraction_id       TEXT NOT NULL REFERENCES extraction_results(id),
    filing_id           TEXT NOT NULL REFERENCES filings(id),
    field_name          TEXT NOT NULL,           -- PRISM field identifier
    extracted_value     TEXT,                    -- JSON-encoded; null if not found
    confidence_score    REAL,
    source_excerpt      TEXT,                    -- text fragment used for extraction
    not_found           INTEGER DEFAULT 0,       -- 1 if field was not found in filing
    reviewed_value      TEXT,                    -- JSON-encoded; set by human reviewer
    review_status       TEXT DEFAULT 'pending',
                        -- enum: pending | accepted | corrected | rejected
    reviewed_at         TEXT,                    -- ISO datetime
    UNIQUE(extraction_id, field_name)
);
```

### 2.4 `edit_log` table

Audit trail for all human edits.

```sql
CREATE TABLE edit_log (
    id                  TEXT PRIMARY KEY,        -- UUID
    filing_id           TEXT NOT NULL REFERENCES filings(id),
    field_name          TEXT NOT NULL,
    old_value           TEXT,
    new_value           TEXT,
    action              TEXT NOT NULL,           -- edited | accepted | rejected | approved | exported
    edited_at           TEXT NOT NULL            -- ISO datetime
);
```

### 2.5 `api_usage_log` table

Tracks Claude API calls for local budget awareness (NFR-6).

```sql
CREATE TABLE api_usage_log (
    id                  TEXT PRIMARY KEY,        -- UUID
    filing_id           TEXT REFERENCES filings(id),
    call_type           TEXT NOT NULL,           -- classify | extract
    model               TEXT NOT NULL,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    called_at           TEXT NOT NULL            -- ISO datetime
);
```

---

## 3. PRISM Schema File Format

All PRISM models are defined in a single file: `schemas/prism/prism-v1.schema.json`. The application loads models dynamically from this file at startup via `schema_loader.py`. No code changes are required when new models are added — replace or update the schema file.

**Example of a single model's field structure within the schema:**
```json
{
  "payout_type_id": "barrier_reverse_convertible",
  "payout_type_label": "Barrier Reverse Convertible",
  "version": "1",
  "description": "Capital-at-risk product with conditional coupon and barrier observation",
  "fields": [
    {
      "field_name": "cusip",
      "label": "CUSIP",
      "data_type": "string",
      "required": true,
      "description": "9-character CUSIP identifier",
      "example": "38148P2E6"
    },
    {
      "field_name": "issuer_name",
      "label": "Issuer Name",
      "data_type": "string",
      "required": true,
      "description": "Full legal name of the issuing entity",
      "example": "Goldman Sachs Finance Corp International Ltd"
    },
    {
      "field_name": "underlier_name",
      "label": "Underlier Name",
      "data_type": "string",
      "required": true,
      "description": "Name of the reference asset or index",
      "example": "S&P 500 Index"
    },
    {
      "field_name": "underlier_ticker",
      "label": "Underlier Ticker",
      "data_type": "string",
      "required": false,
      "description": "Bloomberg or exchange ticker of the underlier",
      "example": "SPX"
    },
    {
      "field_name": "barrier_level_pct",
      "label": "Barrier Level (%)",
      "data_type": "number",
      "required": true,
      "description": "Barrier level as percentage of initial underlier level",
      "example": 70.0
    },
    {
      "field_name": "coupon_rate_pa_pct",
      "label": "Coupon Rate p.a. (%)",
      "data_type": "number",
      "required": true,
      "description": "Annual coupon rate as a percentage",
      "example": 8.5
    },
    {
      "field_name": "trade_date",
      "label": "Trade Date",
      "data_type": "date",
      "required": true,
      "description": "Date the product was priced / executed (YYYY-MM-DD)",
      "example": "2026-03-10"
    },
    {
      "field_name": "maturity_date",
      "label": "Maturity Date",
      "data_type": "date",
      "required": true,
      "description": "Final maturity / expiry date (YYYY-MM-DD)",
      "example": "2027-03-15"
    },
    {
      "field_name": "tenor_months",
      "label": "Tenor (months)",
      "data_type": "integer",
      "required": false,
      "description": "Product tenor in months (derived from trade/maturity dates if not stated)",
      "example": 12
    },
    {
      "field_name": "principal_amount_usd",
      "label": "Principal Amount (USD)",
      "data_type": "number",
      "required": false,
      "description": "Face value / notional of the product in USD",
      "example": 1000.0
    },
    {
      "field_name": "barrier_observation",
      "label": "Barrier Observation Type",
      "data_type": "string",
      "required": false,
      "description": "How the barrier is observed: European (at maturity only) or American (continuous/daily)",
      "example": "European"
    },
    {
      "field_name": "payment_at_maturity",
      "label": "Payment at Maturity (description)",
      "data_type": "string",
      "required": false,
      "description": "Plain-language description of the payout at maturity",
      "example": "If barrier not breached: 100% + coupons. If breached: underlier performance."
    }
  ]
}
```

> The `prism-v1.schema.json` file is present in `schemas/prism/`. When Chroma publishes a new schema version, replace this file — no code changes are required.

---

## 4. Export Format

Exports are written to `data/exports/` as JSON files. One file per approved filing.

**Filename:** `{cusip}_{payout_type_id}_{approved_date}.json`
Example: `38148P2E6_barrier_reverse_convertible_2026-03-18.json`

**JSON export structure:**
```json
{
  "export_metadata": {
    "cusip": "38148P2E6",
    "accession_number": "0001234567-26-000001",
    "issuer_name": "Goldman Sachs Finance Corp International Ltd",
    "filing_date": "2026-03-15",
    "payout_type_id": "barrier_reverse_convertible",
    "prism_schema_version": "1",
    "classification_confidence": 0.94,
    "extracted_at": "2026-03-18T10:23:11Z",
    "approved_at": "2026-03-18T11:05:44Z",
    "export_generated_at": "2026-03-18T11:06:01Z"
  },
  "fields": {
    "cusip": "38148P2E6",
    "issuer_name": "Goldman Sachs Finance Corp International Ltd",
    "underlier_name": "S&P 500 Index",
    "underlier_ticker": "SPX",
    "barrier_level_pct": 70.0,
    "coupon_rate_pa_pct": 8.5,
    "trade_date": "2026-03-10",
    "maturity_date": "2027-03-15",
    "tenor_months": 12,
    "principal_amount_usd": 1000.0,
    "barrier_observation": "European",
    "payment_at_maturity": null
  },
  "field_review_status": {
    "cusip": "accepted",
    "issuer_name": "accepted",
    "underlier_name": "corrected",
    "barrier_level_pct": "accepted",
    "coupon_rate_pa_pct": "accepted",
    "trade_date": "accepted",
    "maturity_date": "accepted",
    "payment_at_maturity": "rejected"
  }
}
```

**CSV export:** A flat CSV is also generated alongside each JSON, with one row per filing containing all field values. Headers are PRISM field names.

---

## 5. Relative Path Conventions

All paths in code and config MUST be relative to the project root (`EDGAR-Extraction_Mapping/`).

| Resource | Relative Path |
|----------|--------------|
| SQLite database | `data/db/edgar_extraction.db` |
| Filing folder (per filing) | `data/filings/{accession_number_no_dashes}/` |
| Raw filing HTML | `data/filings/{accession_number_no_dashes}/raw.html` |
| Filing metadata snapshot | `data/filings/{accession_number_no_dashes}/metadata.json` |
| Filing images (formula graphics, etc.) | `data/filings/{accession_number_no_dashes}/{image_filename}` |
| Filing index page | `data/filings/{accession_number_no_dashes}/index.htm` |
| PRISM schema file | `schemas/prism/prism-v1.schema.json` |
| CUSIP model mapping | `schemas/prism/CUSIP_PRISM_Mapping.xlsx` |
| Financial glossary | `files/financial_glossary.md` |
| Architecture diagram | `files/architecture.drawio` |
| Issuer extraction hints | `files/issuer_extraction_hints.json` |
| Export files (JSON) | `data/exports/{cusip}_{payout_type}_{date}.json` |
| Export files (CSV) | `data/exports/{cusip}_{payout_type}_{date}.csv` |
| Application logs | `logs/app.log` |

**`metadata.json` structure** (written at ingest time, updated when images are (re-)fetched):
```json
{
  "cusip": "...",
  "cik": "...",
  "accession_number": "...",
  "issuer_name": "...",
  "filing_date": "...",
  "edgar_filing_url": "...",
  "ingest_timestamp": "...",
  "images": ["image1.png", "image2.gif"]
}
```
The `"images"` key lists filenames of formula/chart images downloaded from the same EDGAR filing folder and saved alongside `raw.html`. It is an empty list `[]` if no images were found. Missing from metadata of filings ingested before image-download support was added — use `POST /api/filings/{id}/fetch-images` or `scripts/backfill_images.py` to populate.

Path resolution in `backend/config.py`:
```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent  # EDGAR-Extraction_Mapping/
DATA_DIR = PROJECT_ROOT / "data"
SCHEMAS_DIR = PROJECT_ROOT / "schemas" / "prism"
CUSIP_MAPPING_FILE = SCHEMAS_DIR / "CUSIP_PRISM_Mapping.xlsx"
SCHEMA_FILE = SCHEMAS_DIR / "prism-v1.schema.json"
DB_PATH = DATA_DIR / "db" / "edgar_extraction.db"
FILINGS_DIR = DATA_DIR / "filings"   # one subfolder per accession number
EXPORTS_DIR = DATA_DIR / "exports"
FILES_DIR = PROJECT_ROOT / "files"
LOGS_DIR = PROJECT_ROOT / "logs"

def filing_folder(accession_number: str) -> Path:
    """Returns the folder path for a specific filing (accession number, dashes stripped)."""
    return FILINGS_DIR / accession_number.replace("-", "")
```

---

## 6. CUSIP-to-PRISM Model Mapping

The file `schemas/prism/CUSIP_PRISM_Mapping.xlsx` provides a reference table mapping known CUSIPs to their corresponding PRISM payout type. The backend reads this file at startup (`schema_loader.load_cusip_mapping()`) and uses it to:

1. **Pre-populate the classification hint** — when a queried CUSIP is found in the mapping, pass the mapped payout type as a strong prior to the Claude classification prompt (the AI still validates, but starts with the known type)
2. **Accelerate testing** — CUSIPs in the mapping table are known-good test cases for each payout type

**Expected columns in the xlsx (adapt if actual file differs):**

| Column | Description |
|--------|-------------|
| `cusip` | 9-character CUSIP |
| `payout_type_id` | Matches a `payout_type_id` in the PRISM schema JSON files |
| `issuer_name` | Optional — issuer name for reference |
| `notes` | Optional — any additional context |

Parse this file using `openpyxl` in Python. Load once at startup and cache in memory.

---

## 7. PRISM Documentation Reference

The authoritative PRISM documentation lives in the LPA Azure DevOps wiki:

```
https://dev.azure.com/l-p-a/PRISM/_wiki/wikis/PRISM.wiki/15946/Basics-Important-Links
```

> **Note for Claude Code:** This wiki requires LPA authentication and cannot be fetched programmatically during the build session. Markus will copy relevant sections into this document or provide them as additional context during the session. Do not attempt to fetch the URL autonomously — ask Markus to provide the relevant PRISM documentation if needed.

Key PRISM concepts relevant to this project (to be expanded as wiki content is shared):
- **Payout type** — the product structure category (e.g., Barrier Reverse Convertible). Each has a distinct PRISM schema.
- **PRISM model** — the versioned field definition for a given payout type, specifying required and optional fields, data types, and valid values.
- **Schema-as-config** — this system loads PRISM models from `schemas/prism/*.json` at runtime. No payout type logic is hardcoded.

---

*End of DATA_MODEL.md*
