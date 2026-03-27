---
name: fortnox-tools
description: Typed tool wrappers for all Fortnox accounting operations. Covers health checks, BankID authentication, receipt booking, reconciliation, period closing, financial reports, and categorization rules.
---

# Fortnox Tools

You have 12 typed tools for operating Fortnox. Use these instead of raw curl/exec calls — they handle authentication, validation, and error formatting automatically.

## Available tools

| Tool | Purpose |
|------|---------|
| `fortnox_health` | Check service + Chrome CDP status |
| `fortnox_session_check` | Check if a customer has a valid session |
| `fortnox_auth_start` | Start BankID authentication |
| `fortnox_operation_status` | Poll async operation (e.g. BankID) status |
| `fortnox_receipt_analyze` | Analyze a receipt PDF (dry run) |
| `fortnox_receipt_book` | Book an approved voucher |
| `fortnox_reconciliation_run` | Run bank reconciliation |
| `fortnox_period_close` | Lock an accounting period (irreversible) |
| `fortnox_reports_discover` | List available report types |
| `fortnox_reports_download` | Download a financial report |
| `fortnox_rules_list` | List categorization rules |
| `fortnox_rules_sync` | Update categorization rules |

## Standard workflow

Before any operation, always follow this sequence:

### 1. Health check
```
fortnox_health()
```
If status is "degraded", tell the user Chrome needs to be restarted. Do not proceed.

### 2. Session check
```
fortnox_session_check(customer_id: "simon-hallqvist-invest")
```
If `has_session` is false, proceed to authentication. Otherwise, skip to the operation.

### 3. Authentication (if needed)
```
fortnox_auth_start(customer_id: "simon-hallqvist-invest")
```
**Immediately send the `live_url` from the response to the user.** This is time-sensitive — the BankID QR code expires. Then poll:
```
fortnox_operation_status(operation_id: "abc123")
```
Poll every 3-5 seconds. When status is `"complete"`, proceed. If `"failed"`, explain the error and offer to retry.

## Receipt booking flow

This is the most common operation. Always follow the two-step pattern:

### Step 1: Analyze (dry run)
```
fortnox_receipt_analyze(
  customer_id: "simon-hallqvist-invest",
  file_content: "<base64 PDF>",
  filename: "faktura-2024-001.pdf"
)
```

Present the response to the user clearly:
- Supplier name and invoice number
- Each account entry with the account name and amount
- The `confidence` level — warn if not "high"
- Explain account choices (e.g., "6110 is Kontorsmaterial — office supplies")

### Step 2: Book (only after user confirms)
```
fortnox_receipt_book(
  customer_id: "simon-hallqvist-invest",
  file_content: "<base64 PDF>",
  filename: "faktura-2024-001.pdf",
  voucher: { ... proposed_voucher from analyze response ... }
)
```

**NEVER call fortnox_receipt_book without showing the preview first and getting an explicit "yes" from the user.**

If the user wants to change accounts or amounts, modify the voucher object accordingly before booking. Always verify that total debits equal total credits.

## Reconciliation

```
fortnox_reconciliation_run(
  customer_id: "simon-hallqvist-invest",
  account: "1930"
)
```

The default account is 1930 (foretagskonto/bank). If the user doesn't specify, ask or use 1930.

Report results clearly: matched transactions, unmatched items, current balance.

## Period closing

**This is irreversible.** Always use two-step confirmation:

1. Confirm: "I'm about to lock period **2024-02** (February 2024). After this, no changes can be made to vouchers in that period. Are you sure?"
2. Only after explicit "yes":
```
fortnox_period_close(
  customer_id: "simon-hallqvist-invest",
  period: "2024-02"
)
```

Suggest running reconciliation first if it hasn't been done: "Before closing, you might want to reconcile your bank account first."

## Reports

### Discover available types
```
fortnox_reports_discover(customer_id: "simon-hallqvist-invest")
```

### Download a report
```
fortnox_reports_download(
  customer_id: "simon-hallqvist-invest",
  type: "balance_sheet",
  period: "2024-02"
)
```

Common types:
- `"balance_sheet"` — Balansrakning
- `"income_statement"` — Resultatrakning

If the user asks for a "financial overview", offer both.

## Rules management

### List current rules
```
fortnox_rules_list(customer_id: "simon-hallqvist-invest")
```

Always show current rules before proposing changes.

### Sync updated rules
```
fortnox_rules_sync(
  customer_id: "simon-hallqvist-invest",
  rules: [
    { pattern: "Spotify", debit_account: 6210, credit_account: 2440 },
    ...
  ]
)
```

Explain each rule in plain language: "This rule will automatically categorize transactions containing 'Spotify' as Telefon och internet (6210)."

## Error handling

All tools return structured errors. Common patterns:

- **Session expired** → Call `fortnox_auth_start` to re-authenticate
- **400 Bad Request** → Explain what's wrong with the input (missing field, invalid format)
- **500 Server Error** → Suggest the user check the Fortnox service logs and retry
- **Connection refused** → The Fortnox service isn't running. Tell the user.

## Rules of engagement

1. **Always health check first.** A 2-second call that prevents confusing errors later.
2. **Always session check before operations.** Expired sessions are the #1 cause of failures.
3. **Never auto-book.** The analyze → preview → confirm → book flow is mandatory.
4. **Never auto-close periods.** Irreversible operations require explicit user consent.
5. **Explain account mappings.** Don't just say "6110" — say "6110 (Kontorsmaterial — office supplies)".
6. **Multi-customer awareness.** If the user has multiple companies, always confirm which one.
