#Requires -Version 5.1
<#
.SYNOPSIS
    Launches the EDGAR Extraction & PRISM Mapping Docker stack.

.DESCRIPTION
    Reads the Anthropic API key from Windows Credential Manager (preferred) or
    falls back to backend\.env.  The key is injected as an environment variable —
    never written to docker-compose.yml or any log.

    Docker Desktop must be running before calling this script.

.PARAMETER DockerArgs
    Optional arguments forwarded to `docker compose up`.
    Examples:
        .\start.ps1                   # foreground
        .\start.ps1 -d                # detached
        .\start.ps1 --build           # rebuild images
        .\start.ps1 -d --build        # detached + rebuild

.EXAMPLE
    .\start.ps1
    .\start.ps1 -d --build
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$DockerArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root "backend\.venv\Scripts\python.exe"

# ── Sanity checks ──────────────────────────────────────────────────────────────
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found.`nInstall Docker Desktop from https://www.docker.com/products/docker-desktop and ensure it is running."
    exit 1
}

if (-not (Test-Path $Venv)) {
    Write-Error "Python venv not found at backend\.venv`nRun the setup steps from SETUP_WINDOWS11.md first:`n  cd backend`n  python -m venv .venv`n  .venv\Scripts\activate`n  pip install -r requirements.txt"
    exit 1
}

# ── Read API key from Windows Credential Manager ───────────────────────────────
Write-Host "Reading Anthropic API key from Windows Credential Manager..." -ForegroundColor Cyan

$Key = & $Venv -c @"
import keyring, sys
k = keyring.get_password('edgar-extraction', 'anthropic_api_key')
print(k if k else '', end='')
"@ 2>$null

# ── Fall back to .env file ─────────────────────────────────────────────────────
if ([string]::IsNullOrEmpty($Key)) {
    Write-Host "  Not found in Credential Manager. Checking backend\.env ..." -ForegroundColor Yellow
    $EnvFile = Join-Path $Root "backend\.env"
    if (Test-Path $EnvFile) {
        $Line = Select-String -Path $EnvFile -Pattern "^ANTHROPIC_API_KEY\s*=" | Select-Object -First 1
        if ($Line) {
            $Key = ($Line.Line -split "=", 2)[1].Trim()
        }
    }
}

if ([string]::IsNullOrEmpty($Key)) {
    Write-Host ""
    Write-Error @"
ANTHROPIC_API_KEY not found.

Option A - Windows Credential Manager (recommended):
  cd backend
  .venv\Scripts\activate
  python scripts\setup_key.py

Option B - .env file:
  Create backend\.env containing:
  ANTHROPIC_API_KEY=sk-ant-api03-YOUR-KEY-HERE
"@
    exit 1
}

Write-Host "  Key found ($($Key.Length) chars). Starting containers..." -ForegroundColor Green
Write-Host ""

# ── Launch ─────────────────────────────────────────────────────────────────────
$env:ANTHROPIC_API_KEY = $Key

if ($DockerArgs) {
    & docker compose up @DockerArgs
} else {
    & docker compose up
}
