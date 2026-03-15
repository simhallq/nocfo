# NoCFO

Automated Swedish bookkeeping for Fortnox — voucher creation, bank reconciliation, period closing, and financial reports without a CFO.

## What it does

NoCFO automates routine bookkeeping tasks in [Fortnox](https://www.fortnox.se):

- **Voucher creation** from templates (salary, VAT, employer tax, etc.) with idempotency protection
- **Rule-based categorization** of bank transactions via regex patterns (`rules.yaml`)
- **Bank reconciliation** through browser automation
- **Period closing** with pre-flight checks (balances, unreconciled items) and lock execution
- **Financial reports** — download balance sheets and income statements as PDF
- **Scheduling** — run bookkeeping jobs on a recurring basis
- **Workflow recorder** — record browser interactions, enhance with Claude vision, and replay with selector fallback + vision-based recovery

## Architecture

NoCFO operates in two modes:

1. **Fortnox REST API** — OAuth2-authenticated API calls for vouchers, accounts, invoices, and pre-flight checks
2. **Browser automation** — Playwright connects to Chrome via CDP (Chrome DevTools Protocol) to drive Fortnox UI operations that aren't available through the API (reconciliation, period locking, report downloads)

The browser automation runs as a local HTTP server that accepts commands and executes them against a logged-in Fortnox session.

```
CLI (click)
 ├── Fortnox REST API (httpx + OAuth2)
 │    ├── Vouchers, accounts, invoices
 │    ├── Closing pre-flight checks
 │    └── Health checks
 ├── Browser API server (Playwright + CDP)
 │    ├── BankID login
 │    ├── Reconciliation
 │    ├── Period locking
 │    └── Report downloads
 └── Workflow recorder (Playwright + CDP)
      ├── Record interactions → YAML
      ├── Claude vision enhancement
      └── Replay with vision fallback
```

### Web agent

The `web_agent/` module provides a Claude AI-powered browser automation agent. Given a Playwright page and a system prompt, the agent autonomously navigates Fortnox's web UI — clicking, typing, and reading page state — to complete tasks like period closing and report downloads. Pre-built task definitions live in `web_agent/tasks/`.

## Prerequisites

- Python 3.11+
- Google Chrome
- A [Fortnox developer account](https://apps.fortnox.se/integration-developer/signup) with a Private Integration

## Installation

```bash
git clone <repo-url> && cd nocfo
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
```

## Fortnox setup

### 1. Create a developer account

Go to [apps.fortnox.se/integration-developer/signup](https://apps.fortnox.se/integration-developer/signup) and register a developer account. You need an existing Fortnox account for the company you want to automate.

### 2. Create a Private Integration

In the Fortnox developer portal:

1. Click **Create Integration** and choose **Private Integration**
2. Set **Redirect URI** to `http://localhost:8888/callback`
3. Enable the following **scopes**:
   - `bookkeeping` — vouchers, accounts, financial years
   - `supplierinvoice` — supplier invoice management
   - `invoice` — customer invoices
   - `payment` — payment handling
   - `settings` — company settings, period locking
   - `companyinformation` — company details
   - `customer` — customer records
   - `supplier` — supplier records
   - `inbox` — file inbox
   - `connectfile` — file attachments
4. Save the integration and copy the **Client ID** and **Client Secret**

### 3. Configure environment

```bash
cp .env.example .env
```

Add your Fortnox credentials to `.env`:

```
FORTNOX_CLIENT_ID=your-client-id
FORTNOX_CLIENT_SECRET=your-client-secret
```

### 4. Authorize

Run the interactive OAuth flow. This opens your browser, asks you to log in to Fortnox and approve the integration, then captures the authorization code via a local callback server on port 8888:

```bash
nocfo auth setup
```

Tokens are stored locally and auto-refresh when they expire (Fortnox uses rotating refresh tokens).

### 5. Verify

```bash
# Quick check
nocfo auth status

# Full health check — tests API connectivity, scopes, financial year, etc.
nocfo auth status --health
```

## Configuration reference

| Variable | Description | Default |
|---|---|---|
| `FORTNOX_CLIENT_ID` | Fortnox OAuth2 client ID | — |
| `FORTNOX_CLIENT_SECRET` | Fortnox OAuth2 client secret | — |
| `ANTHROPIC_API_KEY` | Anthropic API key (vision fallback) | — |
| `DATABASE_PATH` | SQLite database path | `data/nocfo.db` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `BROWSER_API_URL` | Browser API server URL | `http://localhost:8790` |
| `BROWSER_API_TOKEN` | Bearer token for browser API auth | — |
| `BROWSER_CDP_PORT` | Chrome DevTools Protocol port | `9222` |
| `BROWSER_PROFILE_DIR` | Chrome user data directory | `data/browser_profile` |
| `VISION_FALLBACK_ENABLED` | Enable Claude vision for selector discovery | `true` |
| `SCREENSHOTS_DIR` | Directory for evidence screenshots | `data/screenshots` |
| `LEARNED_SELECTORS_PATH` | Path to learned selectors store | `data/learned_selectors.json` |
| `WORKFLOWS_DIR` | Workflow YAML output directory | `data/workflows` |
| `FUNNEL_BASE` | Tailscale Funnel base URL for BankID QR | — |
| `SESSIONS_DIR` | Per-customer session cookies directory | `data/sessions` |
| `FORTNOX_BASE_URL` | Fortnox API base URL | `https://api.fortnox.se/3` |
| `FORTNOX_AUTH_URL` | Fortnox OAuth URL | `https://apps.fortnox.se/oauth-v1` |
| `OAUTH_REDIRECT_URI` | OAuth redirect URI | `http://localhost:8888/callback` |
| `OAUTH_REDIRECT_PORT` | OAuth redirect server port | `8888` |

## Usage

### Authentication

```bash
# Run interactive OAuth flow (opens browser)
nocfo auth setup

# Check auth status
nocfo auth status

# Full health check against Fortnox API
nocfo auth status --health
```

### Browser automation

Browser-based operations (reconciliation, period closing, reports) require Chrome and the browser API server:

```bash
# Launch Chrome + API server (blocking)
nocfo browser start

# Or run headless
nocfo browser start --headless

# Check server and session status
nocfo browser status

# Log in to Fortnox via BankID
nocfo browser login
```

### Vouchers

```bash
# List vouchers in series A
nocfo voucher list --series A

# Create a voucher from a template
nocfo voucher create \
  --template salary \
  --amount 35000 \
  --date 2025-01-25 \
  --description "January salary"
```

### Reconciliation

```bash
# Run bank reconciliation (requires browser API)
nocfo reconcile run

# Check reconciliation status
nocfo reconcile status
```

### Period closing

```bash
# Pre-flight check
nocfo close check 2025-01

# Execute period closing
nocfo close run 2025-01
```

### Reports

```bash
# Download balance sheet
nocfo report balance --period 2025-01

# Download income statement
nocfo report income --period 2025-01
```

### Scheduler

```bash
# Start job scheduler
nocfo schedule start

# List scheduled jobs
nocfo schedule status
```

### Approve

```bash
# Approve a pending destructive operation
nocfo approve <job-id>
```

### SvD invoice download

```bash
# Download the latest SvD invoice (replays a recorded workflow)
nocfo svd-invoice
```

### Workflow recorder

Record browser interactions as replayable YAML workflows. Connects to Chrome via CDP.

**Setup:** Chrome blocks CDP on the default profile, so we copy the profile to a separate directory (preserving all cookies and logins):

```bash
# macOS — quit Chrome first
killall "Google Chrome"

# One-time: copy your Chrome profile (keeps all logins)
CDP_DIR="$HOME/Library/Application Support/Google/Chrome-NoCFO"
mkdir -p "$CDP_DIR"
cp -R "$HOME/Library/Application Support/Google/Chrome/Default" "$CDP_DIR/Default"
cp "$HOME/Library/Application Support/Google/Chrome/Local State" "$CDP_DIR/"

# Launch Chrome with CDP enabled
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$CDP_DIR"
```

Verify CDP is working: `curl -s http://127.0.0.1:9222/json/version` should return JSON.

**Record** a workflow (interact with the browser, then Ctrl+C to save):

```bash
nocfo record start my_workflow --url https://example.com
```

**Enhance** with Claude vision (adds semantic descriptions per step + workflow summary):

```bash
nocfo record enhance my_workflow
```

**Replay** with optional vision fallback (when selectors fail, Claude vision locates elements by screenshot):

```bash
# Selector-based replay
nocfo record replay my_workflow

# With vision fallback for failed selectors
nocfo record replay my_workflow --vision-fallback

# Faster replay, continue past failures
nocfo record replay my_workflow --vision-fallback --speed 2.0 --no-strict
```

**Manage** saved workflows:

```bash
# List all workflows
nocfo record list

# Show step-by-step summary
nocfo record show my_workflow
```

## Rules

Transaction categorization is defined in `rules.yaml`. Each rule matches bank transaction descriptions via regex and maps to debit/credit account pairs:

```yaml
rules:
  - name: salary_payment
    pattern: "^(LÖN|LÖNEUTBETALNING|SALARY)"
    case_insensitive: true
    debit_account: 7210   # Löner tjänstemän
    credit_account: 1930  # Företagskonto
```

Unmatched transactions are flagged for manual review.

## Testing

```bash
# Run all tests
.venv/bin/python -m pytest tests/

# With verbose output
.venv/bin/python -m pytest tests/ -v
```

## Project structure

```
src/nocfo/
├── cli.py                    # Click CLI entry point
├── config.py                 # Settings (pydantic-settings)
├── bookkeeping/
│   ├── closing.py            # Period closing logic
│   ├── journal.py            # Voucher/journal creation
│   ├── reconciliation.py     # Reconciliation logic
│   └── rules.py              # Rule engine for categorization
├── browser/
│   ├── server.py             # HTTP API server (Playwright)
│   ├── handler.py            # Request handler / page operations
│   ├── client.py             # Python client for the browser API
│   ├── chrome.py             # Chrome launch & CDP management
│   ├── operations_state.py   # Browser operation state tracking
│   └── tokens.py             # Browser-level token management
├── fortnox/
│   ├── api/
│   │   ├── client.py         # REST API client (httpx)
│   │   ├── auth.py           # OAuth2 token management
│   │   ├── models.py         # Pydantic models for API entities
│   │   ├── vouchers.py       # Voucher API
│   │   ├── accounts.py       # Chart of accounts
│   │   ├── invoices.py       # Invoice API
│   │   ├── supplier_invoices.py # Supplier invoice API
│   │   ├── file_connections.py  # File attachment API
│   │   ├── financial_years.py   # Financial year API
│   │   ├── inbox.py          # File inbox API
│   │   └── health.py         # API health checks
│   └── web/
│       ├── auth.py           # BankID / web login
│       ├── handlers.py       # Web UI request handlers
│       ├── navigate.py       # Fortnox SPA navigation
│       ├── session.py        # Web session management
│       ├── selectors.py      # CSS/XPath selectors for Fortnox UI
│       ├── evidence.py       # Screenshot evidence capture
│       ├── vision.py         # Claude vision fallback
│       ├── learned.py        # Learned selector persistence
│       └── operations/       # Per-task browser operations
│           ├── reconciliation.py
│           ├── period_closing.py
│           ├── reports.py
│           └── rules.py
├── web_agent/
│   ├── agent.py              # Claude AI-powered browser agent
│   ├── actions.py            # Agent action definitions
│   ├── browser.py            # Agent browser interface
│   ├── prompts.py            # System prompts for agent tasks
│   └── tasks/                # Pre-built agent tasks
│       ├── period_closing.py
│       └── reports.py
├── recorder/
│   ├── models.py             # Workflow/step Pydantic models
│   ├── recorder.py           # Browser event capture
│   ├── injector.py           # Injected JS for interaction capture
│   ├── replay.py             # ReplayEngine with selector fallback
│   ├── enhancer.py           # Claude vision enhancement
│   └── vision_fallback.py    # Vision-based coordinate fallback
├── scheduler/
│   ├── runner.py             # APScheduler-based runner
│   └── jobs.py               # Job definitions
└── storage/
    ├── database.py           # SQLite via aiosqlite
    ├── idempotency.py        # Duplicate voucher prevention
    └── tokens.py             # OAuth token storage

rules.yaml                    # Transaction categorization rules
tests/                        # ~220 tests (pytest + pytest-asyncio)
```
