import { Type } from "@sinclair/typebox";
import { CustomerIdParam, callFortnox } from "../client.js";

export const fortnoxPeriodClose = {
  name: "fortnox_period_close",
  description:
    "Lock an accounting period in Fortnox. THIS IS IRREVERSIBLE. " +
    "ALWAYS confirm with the user before calling. State clearly which " +
    "period will be locked and that no further changes can be made.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
    period: Type.String({
      description: 'Period to close in YYYY-MM format, e.g. "2024-02"',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; period: string },
  ) {
    return callFortnox("POST", "/period/close", params, "Period close failed");
  },
};
