"""Bank reconciliation (Stäm av konto) via Fortnox browser UI."""

from typing import Any

import structlog
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from nocfo.fortnox.web.evidence import EvidenceCapture
from nocfo.fortnox.web.navigate import APP_DOMAIN, ensure_app, get_app_iframe

logger = structlog.get_logger()

# Bokföring section base path
BOKFORING_PATH = "bf/voucherlist"


def run_reconciliation(
    page: Page,
    *,
    account: int,
    matches: list[dict[str, Any]],
) -> dict:
    """Execute bank reconciliation in Fortnox.

    Navigation: ensure app → Bokföring → iframe → Stäm av konto tab.
    """
    logger.info("reconciliation_start", account=account, match_count=len(matches))
    evidence = EvidenceCapture("reconciliation")

    try:
        if not ensure_app(page):
            evidence.capture(page, "not_in_app")
            return {"status": "error", "message": "Could not navigate to Fortnox app"}

        evidence.capture(page, "app_ready")

        # Navigate to Bokföring section
        if BOKFORING_PATH not in page.url:
            _navigate_to_bokforing(page)

        iframe = get_app_iframe(page)
        if not iframe:
            return {"status": "error", "message": "Could not find Fortnox iframe"}

        evidence.capture(page, "bokforing_page")

        # Click "Stäm av konto" tab in the iframe
        try:
            tab = iframe.wait_for_selector(
                "a[data-viewid='voucherreconcile']",
                timeout=10000,
            )
            if tab:
                tab.click()
                page.wait_for_timeout(3000)
                evidence.capture(page, "reconciliation_page")
        except PlaywrightTimeout:
            evidence.capture(page, "reconciliation_tab_not_found")
            return {"status": "error", "message": "Could not find 'Stäm av konto' tab"}

        # Fill account number (input uses id, not name)
        try:
            account_input = iframe.wait_for_selector(
                "#form-voucherreconcile-account",
                timeout=10000,
            )
            if account_input:
                account_input.fill(str(account))
                page.wait_for_timeout(1000)
                evidence.capture(page, "account_filled")
        except PlaywrightTimeout:
            evidence.capture(page, "account_input_not_found")
            return {"status": "error", "message": f"Could not find account input for {account}"}

        # Click search to load transactions
        try:
            # The Sök button might not have a class — try multiple selectors
            search_btn = iframe.query_selector(
                "button.js-voucherreconcile-search"
            ) or iframe.query_selector(
                "button:has-text('Sök'):visible"
            )
            if search_btn:
                search_btn.click()
                page.wait_for_timeout(3000)
                evidence.capture(page, "transactions_loaded")
            else:
                logger.warning("search_button_not_found")
        except Exception as e:
            logger.warning("search_click_failed", error=str(e))

        # Match transactions
        matched = 0
        failed = 0
        for match in matches:
            try:
                _match_transaction(iframe, match)
                matched += 1
            except Exception as e:
                logger.warning("reconciliation_match_failed", match=match, error=str(e))
                failed += 1

        # Click save if any matches were made
        if matched > 0:
            try:
                save_btn = iframe.wait_for_selector(
                    "button.js-save",
                    timeout=10000,
                )
                if save_btn:
                    save_btn.click()
                    page.wait_for_timeout(2000)
                    logger.info("reconciliation_saved", matched=matched)
                    evidence.capture(page, "saved")
            except PlaywrightTimeout:
                evidence.capture(page, "save_button_not_found")
                return {
                    "status": "partial",
                    "message": "Matches selected but save button not found",
                    "matched": matched,
                    "failed": failed,
                }

        result = {
            "status": "ok" if failed == 0 else "partial",
            "matched": matched,
            "failed": failed,
            "total": len(matches),
        }
        logger.info("reconciliation_complete", **result)
        evidence.capture(page, "complete")
        return result

    except Exception as e:
        logger.error("reconciliation_error", error=str(e))
        evidence.capture(page, "error")
        return {"status": "error", "message": str(e)}


def _navigate_to_bokforing(page: Page) -> None:
    """Navigate to Bokföring section via direct URL."""
    if APP_DOMAIN in page.url:
        base = page.url.split("/app/")[0] + "/app/" + page.url.split("/app/")[1].split("/")[0]
        page.goto(f"{base}/{BOKFORING_PATH}", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)


def _match_transaction(iframe, match: dict[str, Any]) -> None:
    """Select a single transaction match in the reconciliation UI."""
    amount_str = str(match.get("amount", ""))

    # Look for a row containing the amount and click its checkbox
    try:
        checkbox = iframe.wait_for_selector(
            f"tr:has-text('{amount_str}') input[type='checkbox']",
            timeout=5000,
        )
        if checkbox:
            checkbox.click()
    except PlaywrightTimeout:
        raise RuntimeError(f"Could not find transaction match for amount {amount_str}")
