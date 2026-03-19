# REQUIREMENTS.md
# EDGAR Extraction & Mapping — Technical Requirements

> **Status:** Draft v0.2
> **Source:** Business Case "EDGAR Extraction" (260217), LPA Internal
> **Audience:** Claude Code (development agent)
> **Last updated:** 2026-03-18
> **Root folder:** `EDGAR-Extraction_Mapping/`

---

## 1. Project Overview

This project builds a **local, standalone** AI-driven pipeline that retrieves, classifies, and extracts structured-product data from SEC EDGAR 424B2 filings, maps it to LPA's PRISM schema format, and presents it in a browser-based review UI for human validation and export.

The system runs entirely on a **MacBook** (developer/tester machine). There is no cloud deployment, no Azure, no external infrastructure. The goal is a well-functioning local test system that demonstrates the full end-to-end workflow and can be handed off to another machine by copying the project folder.

### Primary Goal
Prove the full pipeline — EDGAR ingest → classify → extract → review → export — locally, using real EDGAR filings and real PRISM schemas, with a working browser UI, before any cloud productionisation is considered.

### Out of Scope (v1)
- Cloud or server deployment of any kind
- Multi-user access (single local user only for v1)
- Authentication / login screens
- Full PRISM DB write (v1 exports JSON/CSV files only)
- Filing types other than 424B2
- Scheduled/automated background monitoring (on-demand only for v1)
- SLA-driven queue management

---

## 2. Portability & Environment Constraints

These are hard constraints. Every technical decision must be evaluated against them.

**PC-1 — Self-contained project folder**
All code, configuration, local data, schemas, logs, and exported files MUST reside within the `EDGAR-Extraction_Mapping/` project folder. Nothing is installed system-wide that cannot be reproduced by following `SETUP.md`.

**PC-2 — Mac-native runtime**
The system targets macOS (Apple Silicon and Intel). No Docker is required, but Docker is acceptable as an option if it simplifies setup — only if the container definition lives inside the project folder.

**PC-3 — Transferable by folder copy**
A second person MUST be able to copy the project folder to their Mac, follow `SETUP.md`, and have a running system. The only prerequisites allowed outside the folder are: Python 3.11+, Node.js 20+, and an Anthropic API key set as an environment variable.

**PC-4 — No hardcoded paths**
All file paths in config and code MUST be relative to the project root or resolved dynamically. No absolute paths (e.g., `/Users/markus/...`).

**PC-5 — API key via environment variable**
The Anthropic API key is provided via `ANTHROPIC_API_KEY` environment variable. It MUST NOT be written to any file inside the project folder.

---

## 3. Project Folder Structure

Claude Code SHALL create and maintain the following structure:

```
EDGAR-Extraction_Mapping/
│
├── REQUIREMENTS.md          # This file
├── EDGAR_API.md             # EDGAR API reference and endpoints
├── DATA_MODEL.md            # PRISM field mapping and data model
├── SETUP.md                 # Step-by-step setup for a new Mac
├── README.md                # Project overview and quick start
│
├── schemas/
│   └── prism/               # PRISM schema files
│       ├── *.json           # One schema file per payout type (provided by Markus)
│       │                    # Filename convention: {payout_type_id}_v{version}.json
│       └── cusip_model_mapping.xlsx  # CUSIP-to-PRISM-model reference mapping (provided by Markus)
│
├── backend/                 # Python backend (FastAPI)
│   ├── main.py
│   ├── requirements.txt     # pip dependencies (pinned versions)
│   ├── config.py            # All config loaded from environment / relative paths
│   ├── ingest/              # Phase 1: EDGAR crawl & download
│   ├── classify/            # Phase 2: payout type classification
│   ├── extract/             # Phase 3: schema-driven field extraction
│   └── export/              # Phase 6: JSON/CSV export logic
│
├── frontend/                # React frontend (Vite)
│   ├── package.json         # npm dependencies (pinned versions)
│   ├── vite.config.js
│   └── src/
│
├── data/
│   ├── filings/             # Persisted original 424B2 filings — one subfolder per filing (gitignored)
│   │   └── {accession_number}/
│   │       ├── raw.html         # Original filing HTML as downloaded from EDGAR
│   │       ├── metadata.json    # Filing metadata at time of ingest
│   │       └── index.htm        # Original EDGAR filing index page (if available)
│   ├── db/                  # SQLite database file (gitignored)
│   └── exports/             # Approved extraction exports (JSON/CSV)
│
└── logs/                    # Application logs (gitignored)
```

---

## 4. Architecture Overview

All components run locally. The browser UI talks to a local backend API. The backend talks to EDGAR (public internet) and the Claude API (public internet). Everything else is local.

```
Browser (localhost:5173)
        │
        ▼
Backend API (localhost:8000)  ←→  SQLite (data/db/)
        │
        ├──→  EDGAR Full-Text Search API  (public, no auth)
        ├──→  Anthropic Claude API        (ANTHROPIC_API_KEY)
        ├──→  schemas/prism/              (local schema files)
        ├──→  data/filings/               (persisted original filings)
        └──→  data/exports/              (output)
```

**Technology stack:**
- **Backend:** Python 3.11+, FastAPI, SQLite (via SQLAlchemy), `httpx` for EDGAR calls
- **Frontend:** React 18, Vite, plain CSS or Tailwind (no heavy UI framework)
- **AI:** Anthropic Claude API — `claude-sonnet-4-20250514` model, via `anthropic` Python SDK
- **Storage:** SQLite for all application state; flat files for raw HTML and exports

---

## 5. Functional Requirements by Phase

### Phase 1 — Ingest

**FR-1.1** The backend SHALL accept a user-provided CUSIP or free-text search term via the frontend and query the EDGAR Full-Text Search API for matching 424B2 filings.

**FR-1.2** The backend SHALL download and persist the raw HTML of each 424B2 filing into a dedicated subfolder: `data/filings/{accession_number_no_dashes}/raw.html`. Each filing SHALL have its own folder — files are never overwritten or shared across filings.

**FR-1.3** Alongside the raw HTML, the backend SHALL write a `metadata.json` file into the same filing folder containing: `cusip`, `cik`, `accession_number`, `issuer_name`, `filing_date`, `edgar_filing_url`, `ingest_timestamp`. This makes each filing folder self-contained and independently usable for future testing without the database.

**FR-1.4** The backend SHALL also attempt to download and save the EDGAR filing index page (`index.htm`) into the filing folder. This provides a record of all documents submitted as part of the filing.

**FR-1.5** The backend SHALL store filing metadata in SQLite, referencing the local folder path: `filing_folder_path` (relative, e.g. `data/filings/000123456726000001/`).

**FR-1.6** The backend SHALL handle EDGAR rate limits gracefully with retry logic and exponential backoff. EDGAR enforces a limit of 10 requests/second per IP; the client MUST stay below this.

**FR-1.7** The frontend SHALL display ingest progress and surface errors (filing not found, network failure) clearly to the user.

> See `EDGAR_API.md` for endpoint URLs, request/response formats, and known quirks.

---

### Phase 2 — Classification

**FR-2.1** After ingest, the system SHALL classify the filing into a PRISM payout type by sending relevant filing text to the Claude API with a classification prompt.

**FR-2.2** The classification prompt SHALL include the list of known payout types loaded from `schemas/prism/` at runtime. Adding a new schema file SHALL automatically extend the classification options — no code change required.

**FR-2.3** The classification result SHALL include: `payout_type_id`, `confidence_score` (0.0–1.0), `matched_schema_version`, `classification_timestamp`.

**FR-2.4** Filings with `confidence_score` below a configurable threshold (default: 0.75, set in `config.py`) SHALL be flagged as `needs_review` rather than proceeding automatically to extraction.

---

### Phase 3 — Extraction

**FR-3.1** Based on the classified payout type, the system SHALL load the corresponding PRISM schema from `schemas/prism/` and extract all defined fields from the filing HTML using the Claude API.

**FR-3.2** Every field defined in the schema MUST produce an extraction result — either a value or an explicit `null` with a `not_found` flag. Silent omission of fields is not acceptable.

**FR-3.3** Each field result SHALL include: `field_name`, `extracted_value`, `confidence_score`, `source_excerpt` (the text fragment the value was drawn from).

**FR-3.4** The extraction prompt SHALL be schema-driven: constructed dynamically from the loaded schema file, not hardcoded. This ensures new schema versions work without code changes.

**FR-3.5** Extraction results SHALL be written to SQLite and linked to their filing record.

---

### Phase 4 — Review UI

**FR-4.1** The frontend SHALL display a list of all filings with their status (`ingested`, `classified`, `extracted`, `approved`, `exported`).

**FR-4.2** Selecting a filing SHALL open a detail view showing:
- Filing metadata (CUSIP, issuer, date, payout type, classification confidence)
- A field-by-field extraction table: field name | extracted value | confidence | source excerpt | status
- The original filing HTML accessible via a side panel or link

**FR-4.3** Fields with `confidence_score` below a configurable threshold (default: 0.80) SHALL be visually highlighted (e.g., amber background) to draw reviewer attention.

**FR-4.4** The reviewer SHALL be able to:
- Edit any field value inline
- Mark individual fields as `accepted` or `rejected`
- Approve the entire filing (moves status to `approved`)
- Flag the filing for re-extraction (re-runs Phase 3)

**FR-4.5** The filing list SHALL be filterable by: status, payout type, filing date range, issuer name / CUSIP.

**FR-4.6** No login or authentication is required. The UI is local-only.

---

### Phase 5 — Validation State

**FR-5.1** The system SHALL track per-filing status through the full lifecycle: `ingested → classified → extracted → approved → exported`.

**FR-5.2** All human edits SHALL be logged to SQLite with: `field_name`, `old_value`, `new_value`, `edited_at`. Reviewer identity is not required in v1 (single user).

**FR-5.3** An approved filing SHALL require an explicit action to return to `extracted` status (i.e., approval is not accidentally reversible).

---

### Phase 6 — Export

**FR-6.1** The frontend SHALL provide an "Export" button per approved filing. Clicking it SHALL generate a JSON file in `data/exports/` containing all approved field values, structured to match the PRISM schema for that payout type.

**FR-6.2** Optionally, a CSV export SHALL also be generated alongside the JSON for each filing.

**FR-6.3** Export filename convention: `{cusip}_{payout_type_id}_{approved_date}.json`

**FR-6.4** A batch export option SHALL allow exporting all approved filings in one action.

**FR-6.5** Export failures (schema validation errors, missing required fields) SHALL be reported in the UI. Required fields that are `null` SHALL block export with a clear error message listing the missing fields.

---

## 6. Non-Functional Requirements

| ID | Category | Requirement |
|----|----------|-------------|
| NFR-1 | Performance | Ingest + classify + extract SHALL complete in under 3 minutes per filing on a MacBook (M-series or Intel, 16GB RAM) |
| NFR-2 | Accuracy | ≥ 90% precision on required PRISM fields (per SOW 4 baseline) |
| NFR-3 | Portability | Full system operational after `SETUP.md` on a fresh Mac with Python 3.11+ and Node 20+ |
| NFR-4 | Recoverability | SQLite database and `data/exports/` persist across application restarts without data loss |
| NFR-5 | Auditability | All extraction events, human edits, and exports written to SQLite with timestamps |
| NFR-6 | API Safety | Anthropic API key MUST NOT be written to disk. All Claude API calls logged locally (prompt tokens, response tokens, cost estimate) for budget awareness |

---

## 7. Open Questions

| # | Question | Blocks | Status |
|---|----------|--------|--------|
| Q1 | Which PRISM payout types are in scope for v1? (Full list or subset?) | Phase 2 classification prompt | 🔴 Open — provide schema files to resolve |
| Q2 | LLM-only extraction or hybrid with rule-based fallback? | Phase 3 architecture | 🔴 Open |
| Q3 | FINMA data residency: does routing raw 424B2 HTML through Claude API require any special handling? | NFR-6, Phase 3 | 🔴 Open — legal/compliance check needed before production use; not a blocker for local test |
| Q4 | Preferred frontend styling: plain CSS, Tailwind, or a component library? | Phase 4 UI | 🟡 Default: Tailwind unless instructed otherwise |

---

## 8. Reference Documents

| File | Purpose | Status |
|------|---------|--------|
| `EDGAR_API.md` | EDGAR endpoint URLs, request/response formats, rate limits, filing structure | ✅ Created |
| `DATA_MODEL.md` | PRISM field mapping table, SQLite schema, export format spec | ✅ Created |
| `SETUP.md` | Step-by-step setup instructions for a new Mac | ✅ Created |
| `README.md` | Project overview and quick start | ✅ Created |
| `schemas/prism/*.json` | PRISM schema file(s) — provided by Markus | ✅ Present (1 file) |
| `schemas/prism/cusip_model_mapping.xlsx` | CUSIP-to-PRISM-model reference mapping | ✅ Present |
| PRISM Wiki (Azure DevOps) | Full PRISM documentation — Claude Code must fetch at session start | 🔗 https://dev.azure.com/l-p-a/PRISM/_wiki/wikis/PRISM.wiki/15946/Basics-Important-Links |

---

*End of REQUIREMENTS.md v0.2*
