# EDGAR Extraction & PRISM Mapping — Handover Brief

**Project:** EDGAR Extraction & PRISM Mapping POC
**Owner:** Lucht Probst Associates (LPA) — Markus
**Handed to:** *(your name)*
**Date:** 2026-04

---

## Part 1 — What This Project Is

### The Problem

LPA's PRISM platform models structured financial products (autocalls, barrier notes, yield enhancements, etc.). To populate PRISM with data, someone currently reads SEC EDGAR filing PDFs (424B2 prospectuses) manually and enters the field values by hand. That is slow, inconsistent, and doesn't scale as the PRISM team adds new product models.

### The Solution

This tool is a **local AI-assisted pipeline** that:

1. **Ingests** a 424B2 filing from EDGAR given a CUSIP number — downloads, parses, and stores the full text
2. **Classifies** the filing into the correct PRISM model type (e.g. `yieldEnhancementCoupon`, `capitalProtectedNote`) using Claude AI (~15 s)
3. **Extracts** all PRISM schema fields from the filing text using Claude AI (30–120 s), with per-field confidence scores
4. **Allows review** — the analyst accepts or rejects individual fields, can manually edit values, and leaves a review trail
5. **Exports** the accepted fields to JSON or CSV for import into PRISM

It is a **POC** — local-only, single-user, no auth, SQLite backend. The goal is to validate whether AI extraction is accurate enough to be worth investing in productionisation.

### What "Done" Looks Like for the POC

- Demonstrate end-to-end workflow on ≥ 5 product types from the PRISM schema
- Measure extraction accuracy (field-level accept/reject ratios) across a sample of real filings
- Present findings to the PRISM schema team and decide whether to productionise

### Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, SQLite (via `sqlite3`), Anthropic SDK |
| Frontend | React 18, Vite, plain CSS |
| AI | Claude claude-sonnet-4-5 (classify + extract) |
| Infra (dev) | Docker Compose (optional), or two terminal windows |

### Project Structure

```
edgar-extraction-prism-mapping/
├── backend/          FastAPI app, all Python logic
│   ├── classify/     Two-stage classifier (PRISM model type)
│   ├── extract/      Section router + field extractor + label mapper
│   ├── ingest/       EDGAR EDGAR download + text parsing
│   ├── export/       JSON / CSV export with schema validation
│   ├── admin/        Logs, cost tracking, schema/label admin
│   ├── schemas/      PRISM JSON schemas (fetched from PRISM team)
│   ├── files/        Runtime config: hints, label maps, section prompts
│   ├── data/         SQLite DB + filing text cache
│   └── tests/        87 pytest tests
├── frontend/         React UI (Filings list, Detail, Expert panel, Admin)
├── docs/             All project docs + HTML user manual + tech handbook
└── handover/         This folder
```

---

## Part 2 — Current State

### What Works (as of handover)

- Full ingest → classify → extract → review → export workflow for all 9 PRISM models currently in the schema
- Three-state classification: `classified` (≥0.80 confidence), `needs_classification_review` (0.60–0.79), `needs_review` (<0.60)
- Manual confirm/override of classification with audit trail
- Section-by-section extraction (routes different schema groups to the relevant filing section)
- Per-field confidence scores, accept/reject UI
- Admin panel: API cost tracking, log viewer
- Expert panel: field hints editor, section prompt editor, label map editor, schema viewer
- Docker Compose stack for easy startup
- 103 real filings in the included database (representative sample across product types)
- 87 passing tests

### Open Tasks (priority order)

**A1 — classificationHints team discussion (CRITICAL)**
The spec `SPEC_CLASSIFICATION_HINTS_FORMAT.md` is ready. The infrastructure in `classifier.py` already reads `classificationHints` blocks from the schema and feeds them into the classification prompt automatically. The action needed is to bring this spec to the PRISM schema team at their next meeting so they adopt the format as they add new models. Currently the `yieldEnhancementCoupon` model is missing its description — this causes the classifier to rely purely on document content for that type.

**C2 — Stage 1 feature extraction prompt (~2 h)**
`files/payout_features.json` defines a 22-dimension feature vector (COUPON_TYPE, CALL_TYPE, DOWNSIDE_PROTECTION_TYPE, HAS_* flags). Implementing a structured prompt to extract this vector as JSON would give a stable intermediate representation before model classification and an audit trail. Reference design in `docs/research/NOTE_LLM_FUZZY_PRISM_MATCHING.md`.

**D3 — Remove old drawio file (5 min)**
`files/architecture.drawio` is superseded by `files/architecture_260322.drawio`. Delete to avoid confusion.

**C3 — Few-shot title examples per model (~1 h content)**
After A1 agreement: add `title_keywords` and representative product titles to each model's `classificationHints` block in the schema.

**C4 — Export validation messaging (~1 h)**
Surface schema validation errors more clearly in the export UI (currently they're in the API response body but not shown in the UI).

**Schema pending diffs (check before working)**
Three pending schema diffs in `data/schema_diffs/` were not yet reviewed at handover:
`20260325_152904`, `20260326_124256`, `20260326_125552`. Review and apply via Admin → Schema panel before running new extractions.

### Known Limitations

- Single-user, no authentication — do not expose to a network
- Extraction accuracy varies by filing quality and product complexity. Barrier and autocall products with complex term sheets score lower
- The PRISM schema evolves weekly — keep the schema current using Admin → Schema → Fetch Latest
- No multi-user session tracking — one analyst at a time is the intended usage

---

## Part 3 — Opening Prompt for Claude Code

Copy and paste the block below at the start of your first Claude Code session on this project.

---

```
You are about to work on the EDGAR Extraction & PRISM Mapping POC, an internal LPA project. Please read the following context carefully before making any changes.

## Project Purpose
A local AI pipeline that ingests SEC EDGAR 424B2 structured product filings, classifies them into PRISM data model types using Claude AI, extracts PRISM schema fields, and exports the results for PRISM ingestion. This is a proof-of-concept to validate AI-assisted data extraction accuracy before any productionisation decision.

## Stack
- Backend: Python 3.13, FastAPI, SQLite, Anthropic SDK (claude-sonnet-4-5)
- Frontend: React 18 + Vite (dev server on :5173, proxies /api to :8000)
- Tests: pytest, 87 tests in backend/tests/

## Key Files to Read First
1. `handover/HANDOVER_BRIEF.md` — project context, current state, open tasks
2. `docs/tech_handbook.html` — full architecture + API reference (open via browser once backend is running)
3. `docs/tracking/OPEN_TASKS.md` — prioritised backlog

## How to Start the App
Open two terminals:
  Terminal 1 (backend):  cd backend && .venv\Scripts\activate && uvicorn main:app --reload --port 8000
  Terminal 2 (frontend): cd frontend && npm run dev
Then open: http://localhost:5173

## Architecture Notes
- `backend/classify/classifier.py` — two-stage classification using Claude. Uses module-level `_get_client()` singleton.
- `backend/extract/extractor.py` — section-by-section extraction. `_slice_filing_text()` routes text by section; `_clamp_conf()` normalises confidence values.
- `backend/extract/label_mapper.py` — maps filing table labels to PRISM schema paths via YAML lookup with normalisation.
- `backend/extract/section_router.py` — defines `SectionSpec` dataclasses that map schema groups to filing sections.
- `backend/schema_loader.py` — dynamic PRISM schema loading; `list_models()` and `_get_model_descriptions()` are fully dynamic.
- `backend/credential_loader.py` — loads API key from: env var → Windows Credential Manager → .env file.
- `backend/config.py` — all path constants; `PROJECT_ROOT = Path(__file__).parent.parent`.

## Database
SQLite at `data/db/edgar_extraction.db`. Tables: `filings`, `extraction_results`, `field_results`, `edit_log`, `api_usage_log`, `classification_feedback`, `label_miss_log`. Included with 103 real filings.

## PRISM Schema
9 models in `schemas/prism-v1.schema.json`. Fetched from the PRISM team's Azure DevOps feed. Update via Admin → Schema → Fetch Latest. Three pending diffs in `data/schema_diffs/` should be reviewed first.

## Coding Standards
- Python: type hints on all function signatures, `pathlib.Path` for all file paths, no `os.path`
- Module-level constants preferred over per-call construction (see `_MONTH_NAMES` in `field_parsers.py`)
- No secrets in code — API key via `credential_loader.py` only
- Tests in `backend/tests/` — run with: `python -m pytest tests/ -v` (expect 87 passed)
- Line endings: Unix LF throughout — do not change to CRLF

## Top Priority Open Task
A1: The classificationHints spec (`docs/specs/SPEC_CLASSIFICATION_HINTS_FORMAT.md`) is ready. The infrastructure in `classifier.py` already reads these hints. The action needed is a team meeting with the PRISM schema team to adopt the format as they add new models. The `yieldEnhancementCoupon` model is currently missing its description — add it to the schema as a quick win.

## What I'd Like You to Do
[REPLACE THIS LINE WITH YOUR SPECIFIC TASK OR QUESTION]
```

---

## Part 4 — Useful Links

| Resource | URL / Location |
|---|---|
| App (once running) | http://localhost:5173 |
| API docs | http://localhost:8000/docs |
| Docs landing page | http://localhost:8000/docs/index.html |
| User Manual | http://localhost:8000/docs/user_manual.html |
| Tech Handbook | http://localhost:8000/docs/tech_handbook.html |
| PRISM schema team wiki | Azure DevOps (ask Markus for access) |
| Windows 11 setup guide | `handover/SETUP_WINDOWS11.md` |

---

*Questions? Contact Markus at LPA via Teams or email.*
