#!/usr/bin/env bash
# ── start.sh ──────────────────────────────────────────────────────────────────
# Launches the Docker stack, reading the Anthropic API key from macOS Keychain.
# The key is injected as an environment variable — never written to disk.
#
# Usage:
#   ./start.sh               # start in foreground (Ctrl+C to stop)
#   ./start.sh -d            # start detached (background)
#   ./start.sh --build       # rebuild images before starting
#   ./start.sh -d --build    # both

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/backend/.venv/bin/python"

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop"
    exit 1
fi

if [ ! -f "$VENV" ]; then
    echo "ERROR: Python venv not found at backend/.venv"
    echo "  Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

# ── Read API key from macOS Keychain via the existing venv ────────────────────
echo "Reading Anthropic API key from Keychain..."
KEY=$("$VENV" -c "
import keyring, sys
k = keyring.get_password('edgar-extraction', 'anthropic_api_key')
print(k if k else '', end='')
" 2>/dev/null)

if [ -z "$KEY" ]; then
    echo ""
    echo "ERROR: ANTHROPIC_API_KEY not found in Keychain."
    echo "  Service:  edgar-extraction"
    echo "  Account:  anthropic_api_key"
    echo ""
    echo "To store the key, run:  python backend/scripts/setup_key.py"
    exit 1
fi

echo "  Key found (${#KEY} chars). Starting containers..."
echo ""

# Export so docker compose picks it up via \${ANTHROPIC_API_KEY} in compose file
export ANTHROPIC_API_KEY="$KEY"

# exec replaces this shell — Ctrl+C goes directly to docker compose
exec docker compose up "$@"
