# ── EDGAR Extraction & PRISM Mapping — Backend ────────────────────────────────
# Python 3.13 slim; lxml needs libxml2/libxslt at runtime.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libxml2 \
        libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

# Working directory matches config.PROJECT_ROOT expectation:
#   config.py: PROJECT_ROOT = Path(__file__).parent.parent  →  /app
#   backend source lives at /app/backend → imports work as "import config" etc.
WORKDIR /app/backend

# ── Dependency layer (cached unless requirements.txt changes) ─────────────────
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Source ────────────────────────────────────────────────────────────────────
COPY backend/ .

# ── Static assets expected at /app/{files,schemas,docs} by config.py ─────────
# In local dev these are bind-mounted; in production they are baked into the image.
COPY files/    /app/files/
COPY schemas/  /app/schemas/
COPY docs/     /app/docs/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
