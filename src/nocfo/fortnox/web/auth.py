"""BankID authentication flow for Fortnox via visible Chrome window.

Supports two modes:
1. Legacy blocking login (bankid_login) — QR only visible in local Chrome
2. QR streaming login (bankid_login_with_qr_capture) — streams QR via SSE for remote auth
"""

import time

import structlog
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

from nocfo.fortnox.web import selectors
from nocfo.fortnox.web.evidence import EvidenceCapture

logger = structlog.get_logger()

FORTNOX_LOGIN_URL = "https://id.fortnox.se"
TENANT_SELECT_URL = "https://apps.fortnox.se/login-fortnox-id/tenant-select"
FORTNOX_APP_DOMAIN = "apps2.fortnox.se"
LOGIN_TIMEOUT = 120  # seconds to wait for BankID scan
POLL_INTERVAL = 2  # seconds between auth status checks
QR_POLL_INTERVAL = 0.8  # seconds between QR captures

# QR capture selectors for id.fortnox.se
_FORTNOX_QR_SELECTORS = [
    "img[alt*='QR']",
    "canvas",
    "[class*='qr'] img",
    "img[src^='data:image']",
]
_cached_qr_selector = None


def bankid_login(page: Page) -> dict:
    """Execute BankID login flow in a visible Chrome window.

    Flow: id.fortnox.se (BankID) -> tenant-select -> apps2.fortnox.se/app/{tenant}/...

    Returns:
        {"status": "authenticated", "url": ...} or {"status": "timeout"} or {"status": "error", ...}
    """
    logger.info("bankid_login_start")
    evidence = EvidenceCapture("auth")

    try:
        # Navigate to Fortnox login
        page.goto(FORTNOX_LOGIN_URL, wait_until="networkidle", timeout=20000)
        evidence.capture(page, "page_loaded")

        # Click BankID tab/button
        try:
            selectors.click(page, "login.bankid_tab", timeout=10000)
            logger.info("bankid_tab_clicked")
            evidence.capture(page, "bankid_tab_clicked")
        except PlaywrightTimeout:
            logger.warning("bankid_tab_not_found", msg="May already be on BankID page")
            evidence.capture(page, "bankid_tab_not_found")

        # Click "BankID med QR-kod" to show QR (Fortnox shows device/QR choice)
        _click_qr_mode(page)

        # Wait for QR to appear on screen (in the Chrome window)
        try:
            selectors.wait_for(page, "login.qr_image", timeout=15000)
            logger.info("bankid_qr_visible", msg="QR code visible in Chrome window")
            evidence.capture(page, "qr_visible")
        except PlaywrightTimeout:
            logger.warning("bankid_qr_not_detected", msg="QR selector not found, proceeding")
            evidence.capture(page, "qr_not_detected")

        # Wait for authentication — poll for redirect to tenant-select or app
        start = time.time()
        while time.time() - start < LOGIN_TIMEOUT:
            if _is_logged_in(page):
                logger.info("bankid_login_success", url=page.url)
                evidence.capture(page, "login_success")
                return {"status": "authenticated", "url": page.url}

            time.sleep(POLL_INTERVAL)

        logger.warning("bankid_login_timeout", elapsed=LOGIN_TIMEOUT)
        evidence.capture(page, "login_timeout")
        return {"status": "timeout", "message": f"BankID login timed out after {LOGIN_TIMEOUT}s"}

    except Exception as e:
        logger.error("bankid_login_error", error=str(e))
        evidence.capture(page, "login_error")
        return {"status": "error", "message": str(e)}


def bankid_login_with_qr_capture(page: Page, operation_id: str, funnel_base: str) -> bool:
    """BankID login flow with QR streaming for remote auth.

    Captures QR data and writes it to the operation dict for SSE streaming.
    Returns True if authenticated, False on timeout/failure.
    """
    from nocfo.browser.operations_state import update_operation, add_qr_url
    from nocfo.browser.tokens import generate_token

    logger.info("bankid_login_qr_start", operation_id=operation_id)
    update_operation(operation_id, status="waiting_for_qr")

    try:
        # Set up response interceptor for autoStartToken
        _setup_bankid_intercept(page, operation_id)

        # Navigate to Fortnox login
        page.goto(FORTNOX_LOGIN_URL, wait_until="networkidle", timeout=20000)

        # Click "BankID med QR-kod" to get QR mode (Fortnox defaults to same-device)
        _click_qr_mode(page)

        time.sleep(1)

        # Generate one-time token and QR URL
        token = generate_token(operation_id, context={"action": "login"})
        qr_url = f"{funnel_base}/auth/live?token={token}"
        add_qr_url(operation_id, qr_url)
        logger.info("qr_url_generated", qr_url=qr_url)

        # Poll loop: capture QR and check for login completion
        deadline = time.time() + LOGIN_TIMEOUT
        while time.time() < deadline:
            # Capture QR data (fast JS eval)
            qr = capture_fortnox_qr(page)
            if qr:
                from nocfo.browser.operations_state import _operations, _operations_lock
                with _operations_lock:
                    if operation_id in _operations:
                        _operations[operation_id]["_qr_data"] = qr

            # Check if login completed
            if _is_logged_in(page):
                logger.info("bankid_login_qr_success", url=page.url)
                update_operation(operation_id, status="authenticated")
                return True

            time.sleep(QR_POLL_INTERVAL)

        logger.warning("bankid_login_qr_timeout", elapsed=LOGIN_TIMEOUT)
        update_operation(operation_id, status="failed", error="BankID login timed out")
        return False

    except Exception as e:
        logger.error("bankid_login_qr_error", error=str(e))
        update_operation(operation_id, status="failed", error=str(e))
        return False


def capture_fortnox_qr(page: Page) -> str | None:
    """Extract QR base64 from id.fortnox.se. Fast JS eval path.

    Returns base64 string (without data URI prefix) or None.
    """
    global _cached_qr_selector

    # Fast path: use cached selector
    if _cached_qr_selector:
        try:
            src = page.evaluate(
                "(sel) => { const el = document.querySelector(sel); "
                "return el && el.offsetWidth > 0 ? "
                "(el.tagName === 'CANVAS' ? el.toDataURL('image/png') : el.src) : null; }",
                _cached_qr_selector,
            )
            if src:
                return _extract_base64(src)
        except Exception:
            _cached_qr_selector = None

    # Discovery path: find working selector
    for sel in _FORTNOX_QR_SELECTORS:
        try:
            src = page.evaluate(
                "(sel) => { const el = document.querySelector(sel); "
                "return el && el.offsetWidth > 0 ? "
                "(el.tagName === 'CANVAS' ? el.toDataURL('image/png') : el.src) : null; }",
                sel,
            )
            if src:
                _cached_qr_selector = sel
                return _extract_base64(src)
        except Exception:
            continue

    return None


def _extract_base64(src: str) -> str | None:
    """Extract base64 data from a data URI."""
    if not src:
        return None
    if src.startswith("data:image/png;base64,"):
        return src[len("data:image/png;base64,"):]
    if src.startswith("data:image"):
        try:
            return src[src.index(",") + 1:]
        except ValueError:
            return None
    return None


def _setup_bankid_intercept(page: Page, operation_id: str) -> None:
    """Response listener for autoStartToken from id.fortnox.se API."""

    def on_response(response):
        try:
            url = response.url
            if "id.fortnox.se" not in url:
                return
            ct = response.headers.get("content-type", "")
            if "json" not in ct and "javascript" not in ct:
                return
            try:
                body = response.json()
            except Exception:
                return
            if not isinstance(body, dict):
                return

            token = _find_autostart_token(body)
            if token:
                uri = f"bankid:///?autostarttoken={token}&redirect=null"
                logger.info("bankid_autostart_captured", url=url)
                from nocfo.browser.operations_state import _operations, _operations_lock
                with _operations_lock:
                    if operation_id in _operations:
                        _operations[operation_id]["_bankid_uri"] = uri
        except Exception:
            pass

    page.on("response", on_response)


def _find_autostart_token(obj, depth: int = 0) -> str | None:
    """Recursively search a dict/list for an autoStartToken value."""
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key.lower() in ("autostarttoken", "auto_start_token") and isinstance(val, str) and len(val) > 10:
                return val
            found = _find_autostart_token(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_autostart_token(item, depth + 1)
            if found:
                return found
    return None


def _click_qr_mode(page: Page) -> None:
    """Click 'BankID med QR-kod' button to switch from same-device to QR mode.

    Fortnox defaults to 'BankID på denna enhet' which tries to open BankID
    on the same machine. For remote auth we need QR mode.
    """
    try:
        selectors.click(page, "login.bankid_qr_button", timeout=5000)
        logger.info("bankid_qr_mode_clicked")
        page.wait_for_timeout(2000)
    except PlaywrightTimeout:
        # May already be showing QR, or different page layout
        logger.warning("bankid_qr_button_not_found", msg="May already be in QR mode")


def _is_logged_in(page: Page) -> bool:
    """Check if the page indicates successful login.

    Detects: tenant-select page, or the apps2 app itself.
    """
    url = page.url

    # Landed on tenant select or the app
    if "tenant-select" in url:
        return True
    if FORTNOX_APP_DOMAIN in url:
        return True

    # Check for session cookies
    try:
        cookies = page.context.cookies()
        cookie_names = {c["name"] for c in cookies}
        if any("fortnox" in n.lower() for n in cookie_names):
            # Has Fortnox cookies and not on login page
            if "id.fortnox.se" not in url or "/account" in url:
                return True
    except Exception:
        pass

    return False
