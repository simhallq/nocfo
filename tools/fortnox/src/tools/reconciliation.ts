import { Type } from "@sinclair/typebox";
import { CustomerIdParam, callFortnox } from "../client.js";

export const fortnoxReconciliationRun = {
  name: "fortnox_reconciliation_run",
  description:
    "Execute bank reconciliation for a specific account in Fortnox. " +
    "The most common account is 1930 (foretagskonto/bank). " +
    "Requires a valid customer session.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
    account: Type.String({
      description:
        'Account number to reconcile, e.g. "1930" for bank account',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; account: string },
  ) {
    return callFortnox("POST", "/reconciliation/run", params, "Reconciliation failed");
  },
};
