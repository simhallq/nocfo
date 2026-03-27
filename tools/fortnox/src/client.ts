const BASE_URL = process.env.FORTNOX_API_URL ?? "http://host.docker.internal:8790";
const TOKEN = process.env.FORTNOX_API_TOKEN ?? "";

export interface ApiResult {
  ok: boolean;
  status: number;
  data: unknown;
}

export async function fortnoxApi(
  method: string,
  path: string,
  body?: Record<string, unknown>,
): Promise<ApiResult> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (TOKEN) {
    headers["Authorization"] = `Bearer ${TOKEN}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers,
    ...(body ? { body: JSON.stringify(body) } : {}),
  });

  let data: unknown;
  try {
    data = await res.json();
  } catch {
    data = { raw: await res.text() };
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
