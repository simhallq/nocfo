# Frey Setup Guide

## Prerequisites

- **Docker** with Compose v2 (`docker compose`)
- **Python 3.11+**
- **Google Chrome** (for browser automation)
- **Anthropic API key** from [console.anthropic.com](https://console.anthropic.com)
- **Telegram** account (for the chat interface)

Optional:
- **Fortnox developer account** from [apps.fortnox.se](https://apps.fortnox.se/integration-developer/signup) (needed for receipt booking and API operations)

---

## Quick Setup

Run the interactive setup script:

```bash
./scripts/setup.sh
```

This generates tokens, creates config files, installs dependencies, and pulls the Docker image. Follow the prompts.

---

## Manual Setup

### 1. Create a Telegram bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot`
3. Name: `Frey`
4. Username: something unique, e.g., `frey_finance_bot`
5. Save the token (format: `123456789:ABCdef...`)

### 2. Generate security tokens

```bash
# Gateway token (authenticates OpenClaw API access)
openssl rand -hex 32

# Browser API token (authenticates Fortnox service API)
openssl rand -hex 32
```

### 3. Create configuration files

**docker/.env** (from `docker/.env.example`):
```bash
cp docker/.env.example docker/.env
```

Fill in:
- `ANTHROPIC_API_KEY` -- your Anthropic key
- `OPENCLAW_GATEWAY_TOKEN` -- the gateway token you generated
- `TELEGRAM_BOT_TOKEN` -- from BotFather

**openclaw/openclaw.json** (from `openclaw/openclaw.json.example`):
```bash
cp openclaw/openclaw.json.example openclaw/openclaw.json
```

Replace:
- `<TELEGRAM_BOT_TOKEN>` with your Telegram token
- `<OPENCLAW_GATEWAY_TOKEN>` with your gateway token

**services/fortnox/.env** (from `services/fortnox/.env.example`):
```bash
cp services/fortnox/.env.example services/fortnox/.env
```

Fill in:
- `ANTHROPIC_API_KEY` -- same key as above
- `BROWSER_API_TOKEN` -- the browser API token you generated
- `FORTNOX_CLIENT_ID` and `FORTNOX_CLIENT_SECRET` -- from Fortnox developer portal (can add later)

### 4. Install the Fortnox service

```bash
cd services/fortnox
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 5. Pull the OpenClaw Docker image

```bash
docker pull ghcr.io/openclaw/openclaw:latest
```

---

## Starting Services

Start in this order:

### 1. Chrome (for browser automation)

```bash
# macOS
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-cdp-profile \
  --headless

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile --headless
```

### 2. Fortnox service

```bash
cd services/fortnox
.venv/bin/fortnox browser start --cdp-port 9222 --port 8790
```

Verify: `curl http://localhost:8790/health` should return `{"status": "ok", ...}`

### 3. OpenClaw (Frey)

```bash
cd docker
docker compose up -d
```

Check logs: `docker compose logs -f openclaw-gateway`

---

## Telegram Pairing

OpenClaw uses a pairing flow for security -- you need to approve your Telegram account.

1. **Send any message** to your Frey bot in Telegram (e.g., "hello")
2. **List pending pairings**:
   ```bash
   cd docker
   docker compose exec openclaw-gateway node dist/index.js pairing list telegram
   ```
3. **Approve your pairing**:
   ```bash
   docker compose exec openclaw-gateway node dist/index.js pairing approve telegram <CODE>
   ```
   Replace `<CODE>` with the pairing code shown in the list.

4. **Test**: Send "What can you help me with?" -- Frey should respond as a finance assistant.

---

## Verification Checklist

```bash
# Fortnox service is running
curl http://localhost:8790/health

# OpenClaw gateway is running
curl http://127.0.0.1:18789/healthz

# Gateway can reach Fortnox service (from inside container)
docker compose -f docker/docker-compose.yml exec openclaw-gateway \
  curl -s http://host.docker.internal:8790/health

# OpenClaw channel status
docker compose -f docker/docker-compose.yml exec openclaw-gateway \
  node dist/index.js channels status --probe
```

---

## Troubleshooting

### "Connection refused" on port 8790
The Fortnox service isn't running. Start it:
```bash
cd services/fortnox && .venv/bin/fortnox browser start --cdp-port 9222 --port 8790
```

### "Chrome CDP unreachable"
Chrome isn't running with CDP enabled. Start it:
```bash
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile --headless
```

### Gateway won't start
Check logs: `cd docker && docker compose logs openclaw-gateway`

Common issues:
- Invalid `openclaw.json` (check syntax)
- Missing API key in `docker/.env`
- Port 18789 already in use

### Telegram bot not responding
1. Check gateway logs for Telegram errors
2. Verify `TELEGRAM_BOT_TOKEN` matches in both `docker/.env` and `openclaw/openclaw.json`
3. Make sure pairing is approved

### "host.docker.internal" not resolving
On Linux, ensure `extra_hosts: ["host.docker.internal:host-gateway"]` is in docker-compose.yml (it is by default). On macOS, this works out of the box.

---

## Updating

### Pull latest OpenClaw
```bash
cd docker
docker compose pull
docker compose up -d
```

### Update Fortnox service
```bash
cd services/fortnox
git pull
.venv/bin/pip install -e ".[dev]"
# Restart the service
```

### Update workspace/skills
Edit files in `workspace/` or `skills/`, then restart OpenClaw:
```bash
cd docker && docker compose restart openclaw-gateway
```
