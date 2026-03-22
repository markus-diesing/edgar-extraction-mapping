"""
FastAPI application entry point.

Start with:
    uvicorn main:app --reload --port 8000

Or initialise the database only:
    python main.py init-db
"""
import logging
import sys
from contextlib import asynccontextmanager

# ── Credential bootstrap ──────────────────────────────────────────────────────
# Must run before `import config` so that os.environ["ANTHROPIC_API_KEY"] is
# populated when config.py evaluates it at module-import time.
from credential_loader import load_api_key
load_api_key()
# ─────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import config
import database
import schema_loader
from ingest.router   import router as ingest_router
from classify.router import router as classify_router
from extract.router  import router as extract_router
from export.router   import router as export_router
from hints.router    import router as hints_router
from sections.router import router as sections_router
from settings.router import router as settings_router
from admin.router          import router as admin_router
from admin.label_map_router import router as label_map_router
from admin.schema_router import router as schema_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOGS_DIR / "app.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")

# Suppress per-request uvicorn access logs — they use a different format and
# flood the log file with health-check polls every 30 s from the frontend.
# WARNING level still surfaces 4xx/5xx access events.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config.ensure_dirs()
    database.init_db()
    log.info("Database initialised at %s", config.DB_PATH)

    models = schema_loader.list_models()
    log.info("PRISM schema loaded — %d models: %s", len(models), models)

    mapping = schema_loader.load_cusip_mapping()
    log.info("CUSIP mapping loaded — %d entries", len(mapping))

    if config.ANTHROPIC_API_KEY:
        log.info("ANTHROPIC_API_KEY loaded — classify/extract available")
    else:
        log.warning(
            "ANTHROPIC_API_KEY is not set — classify/extract will fail. "
            "Run: python scripts/setup_key.py"
        )

    yield
    # Shutdown (nothing to clean up)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="EDGAR Extraction & Mapping",
    description="Local pipeline: EDGAR 424B2 → PRISM schema extraction",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router,   prefix="/api")
app.include_router(classify_router, prefix="/api")
app.include_router(extract_router,  prefix="/api")
app.include_router(export_router,   prefix="/api")
app.include_router(hints_router,    prefix="/api")
app.include_router(sections_router, prefix="/api")
app.include_router(settings_router, prefix="/api")
app.include_router(admin_router,     prefix="/api")
app.include_router(label_map_router, prefix="/api")
app.include_router(schema_router, prefix="/api")


# ---------------------------------------------------------------------------
# Documentation support chat — used by the HTML user manuals
# ---------------------------------------------------------------------------
from pydantic import BaseModel as _BaseModel


class _ChatRequest(_BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/docs/chat")
async def docs_chat(req: _ChatRequest):
    import anthropic as _anthropic
    client = _anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    system = (
        "You are a helpful assistant for the EDGAR Extraction & PRISM Mapping tool built by "
        "Lucht Probst Associates (LPA). This is an internal POC tool that:\n"
        "- Ingests SEC EDGAR 424B2 structured product filings\n"
        "- Classifies them into PRISM data model types using Claude AI\n"
        "- Extracts PRISM fields using a hybrid approach: HTML table parsing (Tier 1), "
        "EDGAR registry data (Tier 0), and LLM extraction (Tier 2)\n"
        "- Provides an Expert UI for reviewing, correcting, and approving extracted fields\n"
        "- Exports to JSON/CSV for downstream PRISM ingestion\n\n"
        "Key components: Filings view (list + detail), Expert view (Field Hints, Section Prompts, "
        "Extraction Settings, Label Map, Schema), Admin view (Logs, Cost & Usage).\n\n"
        "Answer questions about how to use the tool, troubleshoot issues, and explain concepts. "
        "Be concise and practical."
    )
    messages = req.history[-10:] + [{"role": "user", "content": req.message}]
    try:
        resp = client.messages.create(
            model=config.CLAUDE_MODEL_DEFAULT,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return {"reply": resp.content[0].text}
    except Exception as e:
        return {"reply": f"Sorry, I couldn't reach the AI assistant: {e}"}


@app.get("/api/health")
def health():
    models = schema_loader.list_models()
    mapping = schema_loader.load_cusip_mapping()
    return {
        "status": "ok",
        "prism_models": models,
        "cusip_mapping_count": len(mapping),
        "anthropic_key_set": bool(config.ANTHROPIC_API_KEY),
    }


# ---------------------------------------------------------------------------
# CLI helper: python main.py init-db
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "init-db":
        config.ensure_dirs()
        database.init_db()
        print(f"Database initialised at {config.DB_PATH}")
    else:
        print("Usage: python main.py init-db")
        print("To run the server: uvicorn main:app --reload --port 8000")
