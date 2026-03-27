import { Type } from "@sinclair/typebox";
import { callFortnox } from "../client.js";

export const fortnoxHealth = {
  name: "fortnox_health",
  description:
    "Check if the Fortnox service and Chrome CDP are running. " +
    "Call this before any other Fortnox operation.",
  parameters: Type.Object({}),

  async execute(_id: string) {
    return callFortnox("GET", "/health", undefined, "Health check failed");
  },
};
