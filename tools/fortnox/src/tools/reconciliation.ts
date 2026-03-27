import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxReconciliationRun = {
  name: "fortnox_reconciliation_run",
  description:
    "Execute bank reconciliation for a specific account in Fortnox. " +
    "The most common account is 1930 (foretagskonto/bank). " +
    "Requires a valid customer session.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
    account: Type.String({
      description:
        'Account number to reconcile, e.g. "1930" for bank account',
    }),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; account: string },
  ) {
    const res = await fortnoxApi("POST", "/reconciliation/run", {
      customer_id: params.customer_id,
      account: params.account,
    });
    if (!res.ok) return errorResult("Reconciliation failed", res.data);
    return jsonResult(res.data);
  },
};
