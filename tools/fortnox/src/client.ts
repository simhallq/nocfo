import { Type } from "@sinclair/typebox";

const TIMEOUT_MS = 60_000;

function getBaseUrl() {
  return process.env.FORTNOX_API_URL ?? "http://host.docker.internal:8790";
}

function getToken() {
  return process.env.FORTNOX_API_TOKEN ?? "";
}

export const CustomerIdParam = Type.String({
  description: 'Fortnox customer ID, e.g. "simon-hallqvist-invest"',
});

export async function fortnoxApi(
  method: "GET" | "POST",
  path: string,
  body?: Record<string, unknown>,
) {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body) headers["Content-Type"] = "application/json";

  const res = await fetch(`${getBaseUrl()}${path}`, {
    method,
    headers,
    signal: AbortSignal.timeout(TIMEOUT_MS),
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  const raw = await res.text();
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    data = { raw };
  }
  return { ok: res.ok, status: res.status, data };
}

export function textResult(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

export function jsonResult(data: unknown) {
  return textResult(JSON.stringify(data, null, 2));
}

export function errorResult(msg: string, detail?: unknown) {
  const text = detail
    ? `Error: ${msg}\n\n${JSON.stringify(detail, null, 2)}`
    : `Error: ${msg}`;
  return textResult(text);
}

export async function callFortnox(
  method: "GET" | "POST",
  path: string,
  body?: Record<string, unknown>,
  errorLabel?: string,
) {
  const res = await fortnoxApi(method, path, body);
  if (!res.ok) return errorResult(errorLabel ?? "Request failed", res.data);
  return jsonResult(res.data);
}
