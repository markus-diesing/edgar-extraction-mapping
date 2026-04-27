@echo off
:: ── start.bat ─────────────────────────────────────────────────────────────────
:: Launches the Docker stack for the EDGAR Extraction & PRISM Mapping POC.
:: Reads the Anthropic API key from Windows Credential Manager (preferred)
:: or falls back to backend\.env.  The key is injected as an environment
:: variable — never written to docker-compose.yml or any log.
::
:: Usage:
::   start.bat              start in foreground (Ctrl+C to stop)
::   start.bat -d           start detached (background)
::   start.bat --build      rebuild images before starting
::   start.bat -d --build   both
::
:: Prerequisites:
::   - Docker Desktop must be running (whale icon in system tray)
::   - backend\.venv must exist  (run Steps 2-3 from SETUP_WINDOWS11.md first)
::   - API key stored via:  backend\.venv\Scripts\python scripts\setup_key.py
:: ──────────────────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "VENV=%ROOT%backend\.venv\Scripts\python.exe"

:: ── Sanity checks ─────────────────────────────────────────────────────────────
where docker >nul 2>&1
if errorlevel 1 (
    echo ERROR: Docker not found.
    echo   Install Docker Desktop from https://www.docker.com/products/docker-desktop
    echo   and make sure it is running before starting this script.
    pause
    exit /b 1
)

if not exist "%VENV%" (
    echo ERROR: Python venv not found at backend\.venv
    echo   Run the setup steps from SETUP_WINDOWS11.md first:
    echo     cd backend
    echo     python -m venv .venv
    echo     .venv\Scripts\activate
    echo     pip install -r requirements.txt
    pause
    exit /b 1
)

:: ── Read API key from Windows Credential Manager ──────────────────────────────
echo Reading Anthropic API key from Windows Credential Manager...
for /f "delims=" %%K in ('
    "%VENV%" -c "import keyring, sys; k=keyring.get_password(\"edgar-extraction\",\"anthropic_api_key\"); print(k if k else \"\", end=\"\")" 2^>nul
') do set "KEY=%%K"

:: ── Fall back to .env file if Credential Manager returned nothing ──────────────
if "!KEY!"=="" (
    echo   Not found in Credential Manager. Checking backend\.env ...
    if exist "%ROOT%backend\.env" (
        for /f "tokens=2 delims==" %%V in ('findstr /i "ANTHROPIC_API_KEY" "%ROOT%backend\.env"') do (
            set "KEY=%%V"
        )
    )
)

if "!KEY!"=="" (
    echo.
    echo ERROR: ANTHROPIC_API_KEY not found.
    echo   Option A - Windows Credential Manager ^(recommended^):
    echo     cd backend
    echo     .venv\Scripts\activate
    echo     python scripts\setup_key.py
    echo.
    echo   Option B - .env file:
    echo     Create backend\.env with the line:
    echo     ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE
    echo.
    pause
    exit /b 1
)

echo   Key found. Starting containers...
echo.

:: Export so docker compose picks it up via ${ANTHROPIC_API_KEY} in compose file
set "ANTHROPIC_API_KEY=!KEY!"

:: ── Launch ────────────────────────────────────────────────────────────────────
docker compose up %*
