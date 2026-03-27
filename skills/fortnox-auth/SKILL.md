---
name: fortnox-auth
description: Authenticate with Fortnox via BankID. Check session status, initiate BankID login, and manage customer sessions.
---

# Fortnox Authentication

Use this skill when the user wants to log in to Fortnox, check their session status, or needs to re-authenticate via BankID.

## When to use

- User says "log in", "authenticate", "logga in", "BankID"
- User asks to check their session
- Another operation fails due to expired session
- Before running any Fortnox operation, silently check the session

## Flow

### 1. Check session status

```bash
curl -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  http://host.docker.internal:8790/auth/session/{customer_id}
```

If `has_session` is true, tell the user they're already logged in.

### 2. Start BankID authentication (if needed)

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}"}' \
  http://host.docker.internal:8790/auth/start
```

**Immediately send the `live_url` to the user.** This is time-sensitive -- the BankID QR code expires quickly.

Tell the user: "Open this link on your phone or computer to complete BankID authentication."

### 3. Poll for completion

```bash
curl -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  http://host.docker.internal:8790/operation/{operation_id}
```

Poll every 3-5 seconds. When status is `complete`, confirm to the user. If `failed`, explain and offer to retry.

## Rules

- Always check the session before starting authentication
- If the user has multiple companies, ask which one
- Explain what BankID is if the user seems unfamiliar: "BankID is Sweden's digital ID system. You'll scan a QR code with the BankID app on your phone."
- Never attempt to bypass or automate the BankID step -- it requires the user's physical interaction
