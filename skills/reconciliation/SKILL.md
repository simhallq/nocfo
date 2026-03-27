---
name: reconciliation
description: Run bank reconciliation in Fortnox to match bank transactions against booked entries.
---

# Bank Reconciliation

Use this skill when the user wants to reconcile their bank account (stamma av) in Fortnox.

## When to use

- User says "reconcile", "stam av", "avstamning", "match bank transactions"
- User asks if their bank account is up to date
- During periodic checks (heartbeat)

## Flow

### 1. Ensure session is valid

Check `/auth/session/{customer_id}` first.

### 2. Run reconciliation

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}", "account": "1930"}' \
  http://host.docker.internal:8790/reconciliation/run
```

The most common account to reconcile is **1930** (foretagskonto/bank account). If the user doesn't specify, ask or default to 1930.

### 3. Report results

Summarize clearly:
- How many transactions were matched
- Any unmatched transactions that need attention
- The current reconciled balance

## Rules

- Requires both `customer_id` and `account` number
- If the user doesn't specify an account, ask: "Which account should I reconcile? The most common is 1930 (foretagskonto)."
- If there are unmatched transactions, explain what they might be and suggest next steps
