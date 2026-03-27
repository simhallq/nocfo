import { Type } from "@sinclair/typebox";
import { CustomerIdParam, callFortnox } from "../client.js";

export const fortnoxReceiptAnalyze = {
  name: "fortnox_receipt_analyze",
  description:
    "Analyze a receipt or invoice PDF and return proposed voucher entries. " +
    "This is a DRY RUN — nothing is written to Fortnox. " +
    "ALWAYS call this before fortnox_receipt_book. " +
    "Show the preview to the user and wait for confirmation before booking.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
    file_content: Type.String({
      description: "Base64-encoded PDF/image file content",
    }),
    filename: Type.String({
      description: 'Original filename, e.g. "faktura-2024-001.pdf"',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; file_content: string; filename: string },
  ) {
    return callFortnox("POST", "/receipts/analyze", params, "Receipt analysis failed");
  },
};

const VoucherRowSchema = Type.Object({
  account: Type.Number({ description: "BAS account number, e.g. 6110" }),
  debit: Type.String({ description: 'Debit amount as string, e.g. "800.00"' }),
  credit: Type.String({ description: 'Credit amount as string, e.g. "0"' }),
  transaction_information: Type.String({ description: "Line description" }),
});

const VoucherSchema = Type.Object({
  description: Type.String({
    description: "Voucher description, e.g. supplier name + invoice number",
  }),
  voucher_series: Type.String({ description: 'Usually "A"' }),
  transaction_date: Type.String({ description: "ISO date, e.g. 2024-03-15" }),
  rows: Type.Array(VoucherRowSchema, {
    description: "Voucher rows — total debits must equal total credits",
  }),
});

export const fortnoxReceiptBook = {
  name: "fortnox_receipt_book",
  description:
    "Book an approved voucher in Fortnox and attach the PDF. " +
    "NEVER call without first calling fortnox_receipt_analyze and " +
    "getting explicit user confirmation. Pass the proposed_voucher " +
    "from the analyze response (or a user-modified version).",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
    file_content: Type.String({
      description: "Base64-encoded PDF/image file content (same as analyze)",
    }),
    filename: Type.String({ description: "Original filename" }),
    voucher: VoucherSchema,
  }),

  async execute(
    _id: string,
    params: {
      customer_id: string;
      file_content: string;
      filename: string;
      voucher: Record<string, unknown>;
    },
  ) {
    return callFortnox("POST", "/receipts/book", params, "Receipt booking failed");
  },
};
