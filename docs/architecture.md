# Architecture

## Overview

Frey is a multi-service system with three components:

```
User <-> Telegram <-> OpenClaw (Frey) <-> Fortnox Service <-> Fortnox
```

1. **OpenClaw (Frey)** -- AI agent running in Docker, handles user conversations via Telegram
2. **Fortnox Service** -- Python HTTP API for Fortnox operations (browser automation + REST API)
3. **Chrome** -- Headless browser for CDP-based Fortnox automation

## Data flow

### User requests a receipt booking

```
User sends PDF via Telegram
  -> OpenClaw receives message
  -> Frey activates receipt-booking skill
  -> Calls POST /receipts/analyze on Fortnox Service
  -> Fortnox Service uses Claude to analyze PDF
  -> Returns proposed voucher entries
  -> Frey presents preview to user via Telegram
  -> User confirms
  -> Frey calls POST /receipts/book
  -> Fortnox Service creates voucher via Fortnox REST API
  -> Fortnox Service uploads PDF via Fortnox Inbox API
  -> Returns confirmation
  -> Frey confirms to user: "Bokfort! Verifikation A-42"
```

### User authenticates

```
User says "log in" via Telegram
  -> Frey calls POST /auth/start on Fortnox Service
  -> Fortnox Service creates operation, returns live_url
  -> Frey sends live_url to user
  -> User opens link, BankID QR code appears
  -> User scans QR with BankID app on phone
  -> Fortnox Service captures authenticated session cookies
  -> Frey polls /operation/{id} until complete
  -> Confirms: "Du ar nu inloggad!"
```

## Service communication

```
+-------------------+       +-------------------+       +----------+
|    OpenClaw       |  HTTP |   Fortnox         |  CDP  |  Chrome  |
|    (Docker)       |------>|   Service          |------>|  (host)  |
|                   |       |   (host, :8790)   |       |  (:9222) |
|  workspace/       |       |                   |  REST |          |
|  skills/          |       |   src/fortnox/    |------>| Fortnox  |
+-------------------+       +-------------------+       |  API     |
        |                                               +----------+
        | Telegram API
        v
  +----------+
  |  User    |
  | (phone)  |
  +----------+
```

- OpenClaw runs in Docker, accesses Fortnox Service via `host.docker.internal:8790`
- Fortnox Service runs on the host with direct Chrome CDP access
- Chrome runs on the host for CDP-based browser automation
- Fortnox REST API is accessed directly by the Fortnox Service (OAuth2)

## Security

- Fortnox Service requires Bearer token authentication
- OpenClaw Gateway requires its own authentication token
- No services are exposed to the public internet
- BankID authentication requires physical user interaction (cannot be automated)
- Session cookies are stored per-customer in `data/sessions/`

## Directory structure

```
frey/
├── workspace/       # Frey's personality and memory (mounted into Docker)
├── skills/          # OpenClaw skills connecting to Fortnox Service
├── services/
│   └── fortnox/     # Python Fortnox integration service
├── docker/          # Docker Compose for OpenClaw
├── openclaw/        # OpenClaw configuration
├── scripts/         # Setup and deployment
├── systemd/         # Production service files
└── docs/            # This documentation
```
