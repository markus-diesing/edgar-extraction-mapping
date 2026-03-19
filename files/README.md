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
├── README.md           ← you are here
├── REQUIREMENTS.md     ← full functional requirements
├── EDGAR_API.md        ← EDGAR API reference and quirks
├── DATA_MODEL.md       ← database schema, PRISM format, export spec
├── SETUP.md            ← step-by-step setup for a new Mac
├── schemas/
│   └── prism/
│       ├── *.json              ← PRISM schema files (one per payout type)
│       └── cusip_model_mapping.xlsx  ← CUSIP-to-model reference
├── backend/            ← Python / FastAPI
├── frontend/           ← React / Vite
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

**Critical rules:**
- All paths MUST be relative to project root (see `DATA_MODEL.md` section 5)
- `ANTHROPIC_API_KEY` is from environment variable only — never write it to a file
- SQLite only — no PostgreSQL, no Redis, no Docker required
- No authentication — single local user, no login screens
- Schema-as-config — classification and extraction prompts load payout types from `schemas/prism/` at runtime

---

## Status

| Component | Status |
|-----------|--------|
| Requirements | ✅ v0.2 |
| EDGAR API reference | ✅ Ready |
| Data model | ✅ Ready |
| PRISM schema file(s) | ✅ Present in `schemas/prism/` |
| CUSIP model mapping | ✅ Present in `schemas/prism/` |
| Backend | 🔴 Not yet built |
| Frontend | 🔴 Not yet built |

---

*LPA Internal — Test System — Not for Production Use*
