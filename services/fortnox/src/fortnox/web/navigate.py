"""Common navigation helpers for Fortnox SPA.

Fortnox architecture:
  - Outer shell: apps2.fortnox.se/app/{tenant}/... — header, navigation, drawers
  - Inner iframe "iframeApp": apps2.fortnox.se/webapp-ui/{tenant}?container#... — all legacy UI content
  - Settings items, accounting views, etc. are all inside the iframe
"""

import structlog
from playwright.sync_api import Frame, Page, TimeoutError as PlaywrightTimeout

logger = structlog.get_logger()

TENANT_SELECT_URL = "https://apps.fortnox.se/login-fortnox-id/tenant-select"
APP_DOMAIN = "apps2.fortnox.se"
IFRAME_NAME = "iframeApp"

# Default tenant — Simon Hällqvist Invest AB (ID: 1)
DEFAULT_TENANT_SELECTOR = "#tenant-option-1803884-1"


def ensure_app(page: Page, tenant_selector: str = DEFAULT_TENANT_SELECTOR) -> bool:
    """Ensure we're on the apps2 Fortnox app. Navigate via tenant-select if needed.

    Returns True if on the app, False if unable to get there.
    """
    if APP_DOMAIN in page.url:
        return True

    try:
        page.goto(TENANT_SELECT_URL, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        if APP_DOMAIN in page.url:
            return True  # Already redirected (session remembered tenant)

        # Click the tenant
        el = page.wait_for_selector(tenant_selector, timeout=10000)
        if el:
            el.click()
            page.wait_for_timeout(5000)
            return APP_DOMAIN in page.url
    except Exception as e:
        logger.error("ensure_app_failed", error=str(e))

    return False


def go_home(page: Page) -> None:
    """Navigate to the lobby via the Fortnox logo."""
    try:
        logo = page.wait_for_selector("a.Header__smallerLogo__mfhNp, a[href*='/common/lobby']", timeout=3000)
        if logo:
            logo.click()
            page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        pass


def open_settings_dropdown(page: Page) -> bool:
    """Open the gear/settings dropdown in the header."""
    try:
        btn = page.wait_for_selector(
            ".MenuDropdown__headerDropdownContainer__XLb41.settings .MenuDropdown__dropdownBtn__GzZT7",
            timeout=5000,
        )
        if btn:
            btn.click()
            page.wait_for_timeout(1000)
            return True
    except PlaywrightTimeout:
        pass
    return False


def navigate_via_dropdown(page: Page, item_text: str) -> bool:
    """Open settings dropdown and click a menu item (e.g. 'Bokföring', 'Transaktioner')."""
    if not open_settings_dropdown(page):
        return False
    try:
        item = page.wait_for_selector(
            f"a.DropDownItem__dropDownItem__lwKdB:has-text('{item_text}')",
            timeout=5000,
        )
        if item:
            item.click()
            page.wait_for_timeout(3000)
            return True
    except PlaywrightTimeout:
        pass
    return False


def navigate_to_settings_page(page: Page) -> bool:
    """Navigate to the Inställningar (settings) page."""
    if "/common/settings" in page.url:
        _dismiss_unsaved_changes_dialog(page)
        return True

    # Navigate via URL pattern
    if APP_DOMAIN in page.url:
        base = page.url.split("/app/")[0] + "/app/" + page.url.split("/app/")[1].split("/")[0]
        page.goto(f"{base}/common/settings", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(3000)
        _dismiss_unsaved_changes_dialog(page)
        return "/common/settings" in page.url

    return False


def _dismiss_unsaved_changes_dialog(page: Page) -> None:
    """Dismiss the 'Spara ändringar' dialog if it appears.

    Fortnox shows this modal when navigating away from a page with unsaved
    changes: "Du har osparade ändringar i vyn, vill du spara?" with Nej/Ja.
    """
    iframe = page.frame(IFRAME_NAME)
    target = iframe if iframe else page

    try:
        nej_btn = target.wait_for_selector(
            "button:has-text('Nej')",
            timeout=2000,
        )
        if nej_btn and nej_btn.is_visible():
            nej_btn.click()
            page.wait_for_timeout(500)
            logger.info("dismissed_unsaved_changes_dialog")
    except PlaywrightTimeout:
        pass  # No dialog


def get_app_iframe(page: Page) -> Frame | None:
    """Get the iframeApp frame where Fortnox legacy UI content lives.

    Most Fortnox UI content (settings items, accounting views, etc.)
    is rendered inside this iframe, not in the outer page shell.
    """
    frame = page.frame(IFRAME_NAME)
    if frame:
        return frame
    logger.warning("iframe_not_found", name=IFRAME_NAME)
    return None


def open_settings_item(page: Page, item_text: str) -> Frame | None:
    """Navigate to settings page and expand a settings item (e.g. 'Automatkontering').

    Returns the iframe Frame if successful, None on failure.
    The caller should use the returned frame for further interactions.

    Handles the toggle problem: if the section was already open, clicking
    closes it. We detect this by checking if the expander's parent has visible
    content after clicking, and re-click if needed.
    """
    if not ensure_app(page):
        return None

    if not navigate_to_settings_page(page):
        return None

    iframe = get_app_iframe(page)
    if not iframe:
        return None

    try:
        expander = iframe.wait_for_selector(
            f".form-expander-control:has-text('{item_text}')",
            timeout=10000,
        )
        if not expander or not expander.is_visible():
            return None

        # Scroll the expander into view first
        expander.scroll_into_view_if_needed()
        page.wait_for_timeout(500)

        # Check if the section is already expanded by looking at the parent's height
        height_before = expander.evaluate(
            "e => e.parentElement ? e.parentElement.offsetHeight : 0"
        )

        expander.click()
        page.wait_for_timeout(2000)

        # Check height after click — if it got smaller, we toggled it closed
        height_after = expander.evaluate(
            "e => e.parentElement ? e.parentElement.offsetHeight : 0"
        )

        if height_after < height_before:
            # We closed it — click again to re-open
            logger.info("settings_item_was_open_toggled_back", item=item_text)
            expander.click()
            page.wait_for_timeout(2000)

        return iframe

    except PlaywrightTimeout:
        logger.warning("settings_item_not_found", item=item_text)

    return None
