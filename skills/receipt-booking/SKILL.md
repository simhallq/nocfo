---
name: receipt-booking
description: Analyze receipts and invoices, propose voucher entries, and book them in Fortnox after user confirmation.
---

# Receipt Booking

Use this skill when the user wants to book a receipt, invoice, or any financial document (kvitto, faktura) into Fortnox.

## When to use

- User shares a PDF or image of a receipt/invoice
- User says "book this", "bokfor", "verifikat", "faktura", "kvitto"
- User asks about how a document should be categorized

## Flow

### 1. Ensure session is valid

Check `/auth/session/{customer_id}` first. If expired, switch to the fortnox-auth skill.

### 2. Analyze the document

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "{customer_id}",
    "file_content": "{base64_encoded_file}",
    "filename": "{original_filename}"
  }' \
  http://host.docker.internal:8790/receipts/analyze
```

### 3. Present the preview to the user

Show the proposed voucher in a clear format:

```
Leverantor: Acme AB
Fakturanr: 2024-001
Datum: 2024-03-15

Foreslagna konteringar:
  Debet  6110  Kontorsmaterial      800,00 kr
  Debet  2640  Ingaende moms        200,00 kr
  Kredit 2440  Leverantorsskulder  1 000,00 kr

Ska jag boka detta?
```

Explain the account choices in plain language. For example: "6110 is for office supplies (kontorsmaterial). The 25% VAT goes to 2640."

If the confidence is not "high", warn the user: "I'm not fully confident about this categorization. Please double-check the accounts."

### 4. Wait for confirmation

Do NOT proceed without an explicit "yes", "ja", "book it", "bokfor" from the user.

The user may want to adjust accounts or amounts before booking.

### 5. Book the voucher

```bash
curl -X POST -H "Authorization: Bearer $FORTNOX_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "{customer_id}",
    "file_content": "{base64_encoded_file}",
    "filename": "{original_filename}",
    "voucher": {proposed_voucher_from_analyze}
  }' \
  http://host.docker.internal:8790/receipts/book
```

### 6. Confirm to the user

"Bokfort! Verifikation A-42 skapad i Fortnox."

## Rules

- **NEVER skip the preview step.** Always show the proposed voucher and wait for confirmation.
- If the user provides a modified voucher, verify that debits equal credits before booking.
- Common Swedish account mappings:
  - 6110: Kontorsmaterial (office supplies)
  - 6210: Telefon och internet
  - 6530: Redovisning och revision
  - 7610: Utbildning (education/certifications)
  - 2640: Ingaende moms (input VAT)
  - 2440: Leverantorsskulder (accounts payable)
  - 1930: Foretagskonto/bank
