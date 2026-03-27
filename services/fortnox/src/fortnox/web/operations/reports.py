"""Report downloads via Fortnox browser UI.

Strategy: Fortnox reports are legacy PHP modals served in the iframe.
We discovered the API endpoints:
- GET /api/common/reports — report catalog with codes (balance, result, etc.)
- GET /api/reports/reports-v1 — report URLs like /kf/modal/modal_print.php?t=balance&

The approach:
1. Fetch report catalog from the API
2. Navigate the iframe to the report modal URL
3. Fill period parameters and trigger print/download
"""

import base64
import json
from pathlib import Path

import structlog
from playwright.sync_api import Page, Response, TimeoutError as PlaywrightTimeout

from fortnox.web.evidence import EvidenceCapture
from fortnox.web.navigate import APP_DOMAIN, ensure_app, get_app_iframe

logger = structlog.get_logger()

# Map friendly names to Fortnox report codes
REPORT_CODE_MAP = {
    "balansrapport": "balance",
    "resultatrapport": "result",
    "balance": "balance",
    "income": "result",
    "result": "result",
    "huvudbok": "gledger",
    "gledger": "gledger",
    "momsrapport": "vat",
    "vat": "vat",
    "kontoanalys": "acctanalysis",
    "acctanalysis": "acctanalysis",
    "ib": "ib",
    "deleted_vouchers": "deleted_vouchers",
    "liquidity": "liquidity",
    "accrual_list": "accrual_list",
    "quarterly": "quarterly",
    "budget": "budget",
    "resulthas": "resulthas",
    "result12": "result12",
    "systemdocumentation": "systemdocumentation",
}


def discover_report_api(page: Page) -> dict:
    """Discover available reports by calling Fortnox internal API.

    Returns the report catalog from /api/common/reports and /api/reports/reports-v1.
    """
    logger.info("discover_report_api_start")

    if not ensure_app(page):
        return {"status": "error", "message": "Could not navigate to Fortnox app"}

    # Make sure we're on apps2.fortnox.se before fetching
    current_url = page.url
    if APP_DOMAIN not in current_url:
        return {"status": "error", "message": f"Not on Fortnox app domain. Current URL: {current_url}"}

    # Navigate to lobby to get a clean context for API calls
    tenant_id = _extract_tenant_id(current_url)
    if tenant_id and "/common/lobby" not in current_url:
        page.goto(
            f"https://apps2.fortnox.se/app/{tenant_id}/common/lobby",
            wait_until="domcontentloaded",
            timeout=20000,
        )
        page.wait_for_timeout(3000)

    logger.info("discover_page_url", url=page.url)

    # Intercept the SPA's own API calls during lobby load
    # (CSP blocks injected fetch/XHR in Fortnox pages)
    api_data = _fetch_api_via_intercept(page, [
        "/api/common/reports",
        "/api/reports/reports-v1",
    ])

    common_reports = api_data.get("/api/common/reports")
    reports_v1 = api_data.get("/api/reports/reports-v1")

    if common_reports is None and reports_v1 is None:
        return {
            "status": "error",
            "message": "Could not capture report API data during page load",
            "captured_urls": list(api_data.keys()),
        }

    catalog = {"common": common_reports, "reports": reports_v1}

    if not catalog or catalog.get("error"):
        return {"status": "error", "message": catalog.get("error", "Failed to fetch report catalog")}

    # Extract useful info from the catalog
    common_reports = catalog.get("common", {})
    reports_v1 = catalog.get("reports") or []

    # Build a clean report list
    available = []
    for report in reports_v1:
        available.append({
            "code": report.get("code"),
            "module": report.get("module"),
            "url": report.get("url"),
            "legacy": report.get("legacy"),
        })

    # Also extract categorized reports from /api/common/reports
    categories = {}
    if isinstance(common_reports, dict) and "result" in common_reports:
        for category, reports in common_reports["result"].items():
            if isinstance(reports, list):
                categories[category] = [
                    {"text": r.get("text"), "code": r.get("code")}
                    for r in reports
                ]

    return {
        "status": "ok",
        "categories": categories,
        "reports": available,
        "total": len(available),
    }


def download_report(page: Page, *, report_type: str, period: str) -> dict:
    """Download a financial report from Fortnox.

    Opens the legacy PHP report modal in the iframe, sets period parameters,
    and triggers the print/download.

    Args:
        report_type: Report code (e.g., 'balance', 'result', 'vat') or friendly name.
        period: Period string like '2026-01' or '2026-01-01'.
    """
    report_code = REPORT_CODE_MAP.get(report_type.lower(), report_type.lower())
    logger.info("report_download_start", report_code=report_code, period=period, current_url=page.url)
    evidence = EvidenceCapture("reports")

    try:
        if not ensure_app(page):
            evidence.capture(page, "not_in_app")
            return {"status": "error", "message": f"Could not navigate to Fortnox app (was on: {page.url})"}

        evidence.capture(page, "app_ready")

        # Get the report URL from the API
        report_url = _get_report_url(page, report_code)
        if not report_url:
            return {
                "status": "error",
                "message": f"Unknown report code: {report_code}. Use POST /reports/discover to see available reports.",
            }

        logger.info("report_url_found", code=report_code, url=report_url, legacy=report_url.get("legacy"))

        if report_url.get("legacy"):
            return _download_legacy_report(page, report_code, report_url["url"], period, evidence)
        else:
            return _download_new_report(page, report_code, report_url["url"], period, evidence)

    except Exception as e:
        logger.error("report_download_error", error=str(e))
        evidence.capture(page, "error")
        return {"status": "error", "message": str(e)}


def _get_report_url(page: Page, report_code: str) -> dict | None:
    """Fetch the report URL from the Fortnox API."""
    api_data = _fetch_api_via_intercept(page, ["/api/reports/reports-v1"])
    reports = api_data.get("/api/reports/reports-v1")
    if not reports or not isinstance(reports, list):
        return None
    for r in reports:
        if r.get("code") == report_code:
            return {"url": r.get("url"), "legacy": r.get("legacy"), "code": r.get("code")}
    return None


def _download_legacy_report(
    page: Page,
    report_code: str,
    modal_url: str,
    period: str,
    evidence: EvidenceCapture,
) -> dict:
    """Download a legacy PHP report by navigating directly to the modal URL.

    Legacy reports use URLs like /kf/modal/modal_print.php?t=balance&
    These are PHP pages that render a form with period inputs and a print button.
    We navigate the main page directly to the modal URL.
    """
    # Build the full modal URL
    full_url = f"https://apps2.fortnox.se{modal_url}"
    logger.info("opening_legacy_report", url=full_url, code=report_code)

    # Navigate directly to the modal URL
    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(3000)
    evidence.capture(page, "modal_page_loaded")

    # Check what we got — capture the page content for debugging
    page_info = page.evaluate("""() => ({
        title: document.title,
        url: location.href,
        forms: document.forms.length,
        inputs: Array.from(document.querySelectorAll('input')).map(i => ({
            name: i.name, type: i.type, id: i.id, value: i.value
        })),
        buttons: Array.from(document.querySelectorAll('button, input[type="submit"]')).map(b => ({
            text: b.textContent?.trim() || b.value, type: b.type, class: b.className, id: b.id
        })),
        selects: Array.from(document.querySelectorAll('select')).map(s => ({
            name: s.name, id: s.id,
            options: Array.from(s.options).map(o => ({ text: o.text, value: o.value }))
        })),
        bodyText: document.body?.innerText?.substring(0, 1000) || '',
    })""")

    logger.info("modal_page_info", title=page_info.get("title"), forms=page_info.get("forms"))
    evidence.capture(page, "modal_analyzed")

    # Try to fill period fields
    _fill_report_period(page, period, page)
    evidence.capture(page, "period_filled")

    # Try to trigger print/download
    return _trigger_report_download(page, page, report_code, period, evidence, page_info)


def _download_new_report(
    page: Page,
    report_code: str,
    report_url: str,
    period: str,
    evidence: EvidenceCapture,
) -> dict:
    """Download a new-style report by navigating to its URL."""
    tenant_id = _extract_tenant_id(page.url)
    if not tenant_id:
        return {"status": "error", "message": "Could not determine tenant ID"}

    full_url = f"https://apps2.fortnox.se/app/{tenant_id}{report_url}"
    page.goto(full_url, wait_until="domcontentloaded", timeout=20000)
    page.wait_for_timeout(5000)
    evidence.capture(page, "new_report_loaded")

    return {
        "status": "ok",
        "message": f"Navigated to new-style report at {report_url}",
        "report_code": report_code,
        "note": "New-style reports may need additional interaction — check evidence screenshots.",
    }


def _fill_report_period(target, period: str, page: Page) -> None:
    """Fill period/date inputs in the report modal."""
    # Common input patterns in Fortnox report modals
    selectors = [
        "input[name*='period']",
        "input[name*='from']",
        "input[name*='date']",
        "select[name*='period']",
        "input.js-period",
        "input.period",
        "#period",
        "#fromDate",
    ]

    for selector in selectors:
        try:
            el = target.wait_for_selector(selector, timeout=2000)
            if el and el.is_visible():
                el.fill(period)
                logger.info("period_input_filled", selector=selector, period=period)
                page.wait_for_timeout(500)
                return
        except PlaywrightTimeout:
            continue

    logger.warning("no_period_input_found")


def _trigger_report_download(
    target,
    page: Page,
    report_code: str,
    period: str,
    evidence: EvidenceCapture,
    page_info: dict | None = None,
) -> dict:
    """Try to trigger the report download/print."""
    # Look for print/download buttons
    button_selectors = [
        "button:has-text('Skriv ut')",
        "button:has-text('Skapa')",
        "button:has-text('Visa')",
        "button:has-text('OK')",
        "input[type='submit']",
        "button.js-print",
        "button.print",
        "#printButton",
        "a:has-text('PDF')",
        "a:has-text('Skriv ut')",
    ]

    for selector in button_selectors:
        try:
            btn = target.wait_for_selector(selector, timeout=2000)
            if btn and btn.is_visible():
                logger.info("clicking_report_button", selector=selector)

                # Try to capture the download
                try:
                    with page.expect_download(timeout=15000) as download_info:
                        btn.click()

                    download = download_info.value
                    download_path = Path(download.path())
                    file_bytes = download_path.read_bytes()
                    filename = download.suggested_filename or f"{report_code}_{period}.pdf"

                    content_type = "application/pdf"
                    if filename.endswith(".xlsx"):
                        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    elif filename.endswith(".csv"):
                        content_type = "text/csv"

                    logger.info("report_download_success", filename=filename, size=len(file_bytes))
                    evidence.capture(page, "download_complete")
                    return {
                        "status": "ok",
                        "file_data": base64.b64encode(file_bytes).decode("ascii"),
                        "content_type": content_type,
                        "filename": filename,
                    }
                except PlaywrightTimeout:
                    # Download didn't start — the button might open a preview instead
                    btn.click()
                    page.wait_for_timeout(3000)
                    evidence.capture(page, "button_clicked_no_download")
                    logger.info("button_clicked_no_download", selector=selector)
                    break

        except PlaywrightTimeout:
            continue

    # If no download was triggered, capture what we see and return
    evidence.capture(page, "no_download_triggered")

    return {
        "status": "partial",
        "message": "Report modal opened but download not triggered automatically.",
        "report_code": report_code,
        "period": period,
        "page_info": page_info,
        "hint": "Check evidence screenshots in data/screenshots/ for the current state.",
    }


def _fetch_api_via_intercept(page: Page, api_urls: list[str]) -> dict[str, any]:
    """Fetch Fortnox API data by intercepting SPA API calls during page load.

    CSP blocks injected fetch/XHR. Instead, we intercept the API responses
    that the SPA makes naturally when loading a page.

    Args:
        page: Playwright page on apps2.fortnox.se
        api_urls: List of API URL substrings to match (e.g., "/api/common/reports")

    Returns:
        Dict mapping URL substrings to their parsed JSON responses.
    """
    captured: dict[str, any] = {}

    def on_response(response: Response) -> None:
        url = response.url
        for api_url in api_urls:
            if api_url in url and api_url not in captured:
                try:
                    captured[api_url] = response.json()
                except Exception:
                    pass

    page.on("response", on_response)
    try:
        # Navigate to lobby — the SPA will make API calls including our targets
        tenant_id = _extract_tenant_id(page.url)
        if tenant_id:
            page.goto(
                f"https://apps2.fortnox.se/app/{tenant_id}/common/lobby",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            page.wait_for_timeout(5000)
    finally:
        page.remove_listener("response", on_response)

    return captured


def _extract_tenant_id(url: str) -> str | None:
    """Extract tenant ID from Fortnox app URL."""
    if "/app/" in url:
        parts = url.split("/app/")[1].split("/")
        if parts:
            return parts[0]
    return None
