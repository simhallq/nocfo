import { Type } from "@sinclair/typebox";
import { CustomerIdParam, callFortnox } from "../client.js";

export const fortnoxReportsDiscover = {
  name: "fortnox_reports_discover",
  description:
    "Discover available Fortnox report types and their API endpoints. " +
    "Call this to see what reports are available before downloading.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
  }),

  async execute(_id: string, params: { customer_id: string }) {
    return callFortnox("POST", "/reports/discover", params, "Report discovery failed");
  },
};

export const fortnoxReportsDownload = {
  name: "fortnox_reports_download",
  description:
    "Download a financial report from Fortnox. " +
    "Ask the user for the period if not specified.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
    type: Type.Union([
      Type.Literal("balance_sheet"),
      Type.Literal("income_statement"),
    ], { description: "Report type: balance_sheet (balansrakning) or income_statement (resultatrakning)" }),
    period: Type.String({
      description: 'Period in YYYY-MM format, e.g. "2024-02"',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; type: string; period: string },
  ) {
    return callFortnox("POST", "/reports/download", params, "Report download failed");
  },
};
