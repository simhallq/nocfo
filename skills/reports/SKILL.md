---
name: reports
description: Discover and download financial reports from Fortnox (balance sheet, income statement, etc.)
---

# Financial Reports

Use this skill when the user wants to view or download financial reports from Fortnox.

## When to use

- User says "report", "balance sheet", "income statement", "balansrakning", "resultatrakning"
- User asks about financial overview or company performance
- User wants to export financial data

## Flow

### 1. Discover available reports (optional)

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}"}' \
  http://host.docker.internal:8790/reports/discover
```

### 2. Download the requested report

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"customer_id": "{customer_id}", "type": "balance_sheet", "period": "2024-02"}' \
  http://host.docker.internal:8790/reports/download
```

### 3. Present the report

If PDF, share the file with the user. If the data is returned as JSON, summarize the key figures.

## Common report types

| Swedish | English | Type value |
|---------|---------|------------|
| Balansrakning | Balance sheet | `balance_sheet` |
| Resultatrakning | Income statement | `income_statement` |

## Rules

- If the user doesn't specify a period, ask: "For which period? (e.g., 2024-02 or 2024 for full year)"
- Translate between Swedish and English report names naturally
- If the user asks for a "financial overview", offer both balance sheet and income statement
