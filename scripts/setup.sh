#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Cross-platform sed -i (macOS vs GNU)
replace_in_file() {
    local pattern="$1" file="$2"
    sed -i '' "$pattern" "$file" 2>/dev/null || sed -i "$pattern" "$file"
}

echo "=== Frey Setup ==="
echo ""

# ── Step 1: Generate tokens ─────────────────────────────────────────
GATEWAY_TOKEN=""
BROWSER_TOKEN=""

if [ ! -f "$REPO_ROOT/docker/.env" ]; then
    echo "Generating security tokens..."
    GATEWAY_TOKEN=$(openssl rand -hex 32)
    BROWSER_TOKEN=$(openssl rand -hex 32)
    echo "  Gateway token: generated"
    echo "  Browser API token: generated"
    echo ""
fi

# ── Step 2: Collect API keys ────────────────────────────────────────
echo "You'll need the following credentials:"
echo "  - Anthropic API key (from console.anthropic.com)"
echo "  - Telegram bot token (from @BotFather)"
echo "  - Fortnox OAuth credentials (from apps.fortnox.se, optional for now)"
echo ""

ANTHROPIC_KEY=""
TELEGRAM_TOKEN=""

if [ -t 0 ]; then
    read -p "Anthropic API key (sk-ant-...): " ANTHROPIC_KEY
    read -p "Telegram bot token (from @BotFather, or press Enter to skip): " TELEGRAM_TOKEN
fi

# ── Step 3: Create config files ─────────────────────────────────────
echo ""
echo "Creating configuration files..."

# Docker .env
if [ ! -f "$REPO_ROOT/docker/.env" ]; then
    cp "$REPO_ROOT/docker/.env.example" "$REPO_ROOT/docker/.env"
    [ -n "$ANTHROPIC_KEY" ] && replace_in_file "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_KEY}|" "$REPO_ROOT/docker/.env"
    [ -n "$GATEWAY_TOKEN" ] && replace_in_file "s|^OPENCLAW_GATEWAY_TOKEN=.*|OPENCLAW_GATEWAY_TOKEN=${GATEWAY_TOKEN}|" "$REPO_ROOT/docker/.env"
    [ -n "$TELEGRAM_TOKEN" ] && replace_in_file "s|^TELEGRAM_BOT_TOKEN=.*|TELEGRAM_BOT_TOKEN=${TELEGRAM_TOKEN}|" "$REPO_ROOT/docker/.env"
    echo "  Created docker/.env"
else
    echo "  docker/.env already exists, skipping"
fi

# OpenClaw config
if [ ! -f "$REPO_ROOT/openclaw/openclaw.json" ]; then
    cp "$REPO_ROOT/openclaw/openclaw.json.example" "$REPO_ROOT/openclaw/openclaw.json"
    [ -n "$GATEWAY_TOKEN" ] && replace_in_file "s|<OPENCLAW_GATEWAY_TOKEN>|${GATEWAY_TOKEN}|" "$REPO_ROOT/openclaw/openclaw.json"
    [ -n "$TELEGRAM_TOKEN" ] && replace_in_file "s|<TELEGRAM_BOT_TOKEN>|${TELEGRAM_TOKEN}|" "$REPO_ROOT/openclaw/openclaw.json"
    echo "  Created openclaw/openclaw.json"
else
    echo "  openclaw/openclaw.json already exists, skipping"
fi

# Fortnox service .env
if [ ! -f "$REPO_ROOT/services/fortnox/.env" ]; then
    cp "$REPO_ROOT/services/fortnox/.env.example" "$REPO_ROOT/services/fortnox/.env"
    [ -n "$ANTHROPIC_KEY" ] && replace_in_file "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${ANTHROPIC_KEY}|" "$REPO_ROOT/services/fortnox/.env"
    [ -n "$BROWSER_TOKEN" ] && replace_in_file "s|^BROWSER_API_TOKEN=.*|BROWSER_API_TOKEN=${BROWSER_TOKEN}|" "$REPO_ROOT/services/fortnox/.env"
    echo "  Created services/fortnox/.env"
else
    echo "  services/fortnox/.env already exists, skipping"
fi

# Docker data directory for persistent OpenClaw state
mkdir -p "$REPO_ROOT/docker/data/openclaw"

# ── Step 4: Install fortnox service ─────────────────────────────────
echo ""
echo "Installing fortnox service..."
cd "$REPO_ROOT/services/fortnox"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
.venv/bin/pip install -q -e ".[dev]"
echo "  Installed fortnox-service"

# ── Step 5: Build Fortnox tool plugin ────────────────────────────────
echo ""
echo "Building Fortnox tool plugin..."
cd "$REPO_ROOT/tools/fortnox"
npm install --silent 2>/dev/null
npx tsc 2>/dev/null && echo "  Built fortnox plugin" || echo "  WARNING: Plugin build failed. Check tools/fortnox/ for errors."

# ── Step 6: Pull OpenClaw Docker image ──────────────────────────────
echo ""
echo "Pulling OpenClaw Docker image..."
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}"
docker pull "$OPENCLAW_IMAGE" 2>/dev/null || echo "  WARNING: Could not pull image. You may need to build locally or check your Docker setup."

# ── Step 7: Check Chrome ────────────────────────────────────────────
echo ""
if command -v google-chrome &>/dev/null || command -v chromium &>/dev/null; then
    echo "Chrome/Chromium: found"
elif [ -d "/Applications/Google Chrome.app" ]; then
    echo "Chrome: found (macOS)"
else
    echo "WARNING: Chrome not found. Install Chrome for browser automation."
fi

# ── Done ─────────────────────────────────────────────────────────────
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo ""
echo "  1. If you haven't already, create a Telegram bot:"
echo "     - Message @BotFather on Telegram"
echo "     - Send /newbot, name it 'Frey'"
echo "     - Add the token to docker/.env and openclaw/openclaw.json"
echo ""
echo "  2. Start Chrome with CDP:"
echo "     google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile --headless"
echo ""
echo "  3. Start the Fortnox service:"
echo "     cd services/fortnox && .venv/bin/fortnox browser start --cdp-port 9222 --port 8790"
echo ""
echo "  4. Start OpenClaw:"
echo "     cd docker && docker compose up -d"
echo ""
echo "  5. Pair your Telegram account:"
echo "     - Send any message to your bot in Telegram"
echo "     - Run: cd docker && docker compose exec openclaw-gateway node dist/index.js pairing list telegram"
echo "     - Run: cd docker && docker compose exec openclaw-gateway node dist/index.js pairing approve telegram <CODE>"
echo ""
echo "  6. Verify:"
echo "     curl http://localhost:8790/health"
echo "     curl http://127.0.0.1:18789/healthz"
echo ""
