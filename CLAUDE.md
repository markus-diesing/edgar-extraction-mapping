# EDGAR Extraction & Mapping

## Project overview
Python/React application that ingests SEC EDGAR 424B2 structured product filings,
classifies them by payout type, extracts PRISM schema fields via Claude LLM, and
maintains a reference database of underlying securities.

## Stack
- **Backend**: Python 3.13, FastAPI, SQLAlchemy 2, SQLite, Alembic
- **Frontend**: React 18, Vite
- **LLM**: Anthropic Claude (claude-sonnet-4-6) via `anthropic` SDK
- **Data sources**: SEC EDGAR API, yfinance, OpenFIGI

## Layout
```
backend/          FastAPI application
  classify/       Filing classification pipeline
  extract/        PRISM field extraction pipeline
  ingest/         EDGAR filing download + EDGAR client
  underlying/     Underlying securities data module (new)
  alembic/        Database migrations
  tests/          pytest test suite (425 tests)
frontend/src/     React UI
  components/     Panel components (filings, underlyings, admin)
data/db/          SQLite database (gitignored)
files/            Config YAMLs and field definitions
schemas/prism/    PRISM JSON schema
docs/specs/       Module specifications
```

## Running locally
```bash
# Backend
cd backend && .venv/bin/uvicorn main:app --port 8000 --reload

# Frontend
cd frontend && npm run dev
```

## Tests
```bash
cd backend && .venv/bin/python -m pytest tests/ -q
# 425 passed, 0 failed
```

## Key modules
- `backend/underlying/` — three-tier pipeline: EDGAR metadata (Tier 1),
  LLM cover-page extraction (Tier 2), yfinance market data (Tier 3)
- `backend/ingest/edgar_client.py` — EDGAR HTTP client with rate limiting + retry
- `backend/database.py` — all ORM models; Alembic migration helpers
# smoke test
