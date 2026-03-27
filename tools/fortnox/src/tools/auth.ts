import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxSessionCheck = {
  name: "fortnox_session_check",
  description:
    "Check if a customer has a valid Fortnox session. " +
    "Always call this before running operations for a customer. " +
    "If has_session is false, use fortnox_auth_start to authenticate.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
  }),

  async execute(_id: string, params: { customer_id: string }) {
    const res = await fortnoxApi("GET", `/auth/session/${params.customer_id}`);
    if (!res.ok) return errorResult("Session check failed", res.data);
    return jsonResult(res.data);
  },
};

export const fortnoxAuthStart = {
  name: "fortnox_auth_start",
  description:
    "Start BankID authentication for a customer. Returns a live_url that " +
    "you MUST send to the user immediately — they need to open it to scan " +
    "the BankID QR code. Then poll fortnox_operation_status until complete.",
  parameters: Type.Object({
    customer_id: Type.String({
      description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
    }),
    force: Type.Optional(
      Type.Boolean({
        description: "Set true to re-authenticate even if session is valid",
      }),
    ),
  }),

  async execute(
    _id: string,
    params: { customer_id: string; force?: boolean },
  ) {
    const res = await fortnoxApi("POST", "/auth/start", {
      customer_id: params.customer_id,
      ...(params.force ? { force: true } : {}),
    });
    if (!res.ok) return errorResult("Auth start failed", res.data);
    return jsonResult(res.data);
  },
};

export const fortnoxOperationStatus = {
  name: "fortnox_operation_status",
  description:
    "Poll the status of an async operation (e.g. BankID auth). " +
    'Poll every 3-5 seconds until status is "complete" or "failed".',
  parameters: Type.Object({
    operation_id: Type.String({
      description: "Operation ID returned from fortnox_auth_start",
    }),
  }),

  async execute(_id: string, params: { operation_id: string }) {
    const res = await fortnoxApi("GET", `/operation/${params.operation_id}`);
    if (!res.ok) return errorResult("Operation status check failed", res.data);
    return jsonResult(res.data);
  },
};
