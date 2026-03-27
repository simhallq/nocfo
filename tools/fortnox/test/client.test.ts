import { describe, it, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import {
  fortnoxApi,
  callFortnox,
  textResult,
  jsonResult,
  errorResult,
} from "../src/client.js";

// Helper to create a mock Response
function mockResponse(body: string, status = 200) {
  return new Response(body, { status, headers: { "Content-Type": "application/json" } });
}

describe("fortnoxApi", () => {
  let fetchMock: ReturnType<typeof mock.fn>;

  beforeEach(() => {
    process.env.FORTNOX_API_URL = "http://localhost:9999";
    process.env.FORTNOX_API_TOKEN = "test-token";
    fetchMock = mock.fn(fetch, () => Promise.resolve(mockResponse('{"status":"ok"}')));
    mock.method(globalThis, "fetch", fetchMock);
  });

  afterEach(() => {
    mock.restoreAll();
    delete process.env.FORTNOX_API_URL;
    delete process.env.FORTNOX_API_TOKEN;
  });

  it("sends GET request with auth header", async () => {
    await fortnoxApi("GET", "/health");

    assert.equal(fetchMock.mock.calls.length, 1);
    const [url, opts] = fetchMock.mock.calls[0].arguments as [string, RequestInit];
    assert.equal(url, "http://localhost:9999/health");
    assert.equal(opts.method, "GET");
    assert.equal((opts.headers as Record<string, string>)["Authorization"], "Bearer test-token");
  });

  it("does not send Content-Type on GET", async () => {
    await fortnoxApi("GET", "/health");

    const [, opts] = fetchMock.mock.calls[0].arguments as [string, RequestInit];
    assert.equal((opts.headers as Record<string, string>)["Content-Type"], undefined);
  });

  it("sends Content-Type on POST with body", async () => {
    await fortnoxApi("POST", "/auth/start", { customer_id: "test" });

    const [, opts] = fetchMock.mock.calls[0].arguments as [string, RequestInit];
    assert.equal((opts.headers as Record<string, string>)["Content-Type"], "application/json");
    assert.equal(opts.body, '{"customer_id":"test"}');
  });

  it("omits auth header when no token", async () => {
    delete process.env.FORTNOX_API_TOKEN;
    await fortnoxApi("GET", "/health");

    const [, opts] = fetchMock.mock.calls[0].arguments as [string, RequestInit];
    assert.equal((opts.headers as Record<string, string>)["Authorization"], undefined);
  });

  it("parses JSON response", async () => {
    const result = await fortnoxApi("GET", "/health");

    assert.deepEqual(result, { ok: true, status: 200, data: { status: "ok" } });
  });

  it("handles non-JSON response gracefully", async () => {
    mock.restoreAll();
    mock.method(globalThis, "fetch", () =>
      Promise.resolve(new Response("not json", { status: 500 })),
    );

    const result = await fortnoxApi("GET", "/health");

    assert.equal(result.ok, false);
    assert.equal(result.status, 500);
    assert.deepEqual(result.data, { raw: "not json" });
  });

  it("returns ok:false for error status codes", async () => {
    mock.restoreAll();
    mock.method(globalThis, "fetch", () =>
      Promise.resolve(mockResponse('{"error":"not found"}', 404)),
    );

    const result = await fortnoxApi("GET", "/missing");

    assert.equal(result.ok, false);
    assert.equal(result.status, 404);
  });

  it("uses default URL when env var not set", async () => {
    delete process.env.FORTNOX_API_URL;
    await fortnoxApi("GET", "/health");

    const [url] = fetchMock.mock.calls[0].arguments as [string];
    assert.equal(url, "http://host.docker.internal:8790/health");
  });
});

describe("callFortnox", () => {
  beforeEach(() => {
    process.env.FORTNOX_API_URL = "http://localhost:9999";
    process.env.FORTNOX_API_TOKEN = "test-token";
  });

  afterEach(() => {
    mock.restoreAll();
    delete process.env.FORTNOX_API_URL;
    delete process.env.FORTNOX_API_TOKEN;
  });

  it("returns jsonResult on success", async () => {
    mock.method(globalThis, "fetch", () =>
      Promise.resolve(mockResponse('{"status":"ok"}')),
    );

    const result = await callFortnox("GET", "/health");

    assert.deepEqual(result, jsonResult({ status: "ok" }));
  });

  it("returns errorResult on failure", async () => {
    mock.method(globalThis, "fetch", () =>
      Promise.resolve(mockResponse('{"error":"bad"}', 400)),
    );

    const result = await callFortnox("POST", "/auth/start", {}, "Auth failed");
    const text = (result.content[0] as { text: string }).text;

    assert.ok(text.startsWith("Error: Auth failed"));
    assert.ok(text.includes('"error": "bad"'));
  });

  it("uses default error label when none provided", async () => {
    mock.method(globalThis, "fetch", () =>
      Promise.resolve(mockResponse('{"error":"oops"}', 500)),
    );

    const result = await callFortnox("GET", "/health");
    const text = (result.content[0] as { text: string }).text;

    assert.ok(text.startsWith("Error: Request failed"));
  });
});

describe("result helpers", () => {
  it("textResult wraps text in content array", () => {
    const r = textResult("hello");
    assert.deepEqual(r, { content: [{ type: "text", text: "hello" }] });
  });

  it("jsonResult pretty-prints data", () => {
    const r = jsonResult({ a: 1 });
    const text = (r.content[0] as { text: string }).text;
    assert.equal(text, '{\n  "a": 1\n}');
  });

  it("errorResult formats with detail", () => {
    const r = errorResult("bad", { code: 42 });
    const text = (r.content[0] as { text: string }).text;
    assert.ok(text.startsWith("Error: bad"));
    assert.ok(text.includes('"code": 42'));
  });

  it("errorResult formats without detail", () => {
    const r = errorResult("bad");
    assert.deepEqual(r, { content: [{ type: "text", text: "Error: bad" }] });
  });
});
