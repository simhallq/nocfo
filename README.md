# Frey

AI finance assistant for Swedish small businesses, built on [OpenClaw](https://github.com/openclaw/openclaw).

Named after the Norse god of prosperity.

## What it does

Frey manages your Fortnox accounting through natural conversation via Telegram:

- **Receipt booking** -- Send a PDF, Frey analyzes it, proposes account entries, and books it after your confirmation
- **Bank reconciliation** -- Match bank transactions against booked entries
- **Period closing** -- Lock accounting periods with pre-flight checks
- **Financial reports** -- Download balance sheets, income statements
- **BankID authentication** -- Guided login flow with QR code

## Architecture

```
You (Telegram) <-> OpenClaw (Frey) <-> Fortnox Service <-> Fortnox
```

See [docs/architecture.md](docs/architecture.md) for details.

## Quick start

### 1. Setup

```bash
./scripts/setup.sh
```

### 2. Configure

```bash
# Add your API keys
cp docker/.env.example docker/.env
cp services/fortnox/.env.example services/fortnox/.env
cp openclaw/openclaw.json.example openclaw/openclaw.json
# Edit each file with your credentials
```

### 3. Start Fortnox service

```bash
# Start Chrome with CDP
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-cdp-profile

# Start the service
cd services/fortnox
fortnox browser start --cdp-port 9222 --port 8790
```

### 4. Start OpenClaw

```bash
cd docker
docker compose up -d
```

## Structure

```
frey/
├── workspace/          # Frey's personality, tools docs, and memory
├── skills/             # OpenClaw skills (auth, receipts, reconciliation, ...)
├── services/fortnox/   # Fortnox integration service (Python)
├── docker/             # Docker Compose for OpenClaw
├── openclaw/           # OpenClaw configuration
├── scripts/            # Setup and deployment
├── systemd/            # Production service files
└── docs/               # Architecture documentation
```
