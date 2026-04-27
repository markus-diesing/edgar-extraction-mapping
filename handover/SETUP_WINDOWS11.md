# EDGAR Extraction & PRISM Mapping — Windows 11 Setup Guide

**Project:** EDGAR Extraction & PRISM Mapping POC
**Developed by:** Lucht Probst Associates (LPA)
**Target OS:** Windows 11 (22H2 or later)
**Last updated:** 2026-04

---

## ⚠️ Before You Start — Anthropic API Key

You **must** obtain a **new, personal Anthropic API key**.
Do **not** request or reuse the key from whoever sent you this package — each person runs on their own key so usage is tracked separately.

**How to get one:**
1. Go to [https://console.anthropic.com](https://console.anthropic.com)
2. Sign in or create an account
3. Navigate to **API Keys → Create Key**
4. Copy the key (starts with `sk-ant-api03-…`) — you cannot see it again after closing the page
5. Store it in a password manager until Step 5 below

---

## Prerequisites

Install the following before proceeding. All are free.

### 1. Python 3.13

Download the **Windows installer (64-bit)** from [https://www.python.org/downloads/](https://www.python.org/downloads/).

> **Critical during install:** Check **"Add Python to PATH"** on the first screen.

Verify in a new terminal (PowerShell or Command Prompt):
```powershell
python --version   # should show 3.13.x
```

### 2. Node.js 20 (LTS)

Download the **Windows Installer (.msi)** from [https://nodejs.org/](https://nodejs.org/).
Choose the **LTS** release (v20.x or later).

Verify:
```powershell
node --version    # 20.x or higher
npm --version
```

### 3. Git for Windows

Download from [https://git-scm.com/download/win](https://git-scm.com/download/win).
Accept all defaults during install. This also gives you **Git Bash** — useful but not required.

### 4. Docker Desktop for Windows (optional — only for the Docker workflow)

> You can run the project **without Docker** (native mode, Steps 2–6). Docker is a second option once native mode works.

If you want to use Docker:
1. Enable **WSL 2** first — open PowerShell as Administrator and run:
   ```powershell
   wsl --install
   ```
   Restart when prompted.
2. Download Docker Desktop from [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
3. During install, choose **"Use WSL 2 backend"**
4. After install, open Docker Desktop and wait for the whale icon in the system tray to show "Docker Desktop is running"

### 5. VS Code (recommended editor)

Download from [https://code.visualstudio.com/](https://code.visualstudio.com/).
Recommended extensions: **Python**, **ESLint**, **Prettier**, **YAML**.

---

## Step 1 — Unzip the Project

Unzip the handover archive to a folder of your choice. This guide uses `C:\Projects\` as an example.

Right-click the zip → **Extract All** → choose `C:\Projects\`

You should see:
```
C:\Projects\edgar-extraction-prism-mapping\
├── backend\          ← FastAPI Python backend
├── frontend\         ← React UI
├── docs\             ← All documentation and HTML guides
├── files\            ← Hints, label maps, runtime config
├── schemas\          ← PRISM JSON schemas
├── data\             ← Database (included with 103 real filings)
├── handover\         ← This setup guide and handover brief
├── Dockerfile
├── docker-compose.yml
├── start.bat         ← Windows startup script (Docker mode)
└── start.ps1         ← PowerShell startup script (Docker mode)
```

Open **PowerShell** and navigate to the project:
```powershell
cd C:\Projects\edgar-extraction-prism-mapping
```

---

## Step 2 — Python Virtual Environment

Create an isolated Python environment for the backend:

```powershell
cd backend
python -m venv .venv
```

Activate it:
```powershell
.venv\Scripts\activate
```

Your prompt will change to show `(.venv)`. Install dependencies:
```powershell
pip install -r requirements.txt
```

> **If you see:** `'python' is not recognized as an internal or external command`
> → Python was not added to PATH. Reinstall Python and check the "Add to PATH" box.

> **If you see:** `running scripts is disabled on this system`
> → Run this once in PowerShell as Administrator, then retry:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

To deactivate the venv when done: type `deactivate`

---

## Step 3 — Frontend Dependencies

```powershell
cd ..\frontend
npm install
```

This installs React, Vite, and all UI dependencies into `frontend\node_modules\`.

> **If npm install is slow or times out:** try adding `--prefer-offline` or check your network proxy settings.

---

## Step 4 — Initialise the Database

The database file is included in the zip (103 real filings already loaded). If for any reason you need to recreate it from scratch:

```powershell
cd ..\backend
.venv\Scripts\activate
python main.py init-db
```

Expected output:
```
Database initialised at ...data\db\edgar_extraction.db
```

---

## Step 5 — Configure Your Anthropic API Key

### Option A — Windows Credential Manager (recommended)

This is the Windows equivalent of macOS Keychain. Run once with your venv active:

```powershell
cd C:\Projects\edgar-extraction-prism-mapping
backend\.venv\Scripts\activate
python scripts\setup_key.py
```

The script will prompt you to paste your key (input is hidden) and stores it in Windows Credential Manager under the service name `edgar-extraction`.

To verify it was stored (shows only the prefix, not the full key):
```powershell
python -c "import keyring; k=keyring.get_password('edgar-extraction','anthropic_api_key'); print('Key set:', bool(k), '| Prefix:', k[:12] if k else 'n/a')"
```

### Option B — .env file (simpler, less secure)

Create a file called `.env` in the `backend\` folder:
```
ANTHROPIC_API_KEY=sk-ant-api03-YOUR-FULL-KEY-HERE
```

> ⚠️ Never commit `.env` to git. It is listed in `.gitignore` already.

The backend reads the key in this priority order: **environment variable → Credential Manager → .env file**

---

## Step 6 — Start the Application (Native Mode)

Open **two PowerShell windows**.

### Window 1 — Backend

```powershell
cd C:\Projects\edgar-extraction-prism-mapping\backend
.venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Application startup complete.
```

### Window 2 — Frontend (Vite dev server)

```powershell
cd C:\Projects\edgar-extraction-prism-mapping\frontend
npm run dev
```

Open your browser at **http://localhost:5173**

---

## Step 6b — Start the Application (Docker Mode)

If Docker Desktop is running, you can use the included batch scripts instead of the two-window approach above.

**Double-click `start.bat`**, or from PowerShell:
```powershell
cd C:\Projects\edgar-extraction-prism-mapping
.\start.bat
```

The first run takes 3–5 minutes (downloading base images). Every subsequent start takes ~5 seconds.

To stop: press **Ctrl+C** in the terminal, then:
```powershell
docker compose down
```

> **The `start.bat` script reads your API key from Windows Credential Manager** (set up in Step 5 Option A). If the key is not there, it falls back to the `.env` file.

---

## Step 7 — Verify the Installation

With the backend running, check the health endpoint in a new PowerShell window:

```powershell
Invoke-RestMethod http://localhost:8000/api/health | ConvertTo-Json
```

Or open [http://localhost:8000/api/health](http://localhost:8000/api/health) in your browser.

Expected response:
```json
{
  "status": "ok",
  "prism_models": ["yieldEnhancementCoupon", "equityShare", ...],
  "cusip_mapping_count": 9,
  "anthropic_key_set": true
}
```

`anthropic_key_set: true` confirms the API key was found. If it shows `false`, revisit Step 5.

---

## Step 8 — Run the Test Suite

Confirm everything is wired correctly:

```powershell
cd C:\Projects\edgar-extraction-prism-mapping\backend
.venv\Scripts\activate
python -m pytest tests\ -v
```

Expected result: **87 passed**

---

## Step 9 — First Use

Open the documentation landing page:
**[http://localhost:8000/docs/index.html](http://localhost:8000/docs/index.html)**

It links to all project documentation, the User Manual (with built-in AI chat), and the Tech Handbook.

### Quick workflow

1. **Ingest** — In the Filings view, click **Ingest** tab → enter a CUSIP → Search EDGAR → select a result → Ingest Filing
2. **Classify** — Open the filing → click **Classify** (Claude identifies the PRISM payout type, takes ~15 s)
3. **Extract** — Click **Extract** (Claude populates all PRISM fields, takes 30–120 s)
4. **Review** — Check field values, confidence scores; Accept or Reject individual fields
5. **Export** — Export to JSON or CSV for PRISM ingestion

A list of known-good CUSIPs for testing is in `CUSIP_Examples.txt` at the project root.

---

## Windows-Specific Notes

### Commands that differ from the macOS guide

| macOS / Linux | Windows equivalent |
|---|---|
| `source backend/.venv/bin/activate` | `backend\.venv\Scripts\activate` |
| `python3 main.py` | `python main.py` |
| `lsof -iTCP:8000 -sTCP:LISTEN` | `netstat -aon \| findstr :8000` |
| `kill <pid>` | `taskkill /PID <pid> /F` |
| `./start.sh` | `.\start.bat` or `.\start.ps1` |
| `chmod 600 .env` | Not needed — Windows uses ACLs, `.env` is private by default |
| `curl http://localhost:8000/api/health` | `Invoke-RestMethod http://localhost:8000/api/health` |

### Path separators

All Python backend code uses `pathlib.Path`, which handles `\` vs `/` automatically. You do **not** need to change any path strings in the source code.

### Line endings

If you edit files in VS Code, the project's `.gitattributes` and `.editorconfig` keep line endings consistent. Do not change them to Windows-style `\r\n` — the YAML and JSON config files expect Unix line endings.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `anthropic_key_set: false` | Key not stored | Run `scripts\setup_key.py` or create `.env` |
| `ModuleNotFoundError` on start | Venv not activated | Run `.venv\Scripts\activate` first |
| Frontend shows blank page | Backend not running | Start backend first (Step 6) |
| `'python' is not recognized` | Python not in PATH | Reinstall Python with "Add to PATH" checked |
| `running scripts is disabled` | PowerShell execution policy | Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| `npm: command not found` | Node not installed | Install from nodejs.org |
| Port 8000 already in use | Another process using it | `netstat -aon \| findstr :8000` → `taskkill /PID <pid> /F` |
| Docker: `WSL 2 installation is incomplete` | WSL 2 not set up | Run `wsl --install` in Admin PowerShell, restart |
| Docker: containers exit immediately | Key not in Credential Manager | Run `setup_key.py` or create `.env` before `start.bat` |
| Tests fail with `ImportError` | Dependencies not installed | Re-run `pip install -r requirements.txt` in venv |

---

## Project Contacts

For questions about the PRISM data model or schema, contact the PRISM schema team via the Azure DevOps wiki.

For questions about this tool's code or architecture, start with:
- `handover/HANDOVER_BRIEF.md` — project overview and Claude Code opening prompt
- `docs/tech_handbook.html` — full technical reference (open via browser once backend is running)
- `docs/user_manual.html` — end-user guide with built-in AI assistant
