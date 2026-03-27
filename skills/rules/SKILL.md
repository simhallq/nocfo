---
name: rules
description: View and manage Fortnox automatic categorization rules (Regelverk/Automatkontering).
---

# Categorization Rules

Use this skill when the user wants to view or manage automatic transaction categorization rules in Fortnox.

## When to use

- User says "rules", "regelverk", "automatkontering", "categorization"
- User asks about how transactions are automatically sorted
- User wants to add or modify a rule

## Flow

### 1. List current rules

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}"}' \
  http://host.docker.internal:8790/rules/list
```

Present the rules in a clear format showing the pattern match and target accounts.

### 2. Sync updated rules (if modifying)

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}", "rules": [...]}' \
  http://host.docker.internal:8790/rules/sync
```

## Rules

- Always show current rules before proposing changes
- Explain what each rule does in plain language
- When adding a new rule, explain the account mapping: "This rule will automatically categorize transactions matching '{pattern}' to account {number} ({name})"
