#!/usr/bin/env bash
# ── start-prod.sh ──────────────────────────────────────────────────────────────
# First-time setup and start for the production server.
#
# Usage:
#   ./start-prod.sh           # start (prompts for API key if not set)
#   ./start-prod.sh --build   # rebuild images before starting
#   ./start-prod.sh -d        # start detached

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── Detect docker compose command ─────────────────────────────────────────────
if docker compose version &>/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC="docker-compose"
else
    echo "ERROR: neither 'docker compose' nor 'docker-compose' found."
    exit 1
fi

# ── TLS certificate ────────────────────────────────────────────────────────────
echo "Checking TLS certificate..."
bash "$ROOT/nginx/generate-cert.sh"

# ── Anthropic API key ──────────────────────────────────────────────────────────
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    if [ -f "$ROOT/.env" ] && grep -q "ANTHROPIC_API_KEY" "$ROOT/.env"; then
        export $(grep "ANTHROPIC_API_KEY" "$ROOT/.env" | xargs)
    else
        echo ""
        read -rsp "Enter your Anthropic API key (sk-ant-...): " ANTHROPIC_API_KEY
        echo ""
        export ANTHROPIC_API_KEY
        echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY" >> "$ROOT/.env"
        echo "Key saved to .env"
    fi
fi

# ── Start containers ───────────────────────────────────────────────────────────
echo ""
echo "Starting EDGAR (production)..."
$DC -f "$ROOT/docker-compose.prod.yml" up --build -d "$@"

# ── Pull Qwen3-14b into Ollama ─────────────────────────────────────────────────
echo ""
echo "Waiting for Ollama to be ready..."
until $DC -f "$ROOT/docker-compose.prod.yml" exec -T ollama ollama list &>/dev/null; do
    sleep 3
done

echo "Pulling Qwen3-14b (~9 GB — this takes a few minutes on first run)..."
$DC -f "$ROOT/docker-compose.prod.yml" exec -T ollama ollama pull qwen3:14b

echo ""
echo "EDGAR is running at https://$(hostname -I | awk '{print $1}')"
echo ""
echo "Next steps:"
echo "  1. Add https://$(hostname -I | awk '{print $1}') as a redirect URI in the Entra App Registration"
echo "  2. In the Admin UI → Underlying LLM Settings, switch provider to 'ollama'"
