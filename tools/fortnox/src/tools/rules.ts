import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxRulesList = {
  name: "fortnox_rules_list",
  description:
    "List current Regelverk (automatic categorization rules) in Fortnox. " +
    "Always show current rules before proposing changes.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
  }),

  async execute(_id: string, params: { customer_id: string }) {
    const res = await fortnoxApi("POST", "/rules/list", {
      customer_id: params.customer_id,
    });
    if (!res.ok) return errorResult("Rules list failed", res.data);
    return jsonResult(res.data);
  },
};

export const fortnoxRulesSync = {
  name: "fortnox_rules_sync",
  description:
    "Sync categorization rules to Fortnox. " +
    "Always list current rules first with fortnox_rules_list " +
    "and confirm changes with the user before syncing.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
    rules: Type.Array(
      Type.Object({
        pattern: Type.String({ description: "Transaction text match pattern" }),
        debit_account: Type.Number({ description: "Debit account number" }),
        credit_account: Type.Number({ description: "Credit account number" }),
        vat_code: Type.Optional(Type.String({ description: "VAT code" })),
      }),
      { description: "Rules to sync" },
    ),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; rules: unknown[] },
  ) {
    const res = await fortnoxApi("POST", "/rules/sync", {
      customer_id: params.customer_id,
      rules: params.rules,
    });
    if (!res.ok) return errorResult("Rules sync failed", res.data);
    return jsonResult(res.data);
  },
};
