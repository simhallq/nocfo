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
LOGIN_TIMEOUT = 300  # seconds to wait for BankID scan (allows ~10 QR retry cycles)
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

# JS snippet that extracts QR data from any element type (img, canvas, or SVG)
_QR_EXTRACT_JS = """(sel) => {
    const el = document.querySelector(sel);
    if (!el || el.offsetWidth < 50) return null;
    const tag = el.tagName.toUpperCase();
    if (tag === 'CANVAS') return el.toDataURL('image/png');
    if (tag === 'IMG') return el.src || null;
    if (tag === 'svg' || tag === 'SVG') {
        const serializer = new XMLSerializer();
        const svgStr = serializer.serializeToString(el);
        return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
    }
    return null;
}"""


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


def bankid_login_with_qr_capture(page: Page, operation_id: str) -> bool:
    """BankID login flow with QR streaming for remote auth.

    Captures QR data and writes it to the operation dict for SSE streaming.
    Token/URL generation is handled by the caller (handle_auth_start).
    Returns True if authenticated, False on timeout/failure.
    """
    from nocfo.browser.operations_state import update_operation

    from nocfo.browser.operations_state import get_operation_internal

    logger.info("bankid_login_qr_start", operation_id=operation_id)
    update_operation(operation_id, status="waiting_for_qr")

    op_internal = get_operation_internal(operation_id)
    stop_event = op_internal["stop_event"] if op_internal else None

    try:
        # Set up response interceptor for autoStartToken
        _setup_bankid_intercept(page, operation_id)

        # Navigate to Fortnox login
        page.goto(FORTNOX_LOGIN_URL, wait_until="networkidle", timeout=20000)

        # Click BankID tab first — this shows "BankID på denna enhet" (same-device)
        # which contains the bankid:// URI we need for mobile deep linking
        try:
            selectors.click(page, "login.bankid_tab", timeout=10000)
            logger.info("bankid_tab_clicked")
        except PlaywrightTimeout:
            logger.warning("bankid_tab_not_found", msg="May already be on BankID page")

        # Wait for BankID page to load after clicking tab
        time.sleep(2)

        # Check if QR is already visible (new Fortnox flow goes directly to QR)
        qr_already_visible = capture_fortnox_qr(page) is not None
        logger.info("bankid_post_tab_state", url=page.url[:80], qr_visible=qr_already_visible)

        if not qr_already_visible:
            # Try to capture bankid:// URI from same-device view
            uri = _extract_bankid_uri(page)
            if uri:
                update_operation(operation_id, _bankid_uri=uri)
                logger.info("bankid_uri_captured_before_qr", uri=uri[:50])

            # Switch to QR mode (old Fortnox flow had a separate step)
            _click_qr_mode(page)
            time.sleep(1)
        else:
            # QR already showing — also try to capture bankid:// URI
            uri = _extract_bankid_uri(page)
            if uri:
                update_operation(operation_id, _bankid_uri=uri)
                logger.info("bankid_uri_captured", uri=uri[:50])

        # Poll loop: capture QR, detect stale QR, and check for login completion
        deadline = time.time() + LOGIN_TIMEOUT
        last_qr = None
        stale_since: float | None = None
        QR_STALE_THRESHOLD = 15  # seconds before retrying

        qr_lost_since: float | None = None
        QR_LOST_THRESHOLD = 5  # seconds without QR before attempting restart

        while time.time() < deadline and not (stop_event and stop_event.is_set()):
            # Check if login completed (before QR capture for fast detection)
            if _is_logged_in(page):
                logger.info("bankid_login_qr_success", url=page.url)
                update_operation(operation_id, status="authenticated")
                return True

            # Capture QR data (fast JS eval)
            qr = capture_fortnox_qr(page)
            if qr:
                update_operation(operation_id, _qr_data=qr)
                qr_lost_since = None

                # Track stale QR for retry logic
                if qr != last_qr:
                    last_qr = qr
                    stale_since = None
                elif stale_since is None:
                    stale_since = time.time()
                elif time.time() - stale_since > QR_STALE_THRESHOLD:
                    logger.info("bankid_qr_stale", seconds=QR_STALE_THRESHOLD)
                    if _click_retry_button(page):
                        stale_since = None
                        last_qr = None
                        time.sleep(2)
                        continue
            elif last_qr is not None:
                # QR was visible but disappeared — BankID session likely expired
                if qr_lost_since is None:
                    qr_lost_since = time.time()
                elif time.time() - qr_lost_since > QR_LOST_THRESHOLD:
                    logger.info("bankid_qr_lost", msg="QR disappeared, restarting flow")
                    if _restart_bankid_flow(page):
                        stale_since = None
                        last_qr = None
                        qr_lost_since = None
                        time.sleep(2)
                        continue

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

    Supports img, canvas, and SVG QR codes.
    Returns base64 string (without data URI prefix) or None.
    """
    global _cached_qr_selector

    # Fast path: use cached selector
    if _cached_qr_selector:
        try:
            src = page.evaluate(_QR_EXTRACT_JS, _cached_qr_selector)
            if src:
                return _extract_base64(src)
        except Exception:
            _cached_qr_selector = None

    # Discovery path: try known selectors
    for sel in _FORTNOX_QR_SELECTORS:
        try:
            src = page.evaluate(_QR_EXTRACT_JS, sel)
            if src:
                _cached_qr_selector = sel
                return _extract_base64(src)
        except Exception:
            continue

    # SVG discovery: find large SVG with many rects (QR pattern)
    try:
        result = page.evaluate("""() => {
            for (const svg of document.querySelectorAll('svg')) {
                const r = svg.getBoundingClientRect();
                if (r.width > 100 && r.height > 100 && svg.querySelectorAll('rect,path').length > 20) {
                    const svgStr = new XMLSerializer().serializeToString(svg);
                    return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
                }
            }
            return null;
        }""")
        if result:
            return _extract_base64(result)
    except Exception:
        pass

    return None


def _extract_base64(src: str) -> str | None:
    """Extract base64 data from a data URI (PNG, SVG, or other image formats)."""
    if not src:
        return None
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

            logger.debug("bankid_intercept_response", url=url, keys=list(body.keys())[:10])
            token = _find_autostart_token(body)
            if token:
                uri = f"bankid:///?autostarttoken={token}&redirect=null"
                logger.info("bankid_autostart_captured", url=url)
                from nocfo.browser.operations_state import update_operation
                update_operation(operation_id, _bankid_uri=uri)
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

    Fortnox may show QR directly after clicking BankID (no separate step),
    so this uses a short timeout to fail fast when not needed.
    """
    try:
        selectors.click(page, "login.bankid_qr_button", timeout=2000)
        logger.info("bankid_qr_mode_clicked")
        page.wait_for_timeout(1000)
    except PlaywrightTimeout:
        # Fortnox now often shows QR directly — this is expected
        logger.debug("bankid_qr_button_not_found", msg="QR likely already visible")


def _extract_bankid_uri(page: Page) -> str | None:
    """Try to extract bankid:// URI from the Fortnox login page via JS eval.

    Checks DOM links, iframes, meta redirects, and the page's JS state.
    Works best when called BEFORE switching to QR mode, while the
    'BankID på denna enhet' view is still visible.
    """
    try:
        return page.evaluate("""() => {
            // 1. Direct bankid:// links in the DOM
            for (const a of document.querySelectorAll('a[href]')) {
                if (a.href && a.href.indexOf('bankid://') === 0) return a.href;
            }

            // 2. Buttons/links that trigger bankid:// via onclick or data attributes
            const el = document.querySelector('[data-autostarttoken]');
            if (el) return 'bankid:///?autostarttoken=' + el.dataset.autostarttoken + '&redirect=null';

            // 3. Check for bankid:// in any iframe src or link
            for (const iframe of document.querySelectorAll('iframe[src]')) {
                if (iframe.src.indexOf('bankid://') === 0) return iframe.src;
            }

            // 4. Check window.location attempts (Fortnox may try to auto-redirect)
            // Look in all script tags for autoStartToken patterns
            const html = document.documentElement.innerHTML;
            const m = html.match(/autostarttoken=([a-f0-9-]{20,})/i);
            if (m) return 'bankid:///?autostarttoken=' + m[1] + '&redirect=null';

            return null;
        }""")
    except Exception:
        return None


def _restart_bankid_flow(page: Page) -> bool:
    """Restart BankID flow after session expiry.

    Fortnox shows an error page with options to restart via QR or same-device.
    Tries retry button first, then QR mode button, then re-clicks BankID tab.
    """
    if _click_retry_button(page):
        return True
    # Fortnox may show "BankID with QR code" link instead of retry button
    try:
        selectors.click(page, "login.bankid_qr_button", timeout=3000)
        logger.info("bankid_qr_restart_clicked")
        return True
    except PlaywrightTimeout:
        pass
    # Last resort: click BankID tab again
    try:
        selectors.click(page, "login.bankid_tab", timeout=3000)
        logger.info("bankid_tab_restart_clicked")
        return True
    except PlaywrightTimeout:
        pass
    logger.warning("bankid_restart_failed")
    return False


def _click_retry_button(page: Page) -> bool:
    """Click Fortnox's 'Försök igen' button to restart QR flow.

    Returns True if the button was found and clicked.
    """
    try:
        selectors.click(page, "login.bankid_retry_button", timeout=5000)
        logger.info("bankid_retry_button_clicked")
        return True
    except PlaywrightTimeout:
        logger.warning("bankid_retry_button_not_found")
        return False


def _is_logged_in(page: Page) -> bool:
    """Check if the page indicates successful login.

    Detects: tenant-select, apps2, account page, or completion redirect.
    """
    url = page.url

    # Landed on tenant select or the app
    if "tenant-select" in url:
        logger.info("login_detected", trigger="tenant-select", url=url[:80])
        return True
    if FORTNOX_APP_DOMAIN in url:
        logger.info("login_detected", trigger="app-domain", url=url[:80])
        return True

    # Redirected to account page after BankID auth
    if "id.fortnox.se" in url and "/account" in url:
        logger.info("login_detected", trigger="account-page", url=url[:80])
        return True

    # BankID completion redirect
    if "/complete" in url or "/callback" in url:
        logger.info("login_detected", trigger="completion-url", url=url[:80])
        return True

    # No longer on login page (redirected away from BankID flow)
    if "id.fortnox.se" in url and "/fortnoxid-ui-login" not in url:
        logger.info("login_detected", trigger="left-login-page", url=url[:80])
        return True

    return False
