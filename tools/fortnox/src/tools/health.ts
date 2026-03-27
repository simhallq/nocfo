import { Type } from "@sinclair/typebox";
import { fortnoxApi, jsonResult, errorResult } from "../client.js";

export const fortnoxHealth = {
  name: "fortnox_health",
  description:
    "Check if the Fortnox service and Chrome CDP are running. " +
    "Call this before any other Fortnox operation.",
  parameters: Type.Object({}),

  async execute() {
    const res = await fortnoxApi("GET", "/health");
    if (!res.ok) return errorResult("Health check failed", res.data);
    return jsonResult(res.data);
  },
};
