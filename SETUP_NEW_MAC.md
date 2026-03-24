# EDGAR Extraction & PRISM Mapping — New Machine Setup Guide

**Project:** EDGAR Extraction & PRISM Mapping POC
**Developed by:** Lucht Probst Associates (LPA)
**Last updated:** 2026-03-23

---

## ⚠️ Before You Start — Anthropic API Key

You **must** obtain a **new, personal Anthropic API key** for this machine.
**Do not use or ask for the key from the machine this was transferred from.**
Each user / machine should run on its own key so usage is tracked separately and the originating key can be rotated independently.

How to get one:
1. Go to [https://console.anthropic.com](https://console.anthropic.com)
2. Sign in or create an account
3. Navigate to **API Keys** → **Create Key**
4. Copy the key (it starts with `sk-ant-api03-…`) — you will not be able to see it again
5. Keep it in a password manager until you complete Step 5 below

---

## Prerequisites

Install the following before proceeding. All are free and available via Homebrew.

### 1. Homebrew (macOS package manager)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Python 3.12

```bash
brew install python@3.12
```

Verify:
```bash
python3 --version   # must be 3.11 or higher
```

### 3. Node.js 20

```bash
brew install node@20
brew link node@20
```

Verify:
```bash
node --version    # must be 18 or higher
npm --version
```

---

## Step 1 — Unzip the Project

Unzip to a location of your choice. This guide uses `~/Projects/` as an example:

```bash
mkdir -p ~/Projects
unzip EDGAR-Extraction_Mapping.zip -d ~/Projects/
cd ~/Projects/EDGAR-Extraction_Mapping
```

The project structure you should see:

```
EDGAR-Extraction_Mapping/
├── backend/          ← FastAPI Python backend
├── frontend/         ← React UI
├── docs/             ← All documentation and HTML guides
├── files/            ← Hints, label maps, schemas, runtime config
├── schemas/          ← PRISM JSON schemas and CUSIP mapping
├── scripts/          ← Utility scripts (including key setup)
├── tests/            ← Unit and integration tests
├── data/             ← Will be created on first run (DB, filings cache)
├── .env.example      ← API key fallback template (see Step 5)
└── SETUP_NEW_MAC.md  ← This file
```

---

## Step 2 — Python Virtual Environment

The backend runs in an isolated virtual environment. Create it inside the `backend/` folder:

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

You should see all packages install cleanly. The key ones are:
`fastapi`, `uvicorn`, `anthropic`, `sqlalchemy`, `httpx`, `beautifulsoup4`, `keyring`

To deactivate the venv when done: `deactivate`

---

## Step 3 — Frontend Dependencies

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/frontend
npm install
```

This installs React, Vite, and all UI dependencies into `frontend/node_modules/`.

> **Note:** A pre-built version of the frontend is included at `frontend/dist/`. If you only want to use the app (not develop the UI), you can skip `npm install` — the backend serves the built bundle directly. You'll need `npm install` only if you want to run the Vite dev server or rebuild the UI.

---

## Step 4 — Initialise the Database

The app uses a local SQLite database. Create it now:

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/backend
source .venv/bin/activate
python main.py init-db
```

Expected output:
```
Database initialised at .../data/db/edgar_extraction.db
```

---

## Step 5 — Configure Your Anthropic API Key

The key is stored in the **macOS Keychain** — never written to any file on disk. Run the setup script once:

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/backend
source .venv/bin/activate
cd ..
python scripts/setup_key.py
```

The script will prompt you to paste your key (input is hidden). It verifies the round-trip to Keychain before confirming success.

```
EDGAR Extraction — Anthropic API Key Setup
=============================================
  Keyring service : edgar-extraction
  Keyring username: anthropic_api_key

Paste your Anthropic API key (input hidden):
Key stored successfully in the OS keyring.
```

**Alternative — .env file (less secure, use only for testing):**

If Keychain causes issues, copy `.env.example` to `.env` and add your key:

```bash
cp .env.example .env
# Edit .env and set:
# ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE
```

The backend reads the key in this priority order: environment variable → Keychain → `.env` file.

---

## Step 6 — Start the Application

Open **two terminal tabs/windows**:

### Terminal 1 — Backend

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/backend
source .venv/bin/activate
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

### Terminal 2 — Frontend (Vite dev server, optional)

Only needed if you want hot-reload during UI development:

```bash
cd ~/Projects/EDGAR-Extraction_Mapping/frontend
npm run dev
```

The React dev server runs on **http://localhost:5173**.

> If you don't start the Vite dev server, open the frontend via the backend directly:
> **http://localhost:5173** won't work, but you can access the docs at **http://localhost:8000/docs/index.html**

---

## Step 7 — Verify the Installation

With the backend running, check the health endpoint:

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{
  "status": "ok",
  "prism_models": ["yieldEnhancementCoupon", "yieldEnhancementBarrierCoupon", ...],
  "cusip_mapping_count": 9,
  "anthropic_key_set": true
}
```

`anthropic_key_set: true` confirms the API key was found. If it shows `false`, revisit Step 5.

---

## Step 8 — Run the Test Suite

Confirm everything is wired correctly by running the tests:

```bash
cd ~/Projects/EDGAR-Extraction_Mapping
backend/.venv/bin/python -m pytest tests/ -v
```

Expected output:
```
collected 47 items
...
47 passed in X.XXs
```

Integration tests (`tests/integration/`) hit the live backend — make sure it is running (Step 6) before you run the full suite. Unit tests (`tests/unit/`) run standalone.

---

## Step 9 — First Use

Open the **documentation landing page** to get oriented:

**http://localhost:8000/docs/index.html**

It links to all project documentation, including the **User Manual** which has a built-in chat assistant.

### Quick workflow

1. **Ingest** — Enter a CUSIP in the Filings view → Search EDGAR → Select a hit → Ingest
2. **Classify** — Open the filing → click **Classify** (Claude identifies the PRISM payout type)
3. **Extract** — Click **Extract** (Claude populates all PRISM fields; takes 30–120 s)
4. **Review** — Check field values, correct any with the Expert ⚙ panel
5. **Export** — Export to JSON or CSV for PRISM ingestion

A list of known-good CUSIPs for testing is in `CUSIP_Examples.txt` at the project root.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `anthropic_key_set: false` | Key not in Keychain | Re-run `scripts/setup_key.py` |
| `ModuleNotFoundError` on start | venv not activated | `source backend/.venv/bin/activate` |
| Frontend shows blank page | Backend not running | Start backend first (Step 6) |
| `database.db not found` | DB not initialised | Run `python main.py init-db` (Step 4) |
| Classify/Extract fails immediately | Key missing or invalid | Check `/api/health` → `anthropic_key_set` |
| Classify/Extract API error 5xx | Wrong model name in schema | Check `Admin → Schema` panel for active models |
| `npm: command not found` | Node not installed | `brew install node@20` |

### Resetting the API key

```bash
cd ~/Projects/EDGAR-Extraction_Mapping
source backend/.venv/bin/activate
python scripts/setup_key.py    # prompts to overwrite
```

### Checking stored key without revealing it

```bash
source backend/.venv/bin/activate
python -c "import keyring; k=keyring.get_password('edgar-extraction','anthropic_api_key'); print('Key set:', bool(k), '| Prefix:', k[:12] if k else 'n/a')"
```

---

## Project Contacts

For questions about the PRISM data model or schema, contact the PRISM schema team via the Azure DevOps wiki.

For questions about this tool's code or architecture, start with:
- `docs/project/README.md` — project overview
- `docs/tech_handbook.html` — full technical reference (open in browser via `http://localhost:8000/docs/tech_handbook.html`)
- `docs/user_manual.html` — end-user guide with embedded chat assistant
