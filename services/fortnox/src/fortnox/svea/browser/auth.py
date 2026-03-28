"""Browser-based BankID authentication for Svea Bank.

Uses Playwright to navigate to auth.svea.com, handle BankID QR display,
and capture the authorization code from the redirect.

The flow:
1. Navigate to auth.svea.com/connect/authorize with PKCE
2. auth.svea.com displays BankID QR
3. User scans QR → BankID completes
4. Redirect to bank.svea.com/sso-login?code=XXX&state=YYY
5. Capture the authorization code from the redirect URL
6. Exchange code for tokens via HTTP (in auth.py)
"""

import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

import structlog
from playwright.sync_api import Browser, Page

from fortnox.svea.api.auth import build_authorize_url

logger = structlog.get_logger()

# Selectors for auth.svea.com BankID page
BANKID_QR_SELECTORS = [
    "img[alt*='QR']",
    "canvas",
    "svg",
    "#qr-code",
    "[class*='qr']",
    "[data-testid*='qr']",
    "img[src*='data:image']",
]

_QR_EXTRACT_JS = """(sel) => {
    const el = document.querySelector(sel);
    if (!el || el.offsetWidth < 50) return null;
    const tag = el.tagName.toUpperCase();
    if (tag === 'CANVAS') return el.toDataURL('image/png');
    if (tag === 'IMG') return el.src || null;
    if (tag === 'SVG') {
        const serializer = new XMLSerializer();
        const svgStr = serializer.serializeToString(el);
        return 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgStr)));
    }
    return null;
}"""


def capture_svea_qr(page: Page) -> str | None:
    """Extract QR code data from the auth.svea.com BankID page."""
    for sel in BANKID_QR_SELECTORS:
        try:
            if page.query_selector(sel):
                data = page.evaluate(_QR_EXTRACT_JS, sel)
                if data and len(str(data)) > 100:
                    return data
        except Exception:
            continue

    # Fallback: find any large image-like element
    try:
        result = page.evaluate("""() => {
            const imgs = document.querySelectorAll('img, canvas, svg');
            for (const el of imgs) {
                if (el.offsetWidth >= 100 && el.offsetHeight >= 100) {
                    if (el.tagName === 'CANVAS') return el.toDataURL('image/png');
                    if (el.tagName === 'IMG' && el.src) return el.src;
                    if (el.tagName === 'svg' || el.tagName === 'SVG') {
                        const s = new XMLSerializer();
                        const str = s.serializeToString(el);
                        var b = btoa(unescape(encodeURIComponent(str)));
                        return 'data:image/svg+xml;base64,' + b;
                    }
                }
            }
            return null;
        }""")
        return result
    except Exception:
        return None


def svea_bankid_login(
    browser: Browser,
    timeout: float = 120.0,
    qr_callback: Callable[[str], None] | None = None,
) -> dict:
    """Run the full Svea BankID login flow via browser.

    Args:
        browser: Playwright Browser instance (connected via CDP).
        timeout: Maximum time to wait for BankID completion.
        qr_callback: Optional callable(qr_data: str) called when QR updates.

    Returns:
        dict with 'code', 'state', 'code_verifier' on success,
        or 'error' on failure.
    """
    # Build authorize URL with PKCE
    authorize_url, state, code_verifier = build_authorize_url()
    logger.info("svea_auth_starting", authorize_url=authorize_url[:80])

    # Create a fresh context for auth (prevents cookie bleed)
    context = browser.new_context()
    page = context.new_page()

    try:
        # Navigate to authorize URL
        page.goto(authorize_url, wait_until="domcontentloaded", timeout=30000)
        logger.info("svea_auth_page_loaded", url=page.url[:80])

        # Wait for BankID page or redirect
        start_time = time.time()
        last_qr = None

        while time.time() - start_time < timeout:
            current_url = page.url

            # Check if we've been redirected to bank.svea.com/sso-login with a code
            if "bank.svea.com/sso-login" in current_url or "code=" in current_url:
                parsed = urlparse(current_url)
                params = parse_qs(parsed.query)
                # Also check fragment for implicit flows
                if not params.get("code"):
                    frag_params = parse_qs(parsed.fragment)
                    params.update(frag_params)

                code = params.get("code", [None])[0]
                returned_state = params.get("state", [None])[0]

                if code:
                    logger.info("svea_auth_code_captured")
                    return {
                        "code": code,
                        "state": returned_state,
                        "code_verifier": code_verifier,
                    }

            # Try to capture QR
            if qr_callback:
                qr_data = capture_svea_qr(page)
                if qr_data and qr_data != last_qr:
                    qr_callback(qr_data)
                    last_qr = qr_data

            time.sleep(0.8)

        logger.warning("svea_auth_timeout")
        return {"error": "timeout", "message": "BankID authentication timed out"}

    except Exception as e:
        logger.error("svea_auth_error", error=str(e))
        return {"error": "exception", "message": str(e)}
    finally:
        page.close()
        context.close()


def svea_bankid_login_with_qr_capture(
    browser: Browser,
    operation_id: str,
    timeout: float = 120.0,
) -> dict:
    """Run Svea BankID login with QR streaming via operations_state.

    Updates the operation's _qr_data field for SSE streaming,
    following the same pattern as fortnox/web/auth.py.
    """
    from fortnox.browser.operations_state import update_operation

    def on_qr(qr_data: str) -> None:
        update_operation(operation_id, _qr_data=qr_data)

    result = svea_bankid_login(browser, timeout=timeout, qr_callback=on_qr)

    if "code" in result:
        update_operation(operation_id, status="authenticated", result=result)
    else:
        update_operation(
            operation_id,
            status="failed",
            error=result.get("message", "BankID failed"),
        )

    return result
