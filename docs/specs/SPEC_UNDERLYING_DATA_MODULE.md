# Underlying Data Module — Specification & Technical Plan

**Status:** Planned — not yet implemented
**Last updated:** 2026-04-23
**Author:** Markus / LPA (documented via Claude Code session)
**Session context:** Follows code review, handover package, and requirements discussion sessions

---

## Table of Contents

1. [Purpose & Context](#1-purpose--context)
2. [Regulatory Background — Abbreviated Disclosure](#2-regulatory-background--abbreviated-disclosure)
3. [Confirmed Requirements](#3-confirmed-requirements)
4. [Data Points & Field Definitions](#4-data-points--field-definitions)
5. [Architecture Overview](#5-architecture-overview)
6. [Database Schema](#6-database-schema)
7. [Backend Modules](#7-backend-modules)
8. [API Endpoints](#8-api-endpoints)
9. [Frontend Components](#9-frontend-components)
10. [CSV Ingest Format](#10-csv-ingest-format)
11. [Export Format](#11-export-format)
12. [Key Technical Decisions](#12-key-technical-decisions)
13. [Coding Standards & Conventions](#13-coding-standards--conventions)
14. [Build Sequence & Dependencies](#14-build-sequence--dependencies)
15. [Potential Extensions](#15-potential-extensions)
16. [Open Tasks & Blockers](#16-open-tasks--blockers)

---

## 1. Purpose & Context

### What this module does

The Underlying Data Module is a self-contained extension to the EDGAR Extraction & PRISM Mapping tool. Where the existing pipeline ingests **structured product filings (424B2)** and extracts PRISM schema fields, this module focuses on the **underlying reference securities** those products are written on — equities, ADRs, and foreign-listed shares referenced in the term sheets.

### Why it matters

1. **Reference data for PRISM:** PRISM structured product models include underlying security metadata (name, ticker, exchange, share type). This module provides a maintained, reviewed, and exportable source of that data.
2. **Abbreviated disclosure compliance check:** SEC rules allow structured product issuers to use abbreviated disclosure for underlying stocks — but only when the underlying is "current" in its Exchange Act reporting obligations. This module validates currentness automatically, flagging ineligible underlyings before they become a compliance issue.
3. **Linkage to filings:** Connects extracted underlying metadata to the 424B2 filings that reference each security, enabling traceability in both directions.

### Relationship to the existing system

```
Existing pipeline (424B2):          New module (Underlying Data):
  Ingest 424B2 filing          ←── links ──→  Ingest underlying by identifier
  Classify → PRISM model type                  Fetch 10-K / 10-Q from EDGAR
  Extract PRISM fields                         Check "current" filing status
  Human review + approve                       Extract description + share class
  Export JSON/CSV                              Human review + approve
                                               Export underlying JSON
```

The two pipelines share the EDGAR HTTP client, the SQLite database, the Anthropic client singleton, and the review/approval UI pattern. They are otherwise independent.

---

## 2. Regulatory Background — Abbreviated Disclosure

### The rule

When a 424B2 prospectus supplement references an underlying equity security, the issuing bank may use **abbreviated disclosure** — instead of including full audited financials and business description for the underlying company in the prospectus, it can incorporate by reference the underlying company's own SEC filings (its most recent 10-K and the most recent 10-Q filed thereafter).

This is valid **only when** the underlying company:
1. Has equity securities registered under Section 12(b) or 12(g) of the Exchange Act
2. Is **current** in its reporting obligations — all required 10-K and 10-Q filings made within their respective SEC deadlines
3. Has been a reporting company for at least 12 months

When a company is **delinquent** (missed a filing deadline without an approved NT extension), the abbreviated disclosure mechanism is invalid for that underlying. The issuing bank must either include full disclosure in the prospectus or select a different underlying.

### Why the tool must check both 10-K and 10-Q

The comment from the PRISM team that triggered this requirement: *"info from these forms is very much use-case specific, for example in the specific case of abbreviated disclosure the info is found via a combination of 10-K and 10-Q, and checking their filing characteristics, to verify the issuer is 'current', otherwise you can't link to them."*

This means:
- **10-K** → business description, share class structure, annual audited financials
- **10-Q** → most recent quarterly update; confirms the company has remained current since its last 10-K
- Together they constitute the full disclosure picture available via incorporation by reference

### Filing deadlines by filer category

All inputs (filer category, fiscal year end, actual filing dates) are available directly from `data.sec.gov/submissions/CIK{id}.json` — no scraping or external source needed.

| Filer Category | 10-K Deadline | 10-Q Deadline | NT Extension |
|---|---|---|---|
| Large Accelerated Filer (float ≥ $700M) | FYE + 60 days | Quarter end + 40 days | +15 days |
| Accelerated Filer (float $75M–$700M) | FYE + 75 days | Quarter end + 40 days | +15 days |
| Non-Accelerated Filer | FYE + 90 days | Quarter end + 45 days | +15 days |
| Smaller Reporting Company | FYE + 90 days | Quarter end + 45 days | +15 days |
| Foreign Private Issuer (20-F) | FYE + 120 days | N/A (no 10-Q) | varies |
| Canadian Issuer (40-F) | FYE + 90 days | N/A | varies |

**NT filings:** Form NT 10-K / NT 10-Q are "Notification of Late Filing" forms. Filing an NT grants a 15-day extension and is not itself a delinquency, but it is a warning signal. The tool should flag NT filings without treating them as delinquent.

### "Current" status values

```
current     → All required forms filed within deadline (or NT + 15 days)
late_nt     → Filed within NT extension window; NT was filed in current period
delinquent  → Filing deadline (+ NT extension) passed with no filing on record
unknown     → Insufficient history (<12 months) to make a determination
```

---

## 3. Confirmed Requirements

### 3.1 Functional requirements

| # | Requirement | Notes |
|---|---|---|
| F-01 | Separate "Underlying" tab in the main navigation | Fourth view alongside Filings / Expert / Admin |
| F-02 | Ingest by any of: ticker, ISIN, CUSIP, CIK, Bloomberg ticker, company name | Auto-detect identifier type |
| F-03 | Ingest a single identifier | Via text input in the UI |
| F-04 | Ingest a list from a CSV file | One identifier type per file, type declared in header |
| F-05 | Ingest as bulk text paste | One identifier per line |
| F-06 | Import underlyings from existing filings | Scan `classification_product_features.underlyings` for all classified filings |
| F-07 | Identifier disambiguation | When resolution is ambiguous, present a picker before proceeding |
| F-08 | Multi-class share handling | One record per share class (e.g. GOOGL + GOOG stored separately) |
| F-09 | Async ingest with progress indicator | Background job; UI polls for status |
| F-10 | Fetch 10-K data via EDGAR | Download and extract from primary HTML document |
| F-11 | Fetch 10-Q data via EDGAR | Download most recent 10-Q; used for currentness check + optional data |
| F-12 | Compute currentness status | See §2 — current / late_nt / delinquent / unknown |
| F-13 | Flag 20-F filers in UI | Visual distinction from 10-K filers |
| F-14 | Flag ADRs in UI | Detected from cover page and share class language |
| F-15 | Per-field review workflow | Same accept / correct / reject flow as existing extraction review |
| F-16 | Bulk approve | Approve all accepted fields, move underlying to "approved" status |
| F-17 | Manual re-fetch | Button triggers fresh 10-K/10-Q pull; timestamp shown in UI |
| F-18 | Manual field entry | All fields editable; market data fields are manual-entry with optional pre-fill |
| F-19 | Market data pre-fill (Initial Value) | Date-picker + Fetch button → yfinance close on that date |
| F-20 | Market data pre-fill (Closing Value) | Auto-fetched on ingest and re-fetch via yfinance |
| F-21 | Historical price series | 5-year daily closes stored as JSON; rendered as sparkline |
| F-22 | Configurable field list | Enable/disable fields globally; persisted in YAML config file |
| F-23 | Disabled fields not queried for new records | Existing records retain their data |
| F-24 | Linking: underlying → filings | Show which 424B2 filings reference each underlying |
| F-25 | Linking: filing → underlyings | Show linked underlying records from FilingDetail view |
| F-26 | JSON export (single) | Approved fields for one underlying |
| F-27 | JSON export (bulk) | All approved underlyings as JSON array |
| F-28 | API response format | Export endpoint also usable as a programmatic data source |
| F-29 | Field config accessible to all users | No admin-only restriction for POC |

### 3.2 Non-functional requirements

| # | Requirement |
|---|---|
| NF-01 | All EDGAR HTTP calls reuse existing rate limiter (≤5 req/s, exponential backoff on 429) |
| NF-02 | Anthropic API calls reuse module-level `_get_client()` singleton |
| NF-03 | OpenFIGI API used for ISIN/CUSIP → ticker resolution (free tier, no key required for basic lookups) |
| NF-04 | yfinance used for market data (no API key; `auto_adjust=False` for unadjusted prices) |
| NF-05 | All data stored in the existing SQLite database (new tables only) |
| NF-06 | Async ingest implemented via FastAPI BackgroundTasks + thread pool |
| NF-07 | Volume target: hundreds of underlyings (not thousands — no pagination infrastructure required beyond simple filtering) |
| NF-08 | Market data values carry `is_approximate: true` flag and source label in UI |
| NF-09 | All file paths via `pathlib.Path`; no `os.path` |
| NF-10 | Type hints on all function signatures |
| NF-11 | New tests in `backend/tests/` following existing pytest patterns |

---

## 4. Data Points & Field Definitions

### Field catalogue

Each field has: a `field_name` (used in DB and config), a display label, a data source tier, and whether it is enabled by default.

| field_name | Display Label | Source Tier | Default |
|---|---|---|---|
| `company_name` | Company Name | Tier 1 — submissions API | ✅ |
| `share_class_name` | Share Class (full name) | Tier 2 — 10-K cover page extraction | ✅ |
| `ticker` | Ticker | Tier 1 — submissions API | ✅ |
| `ticker_bb` | Bloomberg Ticker | User input / manual | ✅ |
| `exchange` | Exchange | Tier 1 — submissions API | ✅ |
| `share_type` | Share Type | Tier 1 derived (see logic below) | ✅ |
| `reporting_form` | Filing Form | Tier 1 — submissions API | ✅ |
| `brief_description` | Brief Description | Tier 2 — 10-K Item 1 LLM extraction | ✅ |
| `current_status` | Filing Status | Tier 1 computed (currentness engine) | ✅ |
| `last_10k_period` | Last 10-K Period End | Tier 1 — submissions API | ✅ |
| `last_10k_filed` | Last 10-K Filed | Tier 1 — submissions API | ✅ |
| `last_10q_period` | Last 10-Q Period End | Tier 1 — submissions API | ✅ |
| `last_10q_filed` | Last 10-Q Filed | Tier 1 — submissions API | ✅ |
| `filer_category` | Filer Category | Tier 1 — submissions API | ✅ |
| `sic_code` | SIC Code | Tier 1 — submissions API | ✅ |
| `sic_description` | SIC Description | Tier 1 — submissions API | ✅ |
| `state_of_incorporation` | State of Incorporation | Tier 1 — submissions API | ✅ |
| `shares_outstanding` | Shares Outstanding | Tier 1 — XBRL DEI | ✅ |
| `public_float` | Public Float (USD) | Tier 1 — XBRL DEI | ✅ |
| `initial_value` | Initial Value | Tier 3 — yfinance (manual entry) | ✅ |
| `initial_value_date` | Initial Value Date | User input | ✅ |
| `closing_value` | Closing Value | Tier 3 — yfinance auto-fill | ✅ |
| `closing_value_date` | Closing Value Date | Tier 3 — yfinance auto-fill | ✅ |
| `hist_data_series` | Historical Price Series | Tier 3 — yfinance (5-year daily) | ✅ |
| `adr_flag` | ADR | Tier 2 derived from cover page | ✅ |
| `nt_flag` | NT Filing on Record | Tier 1 — submissions API | ✅ |
| `next_expected_filing` | Next Filing Due | Tier 1 computed | ✅ |
| `fiscal_year_end` | Fiscal Year End | Tier 1 — submissions API | ❌ (expert) |
| `cik` | EDGAR CIK | Tier 1 — submissions API | ❌ (expert) |

### Share type derivation logic

```python
def derive_share_type(entity_type: str, reporting_form: str, adr_flag: bool) -> str:
    if adr_flag:
        return "ADR"
    if reporting_form == "20-F":
        return "Foreign (20-F)"
    if reporting_form == "40-F":
        return "Foreign (40-F / Canadian)"
    if entity_type == "operating":
        return "Domestic Common Stock"
    return "Other"
```

### Market data fields behaviour

- **`initial_value`:** Pre-filled from yfinance using the close on `initial_value_date`. Default `initial_value_date` = first available trading date in yfinance history (approximate IPO date). User can override date and re-fetch. Stored with source `"yahoo_finance"` and flag `is_approximate: true`.
- **`closing_value`:** Auto-fetched on ingest and on every manual re-fetch. Most recent settled close. Source `"yahoo_finance"`, `is_approximate: true`.
- **`hist_data_series`:** 5-year daily closes stored as JSON array `[{"date": "2024-04-23", "close": 412.34}, ...]`. Rendered as a sparkline in the UI. Not shown in the review table (rendered separately as a chart widget).

---

## 5. Architecture Overview

```
backend/
  underlying/
    __init__.py
    router.py                  ← FastAPI router; registered in main.py
    edgar_underlying_client.py ← submissions API, 10-K/10-Q download; extends ingest/edgar_client.py
    identifier_resolver.py     ← any identifier type → CIK (via EDGAR + OpenFIGI)
    currentness.py             ← currentness status calculation engine
    extractor.py               ← LLM extraction: cover page + Item 1 (reuses Anthropic singleton)
    market_data_client.py      ← pluggable interface; YahooFinanceClient as default impl
    field_config.py            ← read/write underlying_field_config.yaml
    background.py              ← async job runner (FastAPI BackgroundTasks + thread pool)

files/
  underlying_field_config.yaml ← ordered field list with enabled/display_name overrides

frontend/src/components/
  UnderlyingPanel.jsx          ← sidebar: list + ingest tabs
  UnderlyingDetail.jsx         ← main panel: field review + currentness widget + links
  UnderlyingFieldConfig.jsx    ← Expert panel tab: field toggle + reorder
  (StatusBadge.jsx extended)   ← new badge types: currentness, 20-F, ADR
```

**Registration in `main.py`:**
```python
from underlying.router import router as underlying_router
app.include_router(underlying_router, prefix="/api")
```

**Expert panel tab addition in `App.jsx`:**
```jsx
['underlying_fields', 'Underlying Fields']  // added to expertTab list
```

---

## 6. Database Schema

New tables added to `database.py` via the existing `_migrate()` pattern. Zero impact on existing tables.

### `underlying_securities`

```python
class UnderlyingSecurity(Base):
    __tablename__ = "underlying_securities"

    id                       = Column(String, primary_key=True, default=_uuid)
    # Identification
    cik                      = Column(String, index=True)
    ticker                   = Column(String, index=True)
    ticker_bb                = Column(String)          # Bloomberg ticker (user-supplied)
    source_identifier        = Column(String)          # what the user typed
    source_identifier_type   = Column(String)          # ticker|isin|cusip|cik|name|bb_ticker
    # Company metadata (Tier 1 — submissions API)
    company_name             = Column(String)
    share_class_name         = Column(String)          # extracted: full class title from cover page
    share_type               = Column(String)          # derived: "Domestic Common Stock" | "ADR" | ...
    reporting_form           = Column(String)          # "10-K" | "20-F" | "40-F"
    filer_category           = Column(String)
    fiscal_year_end          = Column(String)          # MMDD, e.g. "0630"
    exchange                 = Column(String)
    sic_code                 = Column(String)
    sic_description          = Column(String)
    state_of_incorporation   = Column(String)
    entity_type              = Column(String)          # raw from submissions
    adr_flag                 = Column(Boolean, default=False)
    # Filing references
    last_10k_accession       = Column(String)
    last_10k_filed           = Column(String)          # ISO date
    last_10k_period          = Column(String)          # ISO date (report date)
    last_10q_accession       = Column(String)
    last_10q_filed           = Column(String)
    last_10q_period          = Column(String)
    # Currentness
    current_status           = Column(String)          # current|late_nt|delinquent|unknown
    nt_flag                  = Column(Boolean, default=False)
    next_expected_filing     = Column(String)          # ISO date, computed
    next_expected_form       = Column(String)          # "10-K" | "10-Q" | "20-F"
    # XBRL facts (Tier 1)
    shares_outstanding       = Column(Float)
    shares_outstanding_date  = Column(String)
    public_float_usd         = Column(Float)
    public_float_date        = Column(String)
    # Market data (Tier 3 — yfinance)
    closing_value            = Column(Float)
    closing_value_date       = Column(String)
    initial_value            = Column(Float)
    initial_value_date       = Column(String)          # user-chosen date for lookup
    hist_data_series         = Column(Text)            # JSON: [{date, close}, ...]
    market_data_source       = Column(String, default="yahoo_finance")
    market_data_fetched_at   = Column(String)
    # Lifecycle
    status                   = Column(String, default="ingested")
    # ingested | fetching | fetched | needs_review | approved | archived
    ingest_timestamp         = Column(String, default=_now)
    last_fetched_at          = Column(String)
    field_config_version     = Column(String)          # snapshot of config at ingest time

    field_results = relationship("UnderlyingFieldResult", back_populates="underlying",
                                  cascade="all, delete-orphan")
    edit_log      = relationship("UnderlyingEditLog", back_populates="underlying",
                                  cascade="all, delete-orphan")
    links         = relationship("UnderlyingLink", back_populates="underlying",
                                  cascade="all, delete-orphan")

    # One record per (CIK, ticker) pair — catches multi-class duplicates
    __table_args__ = (UniqueConstraint("cik", "ticker"),)
```

### `underlying_field_results`

Mirrors `FieldResult` exactly, but for underlying data. Stores per-field extracted values, sources, and review decisions.

```python
class UnderlyingFieldResult(Base):
    __tablename__ = "underlying_field_results"

    id               = Column(String, primary_key=True, default=_uuid)
    underlying_id    = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    field_name       = Column(String, nullable=False)
    extracted_value  = Column(Text)           # JSON-encoded
    confidence_score = Column(Float)          # 1.0 for Tier 1; model score for Tier 2
    source_excerpt   = Column(Text)           # supporting text snippet (Tier 2 only)
    source_type      = Column(String)         # submissions_api|xbrl_dei|10k_cover|10k_item1|manual|yahoo_finance
    is_approximate   = Column(Boolean, default=False)  # True for market data fields
    review_status    = Column(String, default="pending")
    # pending | accepted | corrected | rejected
    reviewed_value   = Column(Text)
    reviewed_at      = Column(String)
    field_config_version = Column(String)

    __table_args__ = (UniqueConstraint("underlying_id", "field_name"),)
    underlying = relationship("UnderlyingSecurity", back_populates="field_results")
```

### `underlying_edit_log`

```python
class UnderlyingEditLog(Base):
    __tablename__ = "underlying_edit_log"

    id             = Column(String, primary_key=True, default=_uuid)
    underlying_id  = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    field_name     = Column(String, nullable=False)
    old_value      = Column(Text)
    new_value      = Column(Text)
    action         = Column(String, nullable=False)  # edited|accepted|rejected|approved|refetched
    edited_at      = Column(String, default=_now)
    underlying = relationship("UnderlyingSecurity", back_populates="edit_log")
```

### `underlying_links`

```python
class UnderlyingLink(Base):
    __tablename__ = "underlying_links"

    id             = Column(String, primary_key=True, default=_uuid)
    filing_id      = Column(String, ForeignKey("filings.id"), nullable=False)
    underlying_id  = Column(String, ForeignKey("underlying_securities.id"), nullable=False)
    linked_at      = Column(String, default=_now)
    link_source    = Column(String)  # "classification_features" | "manual"

    __table_args__ = (UniqueConstraint("filing_id", "underlying_id"),)
    filing     = relationship("Filing")
    underlying = relationship("UnderlyingSecurity", back_populates="links")
```

### Status ladder

```
ingested   → fetching  → fetched → needs_review → approved
                ↓                      ↑
            (error)              (re-fetch resets to fetched)
```

---

## 7. Backend Modules

### `identifier_resolver.py`

**Identifier type detection (in order of precedence):**

```python
def detect_type(raw: str) -> str:
    raw = raw.strip()
    if re.match(r"^\d{7,10}$", raw):                     return "cik"
    if re.match(r"^[A-Z]{2}[A-Z0-9]{10}$", raw):        return "isin"
    if re.match(r"^[A-Z0-9]{9}$", raw):                  return "cusip"
    if re.match(r"^[A-Z]{1,5}\s+[A-Z]{2}$", raw):       return "bb_ticker"
    if re.match(r"^[A-Z\-\.]{1,6}$", raw):               return "ticker"
    return "name"
```

**Resolution chain:**

| Type | Resolution |
|---|---|
| `cik` | Direct `submissions/CIK{n}.json` |
| `ticker` | `company_tickers.json` (cached EDGAR file, ~9K companies) |
| `bb_ticker` | Strip exchange suffix → resolve as ticker |
| `isin` | OpenFIGI API `/v3/mapping` body `[{"idType":"ID_ISIN","idValue":"..."}]` → ticker → CIK |
| `cusip` | OpenFIGI API with `idType: "ID_CUSIP"` → ticker → CIK |
| `name` | EDGAR EFTS search → return top-3 candidates for user disambiguation |

**OpenFIGI API:** `https://api.openfigi.com/v3/mapping` — free tier, no API key for basic lookups, rate-limited to ~25 req/min. No auth header needed for simple ISIN/CUSIP queries.

**`company_tickers.json`** is cached in `files/` on first fetch and refreshed if older than 7 days (small file, ~500 KB).

**Multi-class handling:** When a resolved CIK has multiple tickers (e.g., `["GOOGL", "GOOG"]`), the resolver returns `{status: "multi_class", candidates: [...]}`. The frontend presents a disambiguation picker; each selected class is ingested as a separate `UnderlyingSecurity` record with the same CIK.

### `currentness.py`

```python
@dataclass
class CurrentnessReport:
    status: str                    # current | late_nt | delinquent | unknown
    eligible: bool                 # True iff status == "current" or "late_nt"
    last_10k: FilingCheck | None
    last_10q: FilingCheck | None
    nt_filings: list[str]          # accession numbers of NT forms in rolling 18-month window
    next_due: NextFiling | None    # {form, expected_by: date, days_remaining: int}
    notes: list[str]               # human-readable explanation bullets

@dataclass
class FilingCheck:
    form: str
    period_end: date
    filed: date
    deadline: date
    days_delta: int                # negative = filed early, positive = filed late
    within_nt_extension: bool
```

**Algorithm:**
1. Parse `fiscalYearEnd` (MMDD) → compute most recent completed annual period
2. Look up deadline days from `filer_category` (see §2 table)
3. Scan `filings.recent` history for `10-K` / `10-Q` / `NT 10-K` / `NT 10-Q` / `20-F` etc.
4. For each required period: find filing, compute `filed - period_end`, compare with deadline
5. NT presence in same period → `within_nt_extension = True`, extend deadline +15 days
6. Any period where no filing exists within extended deadline → `delinquent`
7. All periods current → `current` (or `late_nt` if NT was present)
8. Fewer than 4 quarters of history → `unknown`

**Edge cases:**
- Fiscal year change (52/53-week year): accept ±7-day tolerance on period end dates
- Company that recently went public: flag as `unknown` if <4 quarters of 10-Q history
- 20-F filer: check only 20-F timeliness; `last_10q` = None; acceptable by rule

### `extractor.py`

**Two LLM calls per underlying:**

**Call 1 — Cover page extraction:**
- Input: first 8,000 chars of stripped 10-K text (cover page region)
- Output JSON:
  ```json
  {
    "share_classes": [
      {"class_name": "Class A Common Stock, $0.001 par value", "ticker": "GOOGL", "exchange": "Nasdaq Global Select Market"},
      {"class_name": "Class C Capital Stock, $0.001 par value", "ticker": "GOOG",  "exchange": "Nasdaq Global Select Market"}
    ],
    "is_adr": false,
    "adr_note": null
  }
  ```
- Fallback: if cover page parse fails, regex on Section 12(b) table HTML

**Call 2 — Business description:**
- Input: Item 1 Business section (first 5,000 chars after "Item 1" header)
- Output JSON:
  ```json
  {
    "brief_description": "Microsoft develops cloud computing, productivity software, and AI services...",
    "confidence": 0.95
  }
  ```
- Prompt instructs: 1–2 sentences, no marketing language, focus on what the company does

**Cost estimate:** ~2,500 tokens in + ~200 tokens out per underlying. At $3/M input + $15/M output ≈ $0.01 per underlying. Hundreds of underlyings ≈ a few dollars total.

### `market_data_client.py`

```python
from typing import Protocol

class MarketDataClient(Protocol):
    def get_closing_price(self, ticker: str) -> PriceResult: ...
    def get_price_on_date(self, ticker: str, date: date) -> PriceResult: ...
    def get_price_series(self, ticker: str, period_years: int) -> list[PricePoint]: ...

@dataclass
class PriceResult:
    value: float | None
    date: date | None
    source: str               # "yahoo_finance"
    is_approximate: bool      # always True for Tier 3 sources
    error: str | None

class YahooFinanceClient:
    """
    Default implementation using yfinance.
    No API key required.
    auto_adjust=False → unadjusted (raw) prices, not backwards-adjusted for splits.
    """
    def get_closing_price(self, ticker: str) -> PriceResult:
        # yf.Ticker(ticker).history(period="2d", auto_adjust=False).tail(1)["Close"]

    def get_price_on_date(self, ticker: str, date: date) -> PriceResult:
        # yf.Ticker(ticker).history(start=date, end=date+timedelta(5), auto_adjust=False)
        # Returns close on `date`; if market closed, tries next trading day within window

    def get_price_series(self, ticker: str, period_years: int = 5) -> list[PricePoint]:
        # yf.Ticker(ticker).history(period=f"{period_years}y", auto_adjust=False)["Close"]
```

**Important:** `auto_adjust=False` returns raw unadjusted closing prices. This is the correct choice for structured product reference data, where the Initial Reference Level is the actual market price on a specific date — not a backwards-adjusted figure.

**Rate limiting:** yfinance has no hard rate limits but Yahoo Finance may throttle bulk requests. Add `time.sleep(0.5)` between per-ticker calls during bulk ingest.

### `field_config.py`

Reads/writes `files/underlying_field_config.yaml`. The config file controls which fields are queried for new records and their display order/label. Existing records are never altered when fields are disabled.

```yaml
# files/underlying_field_config.yaml
version: "1"
fields:
  - name: company_name
    display_name: "Company Name"
    enabled: true
  - name: share_class_name
    display_name: "Share Class"
    enabled: true
  - name: brief_description
    display_name: "Brief Description"
    enabled: true
  # ... all fields in display order
```

---

## 8. API Endpoints

All registered under prefix `/api`. Full router: `backend/underlying/router.py`.

### Ingest

| Method | Path | Body / Params | Response |
|---|---|---|---|
| `POST` | `/underlying/ingest` | `{identifier: str, identifier_type?: str}` | `{job_id, status, candidates?}` |
| `POST` | `/underlying/ingest/bulk` | `{identifiers: [str]}` | `{job_id, queued_count}` |
| `POST` | `/underlying/ingest/csv` | multipart file upload | `{job_id, parsed_count, errors?}` |
| `POST` | `/underlying/ingest/from-filings` | (none) | `{job_id, found_count, already_exists_count}` |

### Job status (async polling)

| Method | Path | Response |
|---|---|---|
| `GET` | `/underlying/jobs/{job_id}` | `{status, progress: {done, total}, results?: [{id, ticker, status}], errors?: [...]}` |

### CRUD

| Method | Path | Response |
|---|---|---|
| `GET` | `/underlying` | `[{id, ticker, company_name, status, current_status, last_fetched_at, ...}]` |
| `GET` | `/underlying/{id}` | Full record + all `field_results` |
| `POST` | `/underlying/{id}/refetch` | `{job_id}` — triggers fresh 10-K/10-Q pull |
| `DELETE` | `/underlying/{id}` | Sets `status = "archived"`; soft-delete |

### Review & approval

| Method | Path | Body | Response |
|---|---|---|---|
| `PUT` | `/underlying/{id}/fields/{field_name}` | `{action: "accept"\|"correct"\|"reject", value?: any}` | Updated `UnderlyingFieldResult` |
| `POST` | `/underlying/{id}/approve` | (none) | Updated `UnderlyingSecurity` with `status = "approved"` |

### Market data

| Method | Path | Body | Response |
|---|---|---|---|
| `POST` | `/underlying/{id}/market-data/fetch-close` | (none) | Updated `closing_value` field |
| `POST` | `/underlying/{id}/market-data/fetch-initial` | `{date: "YYYY-MM-DD"}` | Updated `initial_value` + `initial_value_date` |

### Linking

| Method | Path | Response |
|---|---|---|
| `GET` | `/underlying/{id}/filings` | `[{filing_id, cusip, issuer_name, filing_date, link_source}]` |
| `GET` | `/filings/{id}/underlyings` | `[{underlying_id, ticker, company_name, current_status}]` |

### Export

| Method | Path | Response |
|---|---|---|
| `GET` | `/underlying/{id}/export` | JSON (see §11) |
| `GET` | `/underlying/export/bulk` | JSON array of all approved underlyings |

### Field configuration

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/underlying/field-config` | — | `{version, fields: [{name, display_name, enabled}]}` |
| `PUT` | `/underlying/field-config` | `{fields: [{name, display_name, enabled}]}` | Updated config |

---

## 9. Frontend Components

### `App.jsx` changes

```jsx
// Top nav — add 'underlying' entry:
[['filings', 'Filings'], ['underlying', 'Underlying ⬡'], ['expert', 'Expert ⚙'], ['admin', 'Admin']]

// mainView === 'underlying' renders:
<UnderlyingView />    // sidebar (panel) + detail, same layout as Filings view

// Expert tab — add 'underlying_fields':
['underlying_fields', 'Underlying Fields']
// renders: <UnderlyingFieldConfig />
```

### `UnderlyingPanel.jsx` (sidebar)

- Tab switcher: **"Underlyings (N)"** | **"Ingest"**
- List tab:
  - Each row: ticker chip, company name, `CurrentnessBadge`, `StatusBadge`, share type pill
  - Filter bar: status, current_status, share type, reporting form
  - Search: name or ticker
  - Click → loads `UnderlyingDetail`
- Ingest tab: see below

### `UnderlyingIngest.jsx` (inside sidebar)

- **Single input:** text field with auto-detected type label → "Fetch" button
- **Bulk paste:** textarea (one per line) → "Queue All" button
- **CSV upload:** file picker with format tooltip → validation preview → "Upload" button
- **"Import from filings":** button that calls `/underlying/ingest/from-filings` → shows count of new vs already-known underlyings
- **Multi-class picker modal:** shown when resolution returns multiple share classes
  - Lists classes with tickers, checkboxes → "Ingest Selected"
- **Progress section:** live-updating job status per queued item (poll `/underlying/jobs/{id}` every 3s)
  - Shows: queued → fetching → done (green) / error (red) per item
  - Collapses when all done

### `UnderlyingDetail.jsx` (main panel)

**Header section:**
- Ticker + share class name (large)
- Exchange pill, share type pill
- `CurrentnessBadge` (prominent — green/amber/red)
- `20-F filer` badge (if applicable, blue)
- `ADR` badge (if applicable, purple)
- "Re-fetch" button (top right) — spins during background job
- "Approve All Accepted" button

**Currentness widget** (prominent card, below header):
```
┌─────────────────────────────────────────────────────────┐
│ ✅ CURRENT  ·  Large Accelerated Filer  ·  FYE Jun 30   │
│ Last 10-K: 2025-06-30  filed 2025-07-30  (30 days early)│
│ Last 10-Q: 2025-12-31  filed 2026-01-28  (28 days early)│
│ Next due:  10-Q for Mar 31, 2026  by  May 11, 2026      │
└─────────────────────────────────────────────────────────┘
```
Amber variant for `late_nt`, red for `delinquent`, grey for `unknown`.

**Field review table** (reuses/mirrors `FieldTable.jsx` pattern):
- Columns: Field | Extracted Value | Source | Confidence | Status | Action
- Source badges: `API` (green), `XBRL` (teal), `10-K cover` (blue), `10-K Item 1` (indigo), `Manual` (grey), `Yahoo Finance ⚠` (amber)
- Market data fields show date alongside value and the `is_approximate` warning
- Accept / Correct / Reject per row

**Historical price chart:**
- Sparkline below field table (if `hist_data_series` populated)
- Simple line chart: 5-year daily closes
- Hover tooltip: date + close price

**"Referenced in N filings" section (collapsible):**
- Table: Issuer | CUSIP | Filing Date | Status → clicking a row opens that FilingDetail
- "Link manually" button for cases where auto-link missed a filing

### `UnderlyingFieldConfig.jsx` (Expert tab)

- Ordered drag-and-drop list of all defined fields
- Toggle switch per field (enable / disable)
- Inline display name override (text input)
- Info note: *"Disabling a field stops it from being queried for new records. Existing data is preserved."*
- "Save" button → PUT `/underlying/field-config`

### `StatusBadge.jsx` extensions

New badge types to add alongside existing filing status badges:

```jsx
// Currentness badges
"current"      → green    "Current"
"late_nt"      → amber    "Late – NT filed"
"delinquent"   → red      "Delinquent"
"unknown"      → grey     "Status unknown"

// Type badges
"20-F"         → blue     "Foreign (20-F)"
"40-F"         → blue     "Foreign (40-F)"
"ADR"          → purple   "ADR"
"is_approx"    → amber    "⚠ Approximate"   ← inline on market data fields
```

---

## 10. CSV Ingest Format

One identifier type per file, declared in the header row.

```csv
identifier_type,identifier
ticker,MSFT
ticker,AAPL
ticker,GOOGL
```

```csv
identifier_type,identifier
isin,US5949181045
isin,US0231351067
```

```csv
identifier_type,identifier
cusip,594918104
cusip,023135106
```

**Validation rules:**
- Row 1 must be exactly `identifier_type,identifier`
- `identifier_type` must be one of: `ticker`, `isin`, `cusip`, `cik`, `bb_ticker`, `name`
- All rows in a file must have the same `identifier_type` (mixed types → validation error with clear message)
- Empty rows and rows starting with `#` are ignored
- Maximum 500 rows per file (for POC)

**Error handling:** Upload returns a validation preview before queuing. Invalid rows are listed with reasons; valid rows proceed.

---

## 11. Export Format

```json
{
  "underlying_export_version": "1.0",
  "exported_at": "2026-04-23T12:00:00Z",
  "field_config_version": "1",
  "securities": [
    {
      "ticker": "MSFT",
      "ticker_bb": "MSFT UW",
      "company_name": "Microsoft Corporation",
      "share_class_name": "Common stock, $0.00000625 par value per share",
      "share_type": "Domestic Common Stock",
      "exchange": "Nasdaq",
      "reporting_form": "10-K",
      "filer_category": "Large accelerated filer",
      "sic_code": "7372",
      "sic_description": "Services-Prepackaged Software",
      "state_of_incorporation": "WA",
      "current_status": "current",
      "nt_flag": false,
      "last_10k_period": "2025-06-30",
      "last_10k_filed": "2025-07-30",
      "last_10q_period": "2025-12-31",
      "last_10q_filed": "2026-01-28",
      "next_expected_filing": "2026-05-11",
      "next_expected_form": "10-Q",
      "brief_description": "Microsoft develops cloud computing, productivity software, and AI services for consumers and enterprises worldwide.",
      "shares_outstanding": 7433166379,
      "shares_outstanding_date": "2025-07-24",
      "public_float_usd": 3100000000000,
      "initial_value": 100.00,
      "initial_value_date": "2020-01-15",
      "initial_value_source": "yahoo_finance",
      "initial_value_is_approximate": true,
      "closing_value": 412.34,
      "closing_value_date": "2026-04-22",
      "closing_value_source": "yahoo_finance",
      "closing_value_is_approximate": true,
      "hist_data_series": [
        {"date": "2021-04-23", "close": 254.12},
        {"date": "2021-04-26", "close": 249.33}
      ],
      "adr_flag": false,
      "cik": "0000789019",
      "approved_at": "2026-04-23T11:00:00Z",
      "last_fetched_at": "2026-04-23T10:30:00Z",
      "referenced_in_filings": ["filing-uuid-1", "filing-uuid-2"]
    }
  ]
}
```

---

## 12. Key Technical Decisions

| # | Decision | Rationale | Alternatives considered |
|---|---|---|---|
| D-01 | **OpenFIGI for ISIN/CUSIP → ticker** | Free, no auth required for basic lookups, well-maintained | CUSIP Global Services (paid); manual CIK entry |
| D-02 | **yfinance for market data** | Zero config, no API key, covers all US names + many international. Adequate for POC | Bloomberg BLPAPI (requires licence); Refinitiv (paid); Alpha Vantage (free tier too restrictive) |
| D-03 | **`auto_adjust=False` in yfinance** | Structured products use raw unadjusted prices as reference levels | Default adjusted prices would misrepresent historical initial values |
| D-04 | **One DB record per share class (not per company)** | PRISM references a specific class (GOOGL vs GOOG are different underlying definitions) | One record per CIK with sub-fields; rejected — over-complicates review workflow |
| D-05 | **Global field config, not per-underlying** | Simpler to manage; sufficient for POC with <500 underlyings | Per-type config (domestic vs 20-F different fields); deferred to potential extension |
| D-06 | **Disabled fields not queried; existing data preserved** | Reversible without data loss; consistent with "no destructive operations" principle | Hard-delete disabled field data; rejected |
| D-07 | **Per-field review (not per-record)** | Consistent with existing extraction review UX; enables selective correction without full re-fetch | Per-record approval; rejected as too coarse |
| D-08 | **Pluggable `MarketDataClient` protocol** | Allows swap to Bloomberg/Refinitiv without touching other modules | Hardcode yfinance; rejected — creates technical debt |
| D-09 | **Currentness check fully from submissions API** | Zero additional API calls; all needed data already in the submissions JSON | Scraping EDGAR company page; rejected |
| D-10 | **Async ingest via FastAPI BackgroundTasks + thread pool** | Ingest of hundreds of underlyings cannot be synchronous (30–60s per item with LLM extraction) | Celery/Redis task queue; rejected — too heavy for a local POC |
| D-11 | **`company_tickers.json` cached locally, refreshed every 7 days** | Avoids repeated EDGAR calls for ticker lookups; file is ~500 KB | Always fetch live; rejected due to rate limit concerns |
| D-12 | **Soft-delete (`status = "archived"`)** | Consistent with existing patterns; prevents accidental data loss | Hard-delete; rejected |
| D-13 | **`UniqueConstraint("cik", "ticker")` on `underlying_securities`** | Prevents duplicate records for the same share class on re-ingest | No constraint; rejected — would cause data duplication on repeated ingest |
| D-14 | **Links populated automatically from `classification_product_features`** | Zero extra work for existing filings — auto-discovered | Manual linking only; rejected — too much friction |

---

## 13. Coding Standards & Conventions

Follows all existing project standards. Key specifics for this module:

### Python
- Type hints on every function signature, including `-> None`
- `pathlib.Path` for all file operations; no `os.path`
- Module-level constants in UPPER_SNAKE_CASE
- Shared Anthropic client: import and call `_get_client()` from `classify.classifier` or replicate the same pattern in `underlying/extractor.py` — do not instantiate `anthropic.Anthropic()` per call
- EDGAR HTTP calls: always call `_wait_rate_limit()` from `ingest.edgar_client` before any EDGAR request; do not bypass the rate limiter
- SQLAlchemy sessions: always use `with database.get_session() as session:` pattern; commit explicitly
- Background tasks: catch and log all exceptions; update `underlying_securities.status` to a meaningful error state on failure; never let a background job silently fail

### Logging
```python
log = logging.getLogger(__name__)   # use module __name__ throughout
log.info("Resolving identifier: %r  type=%s", raw, id_type)
log.warning("OpenFIGI returned no match for %r", cusip)
log.error("10-K extraction failed for CIK %s: %s", cik, exc, exc_info=True)
```

### Error handling in API endpoints
- Return `400` for invalid identifiers with a clear message
- Return `404` for unknown `underlying_id`
- Return `409` for duplicate ingest (CIK + ticker already exists) with `{existing_id: "..."}`
- Return `422` for field review action on a non-`fetched`/`needs_review` record
- Return `202 Accepted` for all async ingest endpoints (never block >2s on an API call)

### Frontend
- All underlying API calls go through `api.js` — add new methods there; never fetch directly from components
- New components follow existing naming: PascalCase `.jsx`, prop destructuring in function signature
- No inline styles — use Tailwind utility classes only
- Status badges: always use `StatusBadge.jsx` or `CurrentnessBadge` — never ad-hoc coloured `<span>`s
- Async polling: use `setInterval` with cleanup in `useEffect`; poll at 3s during active job; stop polling on completion or error

### New `requirements.txt` additions
```
yfinance>=0.2.40
```
(OpenFIGI uses `httpx` which is already a dependency)

### New `config.py` additions
```python
# Underlying data module
UNDERLYING_FIELD_CONFIG_FILE = PROJECT_ROOT / "files" / "underlying_field_config.yaml"
OPENFIGI_API_URL             = "https://api.openfigi.com/v3/mapping"
OPENFIGI_RATE_LIMIT_DELAY    = 2.5       # seconds (25 req/min free tier)
COMPANY_TICKERS_CACHE_FILE   = PROJECT_ROOT / "files" / "company_tickers.json"
COMPANY_TICKERS_CACHE_TTL    = 7 * 24 * 3600   # 7 days in seconds
MARKET_DATA_PRICE_SERIES_YEARS = 5
UNDERLYING_INGEST_MAX_CSV_ROWS = 500
UNDERLYING_JOB_POLL_INTERVAL   = 3        # seconds (frontend)
```

---

## 14. Build Sequence & Dependencies

Execute in order. Steps within a week can be parallelised where noted.

```
Week 1 — Backend foundation
  [1.1] DB schema (Phase 1)        — no dependencies
  [1.2] identifier_resolver.py     — depends on [1.1]; reuses edgar_client._get()
  [1.3] currentness.py             — depends on [1.2]
  [1.4] field_config.py + YAML     — depends on [1.1]; can parallel with [1.2]-[1.3]

Week 2 — Data pipeline
  [2.1] edgar_underlying_client.py — depends on [1.2]; fetch submissions + 10-K/10-Q HTML
  [2.2] extractor.py               — depends on [2.1]; LLM cover page + Item 1 calls
  [2.3] market_data_client.py      — depends on [1.1]; parallel with [2.1]-[2.2]
  [2.4] background.py              — depends on [2.1][2.2][2.3]
  [2.5] router.py (all endpoints)  — depends on all of Week 1 + [2.1]-[2.4]

Week 3 — Frontend
  [3.1] api.js extensions          — depends on [2.5]
  [3.2] StatusBadge.jsx extensions — no dependencies; parallel
  [3.3] UnderlyingPanel.jsx        — depends on [3.1]
  [3.4] UnderlyingIngest.jsx       — depends on [3.1][3.3]
  [3.5] UnderlyingDetail.jsx       — depends on [3.1][3.2]
  [3.6] App.jsx — add nav + view   — depends on [3.3][3.5]

Week 4 — Config, links, export, tests
  [4.1] UnderlyingFieldConfig.jsx  — depends on [3.6]
  [4.2] Filing ↔ Underlying links  — depends on [2.5][3.5]; update classifier to auto-populate
  [4.3] Export endpoints           — depends on [2.5]
  [4.4] Tests                      — depends on all above
  [4.5] config.py additions        — can do in Week 1; listed here for completeness
```

---

## 15. Potential Extensions

Not in scope for this build. Documented here for future reference.

### E-01 — Bloomberg BLPAPI integration
Replace or augment `YahooFinanceClient` with a Bloomberg implementation of `MarketDataClient`. The pluggable interface is already designed for this. Requires Bloomberg Terminal access and `blpapi` Python SDK.

### E-02 — Automatic staleness alerts
When an underlying's `next_expected_filing` passes without a new filing detected, automatically set `current_status = "delinquent"` and surface an alert in the UI. Requires a scheduled background check (could use the existing cron pattern from `docs/tracking/OPEN_TASKS.md`).

### E-03 — Per-underlying-type field configurations
Different field sets for domestic 10-K filers vs 20-F foreign filers vs ADRs. Currently global config is used; this would add a `type_overrides` section to the YAML.

### E-04 — 8-K monitoring for material events
Flag underlyings when a material 8-K is filed (e.g., restatement, going concern, executive departure). The submissions API provides 8-K filings in the same history feed. This would add an `alerts` section to `UnderlyingDetail`.

### E-05 — Automatic link discovery from 424B2 text
Currently, filing ↔ underlying links are populated from `classification_product_features.underlyings` (structured JSON set during classification). Extension: also parse the filing text for CUSIP/ticker mentions in the term sheet and attempt to auto-resolve them to underlying records.

### E-06 — PRISM API push
Instead of (or in addition to) JSON export, push approved underlying records directly to a PRISM API endpoint. Requires PRISM to expose an underlying reference data API.

### E-07 — Underlying watchlist / portfolio view
Group underlyings into named watchlists (e.g. "Q2 2026 structured products"). Useful when the analyst is working on a specific issuance batch.

### E-08 — Historical currentness tracking
Currently, currentness is checked at ingest time and on re-fetch. Extension: store a time-series of currentness status so you can see when a company went delinquent and when it recovered.

### E-09 — 40-F Canadian issuer support
Currently listed as a supported `reporting_form` value but currentness rules for 40-F filers have minor differences. Needs a dedicated deadline table entry and testing against Canadian filers.

### E-10 — Bulk re-fetch on schedule
Automatically re-fetch all approved underlyings monthly (or around their expected filing dates) to keep currentness status fresh. Requires the existing cron/scheduler infrastructure.

---

## 16. Open Tasks & Blockers

### Immediate (before build start)

| # | Task | Owner | Status |
|---|---|---|---|
| OT-01 | Confirm `yfinance` addition to `requirements.txt` is acceptable for the handover colleague's environment | Markus | ✅ Decided — yes, add |
| OT-02 | Confirm OpenFIGI free tier rate limit (25 req/min) is acceptable for POC volume | Markus | ✅ Decided — yes |
| OT-03 | Agree on the exact CSV format declared above (§10) | Markus | Pending sign-off |
| OT-04 | Decide: does the "Import from filings" button run immediately or queue as background job? | Markus | Assumed: background |

### During build

| # | Task | Notes |
|---|---|---|
| OT-05 | Verify OpenFIGI response schema for ISIN/CUSIP lookup before implementing resolver | Free tier returns different fields than documented in some edge cases |
| OT-06 | Test yfinance `auto_adjust=False` for ADRs — pricing behaviour differs from domestic stocks | May need a flag to use adjusted prices for ADRs |
| OT-07 | Validate currentness algorithm against 3+ real examples (one each: current, late_nt, delinquent) | Use EDGAR to find a known delinquent filer for testing |
| OT-08 | Confirm 20-F deadline calculation — foreign private issuers have more variability | Some have SEC-granted extensions; `unknown` status is acceptable fallback |
| OT-09 | Define test fixtures for `currentness.py` unit tests | Need mock submissions JSON for each status variant |
| OT-10 | Check whether `classification_product_features.underlyings` field is consistently populated | If not, the auto-link-from-filings feature will miss some filings |

### Post-build

| # | Task | Notes |
|---|---|---|
| OT-11 | Update `docs/tracking/OPEN_TASKS.md` with module completion status | |
| OT-12 | Update `handover/HANDOVER_BRIEF.md` to describe the new module | |
| OT-13 | Update user manual (`docs/user_manual.html`) with underlying data workflow | |
| OT-14 | Update `README.md` to reflect new module | |
| OT-15 | Run underlying ingest against a set of 20+ real underlyings to validate field extraction accuracy | Acceptance criterion: ≥90% of brief descriptions rated "acceptable" by Markus |

---

*End of specification document.*
*For project-level context, see `handover/HANDOVER_BRIEF.md` and `docs/tracking/OPEN_TASKS.md`.*
*For architecture of the existing system, see `docs/tech_handbook.html`.*
