import { Type } from "@sinclair/typebox";
import { CustomerIdParam, callFortnox } from "../client.js";

export const fortnoxRulesList = {
  name: "fortnox_rules_list",
  description:
    "List current Regelverk (automatic categorization rules) in Fortnox. " +
    "Always show current rules before proposing changes.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
  }),

  async execute(_id: string, params: { customer_id: string }) {
    return callFortnox("POST", "/rules/list", params, "Rules list failed");
  },
};

export const fortnoxRulesSync = {
  name: "fortnox_rules_sync",
  description:
    "Sync categorization rules to Fortnox. " +
    "Always list current rules first with fortnox_rules_list " +
    "and confirm changes with the user before syncing.",
  parameters: Type.Object({
    customer_id: CustomerIdParam,
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
    return callFortnox("POST", "/rules/sync", params, "Rules sync failed");
  },
};
