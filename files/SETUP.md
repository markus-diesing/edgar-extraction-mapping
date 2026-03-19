# SETUP.md
# EDGAR Extraction & Mapping — Setup Guide

> **Platform:** macOS (Apple Silicon or Intel)
> **Last updated:** 2026-03-18

---

## Prerequisites

Install these once on your Mac (system-wide). Everything else is project-local.

| Tool | Version | Install |
|------|---------|---------|
| Python | 3.11 or 3.12 | `brew install python@3.12` or [python.org](https://www.python.org/downloads/) |
| Node.js | 20+ | `brew install node` or [nodejs.org](https://nodejs.org/) |
| Git | any | pre-installed on macOS, or `brew install git` |

Verify:
```bash
python3 --version   # should show 3.11.x or 3.12.x
node --version      # should show v20.x.x or higher
```

---

## Step 1 — Copy the Project Folder

Place the `EDGAR-Extraction_Mapping/` folder wherever you like on your Mac. All paths are relative — location does not matter.

```bash
cd EDGAR-Extraction_Mapping
```

All subsequent commands assume you are in the project root.

---

## Step 2 — Set Your Anthropic API Key

The API key is **never stored in files**. Set it as an environment variable in your shell.

**For the current terminal session only:**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

**To persist across sessions (add to your shell profile):**
```bash
echo 'export ANTHROPIC_API_KEY="sk-ant-..."' >> ~/.zshrc
source ~/.zshrc
```

Verify:
```bash
echo $ANTHROPIC_API_KEY   # should print your key
```

---

## Step 3 — Backend Setup (Python)

```bash
cd backend

# Create a virtual environment inside the project folder
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

cd ..
```

The virtual environment lives at `backend/.venv/` — it stays inside the project folder and travels with it.

---

## Step 4 — Create Required Directories

```bash
mkdir -p data/filings data/db data/exports logs schemas/prism
```

---

## Step 5 — Initialise the Database

```bash
cd backend
source .venv/bin/activate
python main.py init-db
cd ..
```

This creates `data/db/edgar_extraction.db` with the required tables.

---

## Step 6 — Frontend Setup (Node.js / React)

```bash
cd frontend

# Install dependencies (into frontend/node_modules — project-local)
npm install

cd ..
```

---

## Step 7 — Verify Schema Files

Your `schemas/prism/` folder should already contain:
- At least one PRISM schema JSON file (e.g., `barrier_reverse_convertible_v1.json`)
- The CUSIP model mapping file: `cusip_model_mapping.xlsx`

Verify:
```bash
ls schemas/prism/
```

If the folder is empty, add your schema files before proceeding — the application requires at least one schema to classify and extract.

See `DATA_MODEL.md` section 3 for the expected JSON structure of schema files.

---

## Step 8 — Run the Application

You need two terminal windows (or tabs).

**Terminal 1 — Backend:**
```bash
cd EDGAR-Extraction_Mapping/backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

**Terminal 2 — Frontend:**
```bash
cd EDGAR-Extraction_Mapping/frontend
npm run dev
```

Open your browser at: **http://localhost:5173**

---

## Stopping the Application

Press `Ctrl+C` in each terminal window. Data in `data/db/` and `data/exports/` persists.

---

## Transferring to Another Mac

1. Copy the entire `EDGAR-Extraction_Mapping/` folder to the new machine
2. Delete `backend/.venv/` and `frontend/node_modules/` before copying (they are platform-specific binaries) — or just delete them on the new machine
3. Follow Steps 1–8 above on the new machine

**What to exclude when copying (platform-specific, always regenerated):**
```
backend/.venv/
frontend/node_modules/
data/db/            # optional: exclude if you want a clean start
data/filings/       # optional: exclude to save space (re-downloadable from EDGAR)
                    # keep if you want to transfer acquired filings for offline testing
logs/
```

A `.gitignore` in the project root excludes these automatically if using Git.

---

## Troubleshooting

**`ModuleNotFoundError` in backend:**
Make sure the virtual environment is activated: `source backend/.venv/bin/activate`

**`ANTHROPIC_API_KEY not set` error:**
Run `export ANTHROPIC_API_KEY="sk-ant-..."` in the same terminal as the backend.

**Port already in use:**
Change the port: `uvicorn main:app --reload --port 8001` and update the frontend proxy config in `frontend/vite.config.js` accordingly.

**EDGAR returns 403 or 429:**
You may be hitting the rate limit. Wait 60 seconds and try again. Check that the `User-Agent` header in `backend/config.py` is set correctly.

---

*End of SETUP.md*
