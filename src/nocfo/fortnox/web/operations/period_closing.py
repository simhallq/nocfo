"""Period closing (Låsa period) via Fortnox browser UI."""

import structlog
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from nocfo.fortnox.web.evidence import EvidenceCapture
from nocfo.fortnox.web.navigate import open_settings_item

logger = structlog.get_logger()


def close_period(page: Page, *, period: str) -> dict:
    """Lock a period in Fortnox.

    Navigation: ensure app → settings → iframe → Låsning av period expander.

    The period locking UI has:
    - Automatlåsning toggle (checkbox)
    - Manuell låsning table with per-user date inputs
    - "input-set-all-dates" field to set the lock date for all users
    - Save button (js-save-periodlocking)

    Args:
        period: Date string like "2025-12-31" for the lock period end date.
    """
    logger.info("period_close_start", period=period)
    evidence = EvidenceCapture("period_closing")

    try:
        iframe = open_settings_item(page, "Låsning av period")
        if not iframe:
            evidence.capture(page, "period_lock_not_found")
            return {"status": "error", "message": "Could not open 'Låsning av period' settings"}

        evidence.capture(page, "period_lock_open")

        # Scroll down to make the period inputs visible
        iframe.evaluate("""() => {
            const expanders = document.querySelectorAll('.form-expander-control');
            for (const exp of expanders) {
                if (exp.textContent.trim() === 'Låsning av period') {
                    exp.scrollIntoView({behavior: 'instant', block: 'start'});
                    break;
                }
            }
        }""")
        page.wait_for_timeout(500)

        # Fill the "set all dates" input to lock the period for all users
        try:
            set_all = iframe.wait_for_selector(
                "input.input-set-all-dates",
                timeout=5000,
            )
            if set_all:
                set_all.fill(period)
                page.wait_for_timeout(500)
                evidence.capture(page, "period_date_filled")
        except PlaywrightTimeout:
            evidence.capture(page, "set_all_dates_not_found")
            return {"status": "error", "message": f"Could not find period date input"}

        # Click save button
        try:
            save_btn = iframe.wait_for_selector(
                "button.js-save-periodlocking",
                timeout=5000,
            )
            if save_btn:
                save_btn.click()
                page.wait_for_timeout(2000)
                evidence.capture(page, "saved")
        except PlaywrightTimeout:
            evidence.capture(page, "save_button_not_found")
            return {"status": "error", "message": "Could not find save button"}

        # Check for confirmation dialog
        try:
            confirm = iframe.wait_for_selector(
                "button:has-text('Bekräfta'), button:has-text('OK'), button:has-text('Ja')",
                timeout=3000,
            )
            if confirm:
                confirm.click()
                page.wait_for_timeout(1000)
        except PlaywrightTimeout:
            pass  # No confirmation dialog

        logger.info("period_close_success", period=period)
        evidence.capture(page, "success")
        return {"status": "ok", "period": period, "message": f"Period locked up to {period}"}

    except Exception as e:
        logger.error("period_close_error", error=str(e))
        evidence.capture(page, "error")
        return {"status": "error", "message": str(e)}
