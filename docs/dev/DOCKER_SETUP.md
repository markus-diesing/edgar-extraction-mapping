# Docker Setup — EDGAR Extraction & PRISM Mapping

**Added:** 2026-03-24
**Status:** Active — this is the primary way to run the stack locally

---

## Overview

The application runs as two Docker containers orchestrated by Docker Compose:

| Container | What it runs | Port |
|---|---|---|
| `backend` | FastAPI + uvicorn (Python 3.13) | `http://localhost:8000` |
| `frontend` | Vite dev server (Node 20, React 18) | `http://localhost:5173` |

Both containers use **bind mounts** — all source files, data, and config live on your Mac and are read directly by the containers. You edit files normally; there is nothing to copy in or out.

The Anthropic API key is read automatically from **macOS Keychain** via `start.sh`. It is never written to disk or baked into an image.

---

## Prerequisites

- **Docker Desktop** installed and running (whale icon in menu bar = ready)
  Download: https://www.docker.com/products/docker-desktop

That's it. Python and Node do **not** need to be installed to run the container version.
(They are still present in `backend/.venv` and are used by `start.sh` to read the Keychain — see [API Key](#api-key) below.)

---

## Daily Usage

### Start the stack

```bash
cd EDGAR-Extraction_Mapping
./start.sh
```

First run takes **3–5 minutes** (downloads base images, installs packages into the image layers).
Every subsequent start takes **~5 seconds**.

### Start in background (detached)

```bash
./start.sh -d
```

The terminal is returned immediately. Use `docker compose logs -f` to follow output.

### Rebuild images (after changing requirements.txt or package.json)

```bash
./start.sh --build
```

Or detached: `./start.sh -d --build`

> Rebuilding is **not** needed when you edit `.py`, `.jsx`, or any source file — those are mounted live and hot-reload automatically.

### Stop the stack

If running in the foreground: **Ctrl+C**, then:

```bash
docker compose down
```

If running detached:

```bash
docker compose down
```

`docker compose down` stops and removes the containers. Data is safe — it lives in the mounted folders, not in the containers.

---

## URLs

| URL | What you get |
|---|---|
| `http://localhost:5173` | React UI (main application) |
| `http://localhost:8000` | FastAPI backend (direct API access) |
| `http://localhost:8000/docs/index.html` | Documentation landing page |
| `http://localhost:8000/docs/user_manual.html` | User manual with embedded chat |
| `http://localhost:8000/api/health` | Health check (JSON) |

---

## File Access

All files remain in their normal locations on your Mac and behave exactly as before. The containers read and write through bind mounts.

| Mac folder | Container path | Contents |
|---|---|---|
| `backend/` | `/app/backend` | Python source — edits hot-reload immediately |
| `frontend/src/` | `/app/src` | React source — edits hot-reload in browser |
| `data/` | `/app/data` | SQLite database, cached EDGAR filings, exports |
| `files/` | `/app/files` | Hints YAML, label maps, runtime settings |
| `docs/` | `/app/docs` | Documentation served at `/docs/*` |
| `schemas/` | `/app/schemas` | PRISM schema JSON, CUSIP mapping |
| `logs/` | `/app/logs` | `app.log` — writable from Finder/any editor |

**The SQLite database** (`data/db/edgar_extraction.db`) is fully accessible via DB Browser for SQLite or any SQLite tool — open it directly from Finder as usual.

---

## API Key

### On this Mac (Keychain — automatic)

`start.sh` reads the Anthropic key from macOS Keychain using the local Python venv:

```
Service:  edgar-extraction
Account:  anthropic_api_key
```

No manual steps required — key is injected into the container as an environment variable at startup and is never written to a file.

To verify the key is stored correctly:

```bash
backend/.venv/bin/python -c "
import keyring
k = keyring.get_password('edgar-extraction', 'anthropic_api_key')
print('Found:', len(k), 'chars') if k else print('NOT FOUND')
"
```

To store or update the key in Keychain:

```bash
backend/.venv/bin/python -c "
import keyring
keyring.set_password('edgar-extraction', 'anthropic_api_key', 'sk-ant-YOUR-KEY-HERE')
print('Stored.')
"
```

### On another Mac (new user, new key)

The receiving Mac uses a `.env` file instead of Keychain:

1. Get a new Anthropic API key from https://console.anthropic.com
   **Do not use the key from this machine.**

2. Create `.env` in the project root:
   ```
   ANTHROPIC_API_KEY=sk-ant-YOUR-OWN-KEY
   ```

3. Run `docker compose up` directly (skip `start.sh` which requires the venv):
   ```bash
   docker compose up --build
   ```

`docker-compose.yml` passes `${ANTHROPIC_API_KEY}` from the shell environment into the container. `docker compose` automatically reads `.env` from the project root if it exists.

---

## Logs

### Live log stream (all containers)

```bash
docker compose logs -f
```

### Backend only

```bash
docker compose logs -f backend
```

### Log file on disk

`logs/app.log` — updated in real time, accessible in Finder, tailable from terminal:

```bash
tail -f logs/app.log
```

---

## Useful Commands

```bash
# See running containers and their ports
docker ps

# Open a shell inside the running backend container
docker compose exec backend bash

# Open a shell inside the running frontend container
docker compose exec frontend sh

# Restart just the backend (e.g. after a config change)
docker compose restart backend

# Check resource usage
docker stats

# Remove all stopped containers and dangling images (frees disk)
docker system prune
```

---

## Hot Reload

Both services reload automatically when source files change — no restart needed.

| What you change | What happens |
|---|---|
| Any `.py` file in `backend/` | uvicorn detects the change and reloads within ~1 second |
| Any `.jsx`, `.js`, `.css` in `frontend/src/` | Vite pushes an HMR update to the browser instantly |
| `files/runtime_settings.yaml` | Picked up on next request (backend reads it live) |
| `files/*.yaml` hint files | Picked up on next request |
| `backend/requirements.txt` | Requires `./start.sh --build` to reinstall packages |
| `frontend/package.json` | Requires `./start.sh --build` to reinstall packages |

---

## Project Files Created by Docker Setup

| File | Purpose |
|---|---|
| `Dockerfile` | Backend image (Python 3.13-slim + lxml deps) |
| `Dockerfile.frontend` | Frontend image (Node 20-slim, Vite dev server) |
| `docker-compose.yml` | Service definitions, ports, volumes, env |
| `start.sh` | Launcher that reads Keychain → exports key → runs compose |
| `.dockerignore` | Excludes `.venv`, `node_modules`, `data/`, secrets from image build |
| `.env.example` | Template for new-Mac setup (copy to `.env`, fill in key) |

---

## Restore to Pre-Docker State

The pre-Docker state is tagged in git:

```bash
git checkout v0.1-pre-docker
```

To return to the Docker version:

```bash
git checkout main
```

---

## Troubleshooting

**`./start.sh` says "Docker not found"**
Docker Desktop is installed but not running. Open it from Applications and wait for the menu bar whale to turn steady before retrying.

**`start.sh` says "ANTHROPIC_API_KEY not found in Keychain"**
The key needs to be stored. See [API Key → On this Mac](#on-this-mac-keychain--automatic) above.

**Port already in use (8000 or 5173)**
The non-Docker backend/frontend is still running. Stop them:
```bash
lsof -ti :8000 | xargs kill -9 2>/dev/null
lsof -ti :5173 | xargs kill -9 2>/dev/null
```
Then run `./start.sh` again.

**Backend container exits immediately**
Check logs for the cause:
```bash
docker compose logs backend
```
Common causes: missing `logs/` directory (fixed: already exists), Python import error, missing volume mount path.

**Frontend can't reach the backend**
Inside Docker, the backend is reachable at `http://backend:8000` (service name), not `localhost:8000`. The `VITE_BACKEND_URL` environment variable in `docker-compose.yml` handles this — check it hasn't been accidentally removed.

**Changes to `.py` files not hot-reloading**
Confirm the `./backend:/app/backend` volume mount is present in `docker-compose.yml`. If you ran `docker compose up` directly (without `start.sh --build`), the image may have stale code baked in — run `./start.sh --build` once.
