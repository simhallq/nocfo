import { describe, it, beforeEach, afterEach, mock } from "node:test";
import assert from "node:assert/strict";
import { fortnoxHealth } from "../src/tools/health.js";
import { fortnoxSessionCheck, fortnoxAuthStart, fortnoxOperationStatus } from "../src/tools/auth.js";
import { fortnoxReceiptAnalyze, fortnoxReceiptBook } from "../src/tools/receipts.js";
import { fortnoxReconciliationRun } from "../src/tools/reconciliation.js";
import { fortnoxPeriodClose } from "../src/tools/period.js";
import { fortnoxReportsDiscover, fortnoxReportsDownload } from "../src/tools/reports.js";
import { fortnoxRulesList, fortnoxRulesSync } from "../src/tools/rules.js";

function mockFetch(body: Record<string, unknown>, status = 200) {
  return mock.method(globalThis, "fetch", () =>
    Promise.resolve(new Response(JSON.stringify(body), { status })),
  );
}

function lastFetchCall(fetchMock: ReturnType<typeof mock.method>) {
  const calls = fetchMock.mock.calls;
  return calls[calls.length - 1].arguments as [string, RequestInit];
}

describe("tool definitions", () => {
  beforeEach(() => {
    process.env.FORTNOX_API_URL = "http://localhost:9999";
    process.env.FORTNOX_API_TOKEN = "tok";
  });

  afterEach(() => {
    mock.restoreAll();
    delete process.env.FORTNOX_API_URL;
    delete process.env.FORTNOX_API_TOKEN;
  });

  it("fortnox_health calls GET /health", async () => {
    const f = mockFetch({ status: "ok" });
    await fortnoxHealth.execute("id1");
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/health");
    assert.equal(opts.method, "GET");
  });

  it("fortnox_session_check calls GET /auth/session/{id}", async () => {
    const f = mockFetch({ has_session: true });
    await fortnoxSessionCheck.execute("id1", { customer_id: "acme" });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/auth/session/acme");
    assert.equal(opts.method, "GET");
  });

  it("fortnox_auth_start calls POST /auth/start", async () => {
    const f = mockFetch({ operation_id: "op1", live_url: "https://example.com" });
    await fortnoxAuthStart.execute("id1", { customer_id: "acme" });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/auth/start");
    assert.equal(opts.method, "POST");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.customer_id, "acme");
    assert.equal(body.force, undefined);
  });

  it("fortnox_auth_start passes force flag", async () => {
    const f = mockFetch({ operation_id: "op1" });
    await fortnoxAuthStart.execute("id1", { customer_id: "acme", force: true });
    const [, opts] = lastFetchCall(f);
    const body = JSON.parse(opts.body as string);
    assert.equal(body.force, true);
  });

  it("fortnox_operation_status calls GET /operation/{id}", async () => {
    const f = mockFetch({ status: "complete" });
    await fortnoxOperationStatus.execute("id1", { operation_id: "op123" });
    const [url] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/operation/op123");
  });

  it("fortnox_receipt_analyze calls POST /receipts/analyze", async () => {
    const f = mockFetch({ confidence: "high", proposed_voucher: {} });
    await fortnoxReceiptAnalyze.execute("id1", {
      customer_id: "acme",
      file_content: "base64data",
      filename: "test.pdf",
    });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/receipts/analyze");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.customer_id, "acme");
    assert.equal(body.file_content, "base64data");
    assert.equal(body.filename, "test.pdf");
  });

  it("fortnox_receipt_book calls POST /receipts/book", async () => {
    const f = mockFetch({ voucher_series: "A", voucher_number: 42 });
    await fortnoxReceiptBook.execute("id1", {
      customer_id: "acme",
      file_content: "base64data",
      filename: "test.pdf",
      voucher: {
        description: "Test",
        voucher_series: "A",
        transaction_date: "2024-01-01",
        rows: [{ account: 6110, debit: "100", credit: "0", transaction_information: "test" }],
      },
    });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/receipts/book");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.voucher.voucher_series, "A");
  });

  it("fortnox_reconciliation_run calls POST /reconciliation/run", async () => {
    const f = mockFetch({ matched: 5 });
    await fortnoxReconciliationRun.execute("id1", { customer_id: "acme", account: "1930" });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/reconciliation/run");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.account, "1930");
  });

  it("fortnox_period_close calls POST /period/close", async () => {
    const f = mockFetch({ locked: true });
    await fortnoxPeriodClose.execute("id1", { customer_id: "acme", period: "2024-02" });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/period/close");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.period, "2024-02");
  });

  it("fortnox_reports_discover calls POST /reports/discover", async () => {
    const f = mockFetch({ reports: [] });
    await fortnoxReportsDiscover.execute("id1", { customer_id: "acme" });
    const [url] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/reports/discover");
  });

  it("fortnox_reports_download calls POST /reports/download", async () => {
    const f = mockFetch({ file_data: "base64" });
    await fortnoxReportsDownload.execute("id1", {
      customer_id: "acme",
      type: "balance_sheet",
      period: "2024-02",
    });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/reports/download");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.type, "balance_sheet");
  });

  it("fortnox_rules_list calls POST /rules/list", async () => {
    const f = mockFetch({ rules: [] });
    await fortnoxRulesList.execute("id1", { customer_id: "acme" });
    const [url] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/rules/list");
  });

  it("fortnox_rules_sync calls POST /rules/sync", async () => {
    const f = mockFetch({ synced: true });
    await fortnoxRulesSync.execute("id1", {
      customer_id: "acme",
      rules: [{ pattern: "Spotify", debit_account: 6210, credit_account: 2440 }],
    });
    const [url, opts] = lastFetchCall(f);
    assert.equal(url, "http://localhost:9999/rules/sync");
    const body = JSON.parse(opts.body as string);
    assert.equal(body.rules[0].pattern, "Spotify");
  });

  it("returns error result on API failure", async () => {
    mockFetch({ error: "session expired" }, 401);
    const result = await fortnoxSessionCheck.execute("id1", { customer_id: "acme" });
    const text = (result.content[0] as { text: string }).text;
    assert.ok(text.startsWith("Error: Session check failed"));
    assert.ok(text.includes("session expired"));
  });
});
