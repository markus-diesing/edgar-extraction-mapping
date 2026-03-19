# EDGAR Extraction & Mapping

A local, standalone pipeline for retrieving, classifying, and extracting structured-product data from SEC EDGAR 424B2 filings, mapped to LPA's PRISM schema format, with a browser-based review and export UI.

**Runs entirely on your Mac. No cloud. No server. No login.**

---

## What This Does

1. **Ingest** — Search EDGAR for 424B2 filings by CUSIP or issuer name, download the filing HTML
2. **Classify** — Use Claude AI to identify the PRISM payout type (e.g., Barrier Reverse Convertible)
3. **Extract** — Use Claude AI to extract all PRISM schema fields from the filing, with confidence scores
4. **Review** — Browser UI for a human reviewer to verify, edit, and approve extracted data
5. **Export** — Generate PRISM-compatible JSON/CSV files for approved filings

---

## Quick Start

See **[SETUP.md](SETUP.md)** for full instructions.

**Short version (after prerequisites installed):**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python main.py init-db && cd ..
cd frontend && npm install && cd ..

# Terminal 1:
cd backend && source .venv/bin/activate && uvicorn main:app --reload --port 8000

# Terminal 2:
cd frontend && npm run dev

# Browser: http://localhost:5173
```

---

## Project Structure

```
EDGAR-Extraction_Mapping/
├── README.md                   ← you are here
├── REQUIREMENTS.md             ← full functional requirements
├── EDGAR_API.md                ← EDGAR API reference and quirks
├── DATA_MODEL.md               ← database schema, PRISM format, export spec
├── SETUP.md                    ← step-by-step setup for a new Mac
├── IMPROVEMENTS_TODO.md        ← prioritised backlog
├── RESEARCH_FINDINGS_AND_NEXT_STEPS.md  ← batch-run analysis and findings
├── schemas/
│   └── prism/
│       ├── prism-v1.schema.json          ← all PRISM models in one file
│       └── CUSIP_PRISM_Mapping.xlsx      ← CUSIP-to-model reference
├── files/
│   ├── architecture.drawio     ← system architecture diagram
│   ├── financial_glossary.md   ← glossary loaded into extraction system prompt
│   ├── issuer_extraction_hints.json ← per-issuer hints (BofA, JPMorgan, …)
│   ├── sections/               ← per-section extraction config (YAML)
│   ├── hints/                  ← cross-issuer and per-issuer hint overrides
│   └── runtime_settings.yaml   ← runtime extraction settings
├── backend/            ← Python / FastAPI
│   ├── ingest/         ← EDGAR search + HTML download + image download
│   ├── classify/       ← two-stage Claude classification
│   ├── extract/        ← schema-driven Claude extraction
│   ├── export/         ← JSON/CSV export
│   ├── hints/          ← hints CRUD API
│   ├── sections/       ← section config API
│   └── settings/       ← runtime settings API
├── frontend/           ← React / Vite
├── scripts/
│   ├── backfill_images.py    ← download images for existing filings
│   └── retry_failed_ingest.py
├── data/
│   ├── filings/        ← persisted original 424B2 filings (one folder per filing)
│   ├── db/             ← SQLite database
│   └── exports/        ← approved extraction exports (JSON/CSV)
└── logs/
```

---

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Deployment | Local Mac only | Test/demo system; no infra needed |
| Database | SQLite | Zero-config, file-based, portable |
| Backend | Python + FastAPI | Fast to iterate, good EDGAR/AI library support |
| Frontend | React + Vite | Standard, lightweight, runs on `npm run dev` |
| AI model | Claude Sonnet (Anthropic API) | Best extraction quality for structured financial text |
| Portability | All deps in `backend/.venv/` and `frontend/node_modules/` | Copy folder → run on any Mac |

---

## For Claude Code

**Read these files before writing any code:**
1. `REQUIREMENTS.md` — what to build and what NOT to build
2. `EDGAR_API.md` — all EDGAR endpoints, rate limits, and filing quirks
3. `DATA_MODEL.md` — database schema, PRISM format, path conventions
4. `files/CLAUDE_CODE_BOOTSTRAP.md` — session bootstrap checklist

**Critical rules:**
- All paths MUST be relative to project root (see `DATA_MODEL.md` section 5)
- `ANTHROPIC_API_KEY` is from environment variable only — never write it to a file
- SQLite only — no PostgreSQL, no Redis, no Docker required
- No authentication — single local user, no login screens
- Schema-as-config — classification and extraction prompts load payout types from `schemas/prism/prism-v1.schema.json` at runtime

---

## API Endpoints Reference

### Ingest
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/ingest/search` | Search EDGAR for 424B2 filings |
| POST | `/api/ingest/filing` | Download and persist a specific filing |
| GET  | `/api/filings` | List all filings (filterable by status, payout_type, cusip) |
| GET  | `/api/filings/{id}` | Get one filing record |
| DELETE | `/api/filings/{id}` | Delete a filing record and its local files |
| GET  | `/api/filings/{id}/document` | Serve raw HTML with highlight injection |
| GET  | `/api/filings/{id}/text` | Return stripped plain text of a filing |
| GET  | `/api/filings/{id}/kpis` | Ingest/classify/extract timing and token-cost KPIs |
| POST | `/api/filings/{id}/fetch-images` | (Re-)download images from EDGAR for an existing filing |
| POST | `/api/filings/{id}/reset-classification` | Revert to `ingested` status, clearing classification data |
| POST | `/api/filings/{id}/classify-override` | Manually set PRISM model (logged to classification_feedback) |

### Classify
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/classify/{id}` | Run two-stage Claude classification |
| GET  | `/api/classify/models` | List valid PRISM model IDs from the schema |

### Extract / Review / Export
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/extract/{id}` | Run schema-driven extraction |
| POST | `/api/extract/{id}/reextract` | Re-run extraction on an already-extracted filing |
| GET  | `/api/extract/{id}/results` | Get extraction results with field-level detail |
| PATCH | `/api/extract/{id}/fields/{field_id}` | Update a single field (value + review status) |
| POST | `/api/extract/{id}/approve` | Approve a filing |
| POST | `/api/extract/{id}/unapprove` | Undo approval |
| POST | `/api/export/{id}` | Export an approved filing to JSON/CSV |
| POST | `/api/export/batch` | Export all approved filings |
| GET  | `/api/export/list` | List existing exports |

### Configuration (Expert Settings)
| Method | Path | Description |
|--------|------|-------------|
| GET/PUT | `/api/hints` | List issuer hint slugs |
| GET/PUT | `/api/hints/cross-issuer` | Cross-issuer extraction hints |
| GET/PUT | `/api/hints/issuers/{slug}` | Per-issuer hints |
| GET/PUT | `/api/hints/issuers/{slug}/fields/{fieldPath}` | Per-issuer, per-field hint |
| GET/PUT | `/api/sections` | List section configs |
| GET/PUT | `/api/sections/{name}` | Get/update a section config |
| GET/PUT | `/api/settings` | Runtime extraction settings |

---

## Key Features

### Image Downloading
During ingest, the backend automatically downloads formula images (`<img>` tags) from the same EDGAR filing folder and saves them alongside `raw.html`. Image filenames are recorded in `metadata.json` under the `"images"` key. For filings already in the database, use `POST /api/filings/{id}/fetch-images` or run `scripts/backfill_images.py`.

### Financial Glossary
`files/financial_glossary.md` is loaded into the extraction system prompt (mtime-cached). Add domain terminology here to improve extraction accuracy without code changes.

### Classification Override
For filings where the AI classifier returns a wrong or low-confidence result, reviewers can use the "Set Model" button in the UI to manually assign a PRISM model. The override is recorded in the `classification_feedback` table for audit and future few-shot use.

### Classification Reset
"↺ Reset" button (visible in `classified` and `needs_review` states) reverts a filing to `ingested` status, clearing all classification data. Blocked on `extracted`, `approved`, and `exported` states — re-extract or unapprove first.

### Architecture Diagram
`files/architecture.drawio` contains the full system architecture diagram (editable with draw.io desktop or draw.io.net).

---

## Status

| Component | Status |
|-----------|--------|
| Requirements | ✅ v0.2 |
| EDGAR API reference | ✅ Ready |
| Data model | ✅ Ready |
| Architecture diagram | ✅ `files/architecture.drawio` |
| PRISM schema file | ✅ `schemas/prism/prism-v1.schema.json` |
| CUSIP model mapping | ✅ `schemas/prism/CUSIP_PRISM_Mapping.xlsx` |
| Backend | ✅ Running |
| Frontend | ✅ Running |

---

*LPA Internal — Test System — Not for Production Use*
