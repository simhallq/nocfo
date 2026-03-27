---
name: period-closing
description: Lock (close) an accounting period in Fortnox to prevent further changes.
---

# Period Closing

Use this skill when the user wants to close/lock an accounting period in Fortnox.

## When to use

- User says "close period", "lock period", "stang period", "las period"
- User asks about period management
- Heartbeat reminder after month-end

## Flow

### 1. Confirm the period

Always explicitly confirm which period to close:

"Are you sure you want to close period **2024-02** (February 2024)? This will lock all vouchers in that period and **cannot be undone**."

### 2. Ensure session is valid

Check `/auth/session/{customer_id}` first.

### 3. Close the period

Only after explicit user confirmation:

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}", "period": "2024-02"}' \
  http://host.docker.internal:8790/period/close
```

### 4. Confirm

"Period 2024-02 is now locked. No further changes can be made to vouchers in February 2024."

## Rules

- **This is IRREVERSIBLE.** Always warn the user clearly.
- **Two-step confirmation required.** First ask "which period?", then confirm "are you sure?"
- Period format is YYYY-MM
- If the user says "close last month", calculate which month that is
- Suggest running reconciliation before closing, if it hasn't been done: "Before closing, it's usually a good idea to run a reconciliation first. Want me to do that?"
