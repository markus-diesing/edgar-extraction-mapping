# SETUP.md
# EDGAR Extraction & Mapping — Setup Guide

> **Platform:** macOS (Apple Silicon or Intel) · Windows 11
> **Last updated:** 2026-03-19

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

## Step 2 — Store Your Anthropic API Key

The API key is stored in the **OS credential store** — never in any file in the project folder.

| Platform | Store used |
|----------|------------|
| macOS    | Keychain   |
| Windows  | Windows Credential Manager |
| Linux    | Secret Service (GNOME Keyring / KWallet) |

**One-time setup (run once per machine/user):**
```bash
# cd to the project root first, then activate the backend venv
cd EDGAR-Extraction_Mapping
source backend/.venv/bin/activate          # macOS / Linux
# backend\.venv\Scripts\activate           # Windows

python3 scripts/setup_key.py
```

The script prompts for your key (input hidden), stores it in the OS keyring, and verifies the round-trip. After that, `uvicorn main:app` picks up the key automatically — no `export` needed in any terminal.

**Fallback options (if keyring is unavailable):**

*Environment variable — current session only:*
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

*`.env` file — persists across sessions (add to `.gitignore`):*
```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
chmod 600 .env
echo '.env' >> .gitignore
```

The backend checks sources in this order: environment variable → OS keyring → `.env` file.

**Windows note:** if `setup_key.py` fails with a keyring backend error, install the Windows helper:
```
pip install pywin32
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
- `prism-v1.schema.json` — the PRISM JSON Schema (all models in one file)
- `CUSIP_PRISM_Mapping.xlsx` — CUSIP-to-model reference table

Verify:
```bash
ls schemas/prism/
# Expected output:
# CUSIP_PRISM_Mapping.xlsx   prism-v1.schema.json
```

The application loads models dynamically from `prism-v1.schema.json` at startup.
When Chroma publishes a new schema version, replace the file — no code changes needed.

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

## Utility Scripts

### setup_key.py — Store Anthropic API key in OS keyring

Run once per machine/user after the venv is set up:

```bash
cd EDGAR-Extraction_Mapping
source backend/.venv/bin/activate
python3 scripts/setup_key.py
```

To update the key after rotation, run the script again — it will prompt before overwriting.
To remove the key: `python3 -c "import keyring; keyring.delete_password('edgar-extraction', 'anthropic_api_key')"`

---

### backfill_images.py — Download images for existing filings

During ingest the pipeline automatically saves formula images alongside `raw.html`. Filings ingested before this feature was added (or any filing where the image list is empty) can be updated in bulk:

```bash
cd EDGAR-Extraction_Mapping
# Backend must be running first (see Step 8)

# Backfill only filings that have no images recorded
python3 scripts/backfill_images.py

# Re-run for every filing (e.g., after adding support for new image extensions)
python3 scripts/backfill_images.py --all
```

### retry_failed_ingest.py — Retry failed ingest attempts

```bash
python3 scripts/retry_failed_ingest.py
```

---

## Transferring to Another Machine

The project folder contains no credentials — the API key lives in the OS keyring, not the directory. Handoff is clean.

**Steps on the receiving machine:**
1. Copy the `EDGAR-Extraction_Mapping/` folder (see exclusions below)
2. Install prerequisites for the target platform (see Prerequisites section)
3. Follow Steps 3–8 above
4. Run `python scripts/setup_key.py` once to store the key in the new machine's OS keyring

**macOS → Windows specifics:**
- Use `backend\.venv\Scripts\activate` instead of `source backend/.venv/bin/activate`
- Node/npm commands are identical
- Python 3.11/3.12 from [python.org](https://www.python.org/downloads/windows/) — ensure "Add to PATH" is checked during install
- If keyring fails: `pip install pywin32`

**What to exclude when copying (platform-specific, always regenerated):**
```
backend/.venv/
frontend/node_modules/
data/db/            # optional: exclude if you want a clean start
data/filings/       # optional: exclude to save space (re-downloadable from EDGAR)
                    # keep if you want to transfer acquired filings for offline use
logs/
.env                # never copy — recipient stores their own key via setup_key.py
```

A `.gitignore` in the project root excludes these automatically if using Git.

---

## Troubleshooting

**`ModuleNotFoundError` in backend:**
Make sure the virtual environment is activated: `source backend/.venv/bin/activate`

**`ANTHROPIC_API_KEY is not set` warning at backend startup:**
Run the one-time setup: `python scripts/setup_key.py`
Or for a single session: `export ANTHROPIC_API_KEY="sk-ant-..."` (macOS/Linux) / `set ANTHROPIC_API_KEY=sk-ant-...` (Windows CMD).

**Port already in use:**
Change the port: `uvicorn main:app --reload --port 8001` and update the frontend proxy config in `frontend/vite.config.js` accordingly.

**EDGAR returns 403 or 429:**
You may be hitting the rate limit. Wait 60 seconds and try again. Check that the `User-Agent` header in `backend/config.py` is set correctly.

---

*End of SETUP.md*
