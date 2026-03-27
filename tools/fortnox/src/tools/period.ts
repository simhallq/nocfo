import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxPeriodClose = {
  name: "fortnox_period_close",
  description:
    "Lock an accounting period in Fortnox. THIS IS IRREVERSIBLE. " +
    "ALWAYS confirm with the user before calling. State clearly which " +
    "period will be locked and that no further changes can be made.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
    period: Type.String({
      description: 'Period to close in YYYY-MM format, e.g. "2024-02"',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; period: string },
  ) {
    const res = await fortnoxApi("POST", "/period/close", {
      customer_id: params.customer_id,
      period: params.period,
    });
    if (!res.ok) return errorResult("Period close failed", res.data);
    return jsonResult(res.data);
  },
};
