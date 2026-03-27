# Tools

## Fortnox Service API

Base URL: `http://host.docker.internal:8790`
Auth: `Authorization: Bearer {FORTNOX_API_TOKEN}`

All endpoints return JSON. Errors include `{"error": "message"}` with appropriate HTTP status codes.

---

### Health & Status

#### `GET /health`
Check if the Fortnox service and Chrome CDP are running. **No auth required.**

```bash
curl http://host.docker.internal:8790/health
```

Response:
```json
{"status": "ok", "chrome": {"cdp_reachable": true, "port": 9222}}
```

Status is `"ok"` or `"degraded"` (Chrome CDP unreachable).

**Rule:** Always call this before any operation. If degraded, tell the user Chrome needs to be restarted.

---

#### `GET /auth/session/{customer_id}`
Check if a customer has a valid Fortnox session.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://host.docker.internal:8790/auth/session/simon-hallqvist-invest
```

Response:
```json
{"customer_id": "simon-hallqvist-invest", "has_session": true}
```

**Rule:** Always check this before running operations for a customer. If `has_session` is false, guide the user through BankID authentication first.

---

### Authentication

#### `POST /auth/start`
Create a BankID authentication operation. Returns a `live_url` that the user must open to complete BankID login.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest"}' \
  http://host.docker.internal:8790/auth/start
```

Request body:
- `customer_id` (string, required): Which company to authenticate for
- `force` (boolean, optional): Set to `true` to re-authenticate even if session is valid

Response (202):
```json
{
  "operation_id": "abc123",
  "status": "awaiting_user",
  "live_url": "https://funnel.example.com/auth/live?token=...",
  "poll_url": "/operation/abc123",
  "message": "Send live_url to customer. BankID starts when they open it."
}
```

If session is already valid (and `force` is not set):
```json
{"status": "already_authenticated", "customer_id": "...", "message": "Valid session exists."}
```

**Rule:** Send the `live_url` directly to the user. They must open it on their device to scan the BankID QR code. Then poll `/operation/{id}` until status is `"complete"`.

---

#### `GET /operation/{operation_id}`
Poll an async operation's status.

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://host.docker.internal:8790/operation/abc123
```

Response:
```json
{"operation_id": "abc123", "status": "complete", "result": {"authenticated": true}}
```

Possible statuses: `awaiting_user`, `starting`, `pending`, `waiting_for_qr`, `complete`, `failed`

**Rule:** Poll every 3-5 seconds. Stop when status is `complete` or `failed`.

---

### Receipt Booking

#### `POST /receipts/analyze`
Analyze a receipt/invoice PDF and return proposed voucher entries. **Dry run only -- nothing is written to Fortnox.**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "simon-hallqvist-invest",
    "file_content": "<base64-encoded PDF>",
    "filename": "faktura-2024-001.pdf"
  }' \
  http://host.docker.internal:8790/receipts/analyze
```

Request body:
- `customer_id` (string, required)
- `file_path` (string): Absolute path on the server, OR
- `file_content` (string): Base64-encoded file bytes
- `filename` (string): Required when using `file_content`

Response:
```json
{
  "supplier_name": "Acme AB",
  "invoice_number": "2024-001",
  "invoice_date": "2024-03-15",
  "payment_date": "2024-04-15",
  "description": "Kontorsmaterial",
  "total_net": "800.00",
  "total_vat": "200.00",
  "total_gross": "1000.00",
  "vat_rate": 25,
  "confidence": "high",
  "notes": "",
  "items": [...],
  "preview": "Debet 6110 Kontorsmaterial  800.00\nDebet 2640 Moms  200.00\nKredit 2440 Leverantorsskuld  1000.00",
  "proposed_voucher": {
    "description": "Acme AB - 2024-001",
    "voucher_series": "A",
    "transaction_date": "2024-03-15",
    "rows": [
      {"account": 6110, "debit": "800.00", "credit": "0", "transaction_information": "Kontorsmaterial"},
      {"account": 2640, "debit": "200.00", "credit": "0", "transaction_information": "Moms"},
      {"account": 2440, "debit": "0", "credit": "1000.00", "transaction_information": "Leverantorsskuld"}
    ]
  }
}
```

**Rule:** ALWAYS call this before `/receipts/book`. Show the `preview` to the user and explain the account mappings. Wait for explicit confirmation before proceeding to book. If `confidence` is not "high", warn the user.

---

#### `POST /receipts/book`
Book an approved voucher in Fortnox and attach the PDF.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "simon-hallqvist-invest",
    "file_content": "<base64-encoded PDF>",
    "filename": "faktura-2024-001.pdf",
    "voucher": {
      "description": "Acme AB - 2024-001",
      "voucher_series": "A",
      "transaction_date": "2024-03-15",
      "rows": [
        {"account": 6110, "debit": "800.00", "credit": "0", "transaction_information": "Kontorsmaterial"},
        {"account": 2640, "debit": "200.00", "credit": "0", "transaction_information": "Moms"},
        {"account": 2440, "debit": "0", "credit": "1000.00", "transaction_information": "Leverantorsskuld"}
      ]
    }
  }' \
  http://host.docker.internal:8790/receipts/book
```

Request body:
- `customer_id` (string, required)
- `file_path` or `file_content` + `filename` (required): The PDF to attach
- `voucher` (object, required): The `proposed_voucher` from `/receipts/analyze` (possibly modified by user)

Response:
```json
{"voucher_series": "A", "voucher_number": 42, "status": "created"}
```

**Rule:** NEVER call this without first calling `/receipts/analyze` and getting user confirmation. The voucher must balance (total debits == total credits) or it will be rejected.

---

### Reconciliation

#### `POST /reconciliation/run`
Execute bank reconciliation for a specific account.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest", "account": "1930"}' \
  http://host.docker.internal:8790/reconciliation/run
```

Request body:
- `customer_id` (string, required)
- `account` (string, required): Account number to reconcile (e.g., "1930" for bank account)
- `matches` (array, optional): Pre-matched transaction pairs

Response: Operation result with reconciliation details.

**Rule:** Requires valid session. The most commonly reconciled account is 1930 (foretagskonto/bank).

---

### Period Closing

#### `POST /period/close`
Lock an accounting period. **This is irreversible.**

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest", "period": "2024-02"}' \
  http://host.docker.internal:8790/period/close
```

Request body:
- `customer_id` (string, required)
- `period` (string, required): Period to close in YYYY-MM format

Response: Operation result confirming period was locked.

**Rule:** ALWAYS confirm with the user before closing. State clearly: "This will lock period {period}. No more changes can be made to vouchers in this period. Are you sure?" This cannot be undone.

---

### Reports

#### `POST /reports/discover`
Discover available Fortnox report types and API endpoints.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest"}' \
  http://host.docker.internal:8790/reports/discover
```

Request body:
- `customer_id` (string, required)

Response: List of available report types and their internal endpoints.

---

#### `POST /reports/download`
Download a financial report.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest", "type": "balance_sheet", "period": "2024-02"}' \
  http://host.docker.internal:8790/reports/download
```

Request body:
- `customer_id` (string, required)
- `type` (string, required): Report type (e.g., `"balance_sheet"`, `"income_statement"`)
- `period` (string, required): Period in YYYY-MM format

Response: PDF file download, or JSON with `file_data` (base64) if the report data is embedded.

**Rule:** If the user asks for a "balansrakning", use type `"balance_sheet"`. For "resultatrakning", use `"income_statement"`. Ask for the period if not specified.

---

### Rules

#### `POST /rules/list`
List current Regelverk (automatic categorization rules) in Fortnox.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest"}' \
  http://host.docker.internal:8790/rules/list
```

Request body:
- `customer_id` (string, required)

Response: List of current categorization rules.

---

#### `POST /rules/sync`
Sync categorization rules to Fortnox.

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "simon-hallqvist-invest", "rules": [...]}' \
  http://host.docker.internal:8790/rules/sync
```

Request body:
- `customer_id` (string, required)
- `rules` (array, required): Rules to sync

**Rule:** Always show current rules (via `/rules/list`) before proposing changes.

---

## Operational rules

1. **Always check health first.** Call `GET /health` before any operation sequence.
2. **Always check session.** Call `GET /auth/session/{id}` before customer operations.
3. **Two-step booking.** Always analyze before booking. Never skip the preview.
4. **Confirm destructive ops.** Period closing is irreversible. Always get explicit "yes".
5. **Handle auth flow correctly.** Send the `live_url` to the user immediately -- it's time-sensitive for BankID. Poll the operation until complete.
6. **Report errors clearly.** If an operation fails, explain what happened in plain language.
