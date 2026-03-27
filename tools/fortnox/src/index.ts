import { fortnoxHealth } from "./tools/health.js";
import {
  fortnoxSessionCheck,
  fortnoxAuthStart,
  fortnoxOperationStatus,
} from "./tools/auth.js";
import {
  fortnoxReceiptAnalyze,
  fortnoxReceiptBook,
} from "./tools/receipts.js";
import { fortnoxReconciliationRun } from "./tools/reconciliation.js";
import { fortnoxPeriodClose } from "./tools/period.js";
import {
  fortnoxReportsDiscover,
  fortnoxReportsDownload,
} from "./tools/reports.js";
import { fortnoxRulesList, fortnoxRulesSync } from "./tools/rules.js";

const ALL_TOOLS = [
  fortnoxHealth,
  fortnoxSessionCheck,
  fortnoxAuthStart,
  fortnoxOperationStatus,
  fortnoxReceiptAnalyze,
  fortnoxReceiptBook,
  fortnoxReconciliationRun,
  fortnoxPeriodClose,
  fortnoxReportsDiscover,
  fortnoxReportsDownload,
  fortnoxRulesList,
  fortnoxRulesSync,
];

interface PluginApi {
  registerTool(tool: {
    name: string;
    description: string;
    parameters: unknown;
    execute: (id: string, params: Record<string, unknown>) => Promise<unknown>;
  }): void;
}

export default {
  id: "fortnox",
  name: "Fortnox Accounting",
  description:
    "Tools for managing Fortnox accounting: authentication, receipt booking, " +
    "reconciliation, period closing, reports, and categorization rules.",

  register(api: PluginApi) {
    for (const tool of ALL_TOOLS) {
      api.registerTool(tool as Parameters<PluginApi["registerTool"]>[0]);
    }
  },
};
