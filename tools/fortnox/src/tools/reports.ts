import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxReportsDiscover = {
  name: "fortnox_reports_discover",
  description:
    "Discover available Fortnox report types and their API endpoints. " +
    "Call this to see what reports are available before downloading.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
  }),

  async execute(_id: string, params: { customer_id: string }) {
    const res = await fortnoxApi("POST", "/reports/discover", {
      customer_id: params.customer_id,
    });
    if (!res.ok) return errorResult("Report discovery failed", res.data);
    return jsonResult(res.data);
  },
};

export const fortnoxReportsDownload = {
  name: "fortnox_reports_download",
  description:
    "Download a financial report from Fortnox. " +
    'Use "balance_sheet" for balansrakning and "income_statement" for resultatrakning. ' +
    "Ask the user for the period if not specified.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
    type: Type.String({
      description:
        'Report type: "balance_sheet", "income_statement", etc.',
    }),
    period: Type.String({
      description: 'Period in YYYY-MM format, e.g. "2024-02"',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; type: string; period: string },
  ) {
    const res = await fortnoxApi("POST", "/reports/download", {
      customer_id: params.customer_id,
      type: params.type,
      period: params.period,
    });
    if (!res.ok) return errorResult("Report download failed", res.data);
    return jsonResult(res.data);
  },
};
