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
from datetime import datetime as _datetime
from pathlib import Path

# ── Credential bootstrap ──────────────────────────────────────────────────────
# Must run before `import config` so that os.environ["ANTHROPIC_API_KEY"] is
# populated when config.py evaluates it at module-import time.
from credential_loader import load_api_key
load_api_key()
# ─────────────────────────────────────────────────────────────────────────────

import anthropic as _anthropic

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
from underlying.router import router as underlying_router

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

# Shared Anthropic client for the docs chat endpoint — instantiated once at
# startup so the constructor cost (env-var reads, attribute wiring) is not
# repeated on every request.
_docs_chat_client = _anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

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
app.include_router(underlying_router, prefix="/api")

# Serve the docs/ directory at /docs so user_manual.html and other HTML docs
# are on the same origin as the API (required for the in-manual chat to work).
app.mount("/docs", StaticFiles(directory=config.PROJECT_ROOT / "docs"), name="docs")


# ---------------------------------------------------------------------------
# Documentation support chat — used by the HTML user manuals
# ---------------------------------------------------------------------------
from pydantic import BaseModel as _BaseModel


class _ChatRequest(_BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/docs/chat")
async def docs_chat(req: _ChatRequest):
    system = (
        "You are a concise chat assistant embedded in the user manual for the EDGAR Extraction "
        "& PRISM Mapping tool — an internal POC by Lucht Probst Associates (LPA).\n\n"
        "The tool ingests SEC EDGAR 424B2 structured product filings, classifies them into PRISM "
        "data model types using Claude AI, extracts PRISM fields, and exports to JSON/CSV. "
        "Key UI areas: Filings (list + detail), Expert ⚙ (Field Hints, Section Prompts, "
        "Extraction Settings, Label Map, Schema), Admin (Logs, Cost & Usage).\n\n"
        "RESPONSE RULES — follow these strictly:\n"
        "- Answer in 2–4 sentences OR a bullet list of 3–5 items. Never both.\n"
        "- Never use markdown tables, horizontal rules (---), or headings (##).\n"
        "- Use **bold** only for a single key term per response, if helpful.\n"
        "- Use inline `code` only for field names or UI labels.\n"
        "- If the question is broad, give a focused one-paragraph answer and invite a follow-up "
        "on a specific aspect rather than trying to cover everything.\n"
        "- Tone: direct, practical, no filler phrases."
    )
    # Build message list: trim history to last 10 messages, then ensure the
    # window starts on a user turn so the alternating role requirement is met.
    trimmed = req.history[-10:]
    if trimmed and trimmed[0].get("role") != "user":
        trimmed = trimmed[1:]  # drop leading assistant message
    messages = trimmed + [{"role": "user", "content": req.message}]
    try:
        resp = _docs_chat_client.messages.create(
            model=config.CLAUDE_MODEL_DEFAULT,
            max_tokens=1024,
            system=system,
            messages=messages,
        )
        return {"reply": resp.content[0].text}
    except Exception as e:
        return {"reply": f"Sorry, I couldn't reach the AI assistant: {e}"}


# ---------------------------------------------------------------------------
# Docs manifest — used by docs/index.html landing page
# ---------------------------------------------------------------------------
@app.get("/api/docs/manifest")
def docs_manifest():
    """Return metadata for all documentation files under docs/ subfolders."""
    docs_root = config.PROJECT_ROOT / "docs"

    CATEGORIES = {
        "project":  {"label": "Project Fundamentals", "icon": "🏗"},
        "plans":    {"label": "Implementation Plans",  "icon": "📋"},
        "specs":    {"label": "Specifications",        "icon": "📐"},
        "research": {"label": "Research & Analysis",   "icon": "🔬"},
        "taxonomy": {"label": "Product Taxonomy",      "icon": "🗂"},
        "tracking": {"label": "Tasks & Backlog",       "icon": "✅"},
        "dev":      {"label": "Developer Notes",       "icon": "⚙️"},
    }
    HTML_DOCS = [
        {"name": "User Manual",        "file": "user_manual.html",  "abstract": "Step-by-step guide to ingesting, classifying, extracting, and exporting structured product filings."},
        {"name": "Tech Handbook",      "file": "tech_handbook.html","abstract": "Architecture, component design, API reference, and backend internals."},
        {"name": "Architecture",       "file": "architecture.html", "abstract": "Visual architecture diagrams for the tool pipeline and data flows."},
    ]

    def _abstract(path: Path) -> str:
        """Extract first substantive paragraph from a markdown file.

        Reads the file line-by-line and stops as soon as 3 content lines are
        collected, avoiding loading the full file into memory.
        """
        try:
            para: list[str] = []
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    is_skip = (
                        not stripped
                        or stripped.startswith("#")
                        or (stripped.startswith("**") and stripped.endswith("**"))
                        or stripped.startswith("---")
                        or stripped.startswith("*Last")
                        or stripped.startswith("*Date")
                    )
                    if is_skip:
                        if para:
                            break
                        continue
                    para.append(stripped)
                    if len(para) >= 3:
                        break
            result = " ".join(para)
            return result[:240] + ("…" if len(result) > 240 else "")
        except Exception:
            return ""

    categories_out = []
    # Static HTML docs first
    html_files = []
    for h in HTML_DOCS:
        p = docs_root / h["file"]
        if p.exists():
            mtime = _datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
            html_files.append({"name": h["name"], "url": f"/docs/{h['file']}", "type": "html",
                                "last_modified": mtime, "abstract": h["abstract"]})
    if html_files:
        categories_out.append({"key": "guides", "label": "Interactive Guides", "icon": "📖", "files": html_files})

    # Markdown docs by category subfolder
    for key, meta in CATEGORIES.items():
        folder = docs_root / key
        if not folder.is_dir():
            continue
        files_out = []
        for md in sorted(folder.glob("*.md")):
            mtime = _datetime.fromtimestamp(md.stat().st_mtime).strftime("%Y-%m-%d")
            url = f"/docs/{key}/{md.name}"
            files_out.append({"name": md.stem.replace("_", " ").title(),
                               "filename": md.name, "url": url, "type": "markdown",
                               "last_modified": mtime, "abstract": _abstract(md)})
        if files_out:
            categories_out.append({"key": key, "label": meta["label"], "icon": meta["icon"], "files": files_out})

    return {"categories": categories_out}


_health_cache: dict | None = None
_health_cache_at: float = 0.0
_HEALTH_TTL = 30.0  # seconds — refresh at most every 30 s


@app.get("/api/health")
def health():
    """Return backend health.  Response is cached for _HEALTH_TTL seconds
    to avoid repeated file-I/O from the frontend's 30 s polling interval."""
    import time as _time
    global _health_cache, _health_cache_at
    now = _time.monotonic()
    if _health_cache is None or (now - _health_cache_at) > _HEALTH_TTL:
        models  = schema_loader.list_models()
        mapping = schema_loader.load_cusip_mapping()
        _health_cache = {
            "status": "ok",
            "prism_models": models,
            "cusip_mapping_count": len(mapping),
            "anthropic_key_set": bool(config.ANTHROPIC_API_KEY),
        }
        _health_cache_at = now
    return _health_cache


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
