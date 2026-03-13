"""Fortnox session management — login detection, session validation, and cookie persistence."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import structlog
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout

logger = structlog.get_logger()

# The actual Fortnox accounting app lives on apps2.fortnox.se
FORTNOX_APP_DOMAIN = "apps2.fortnox.se"
FORTNOX_LOBBY_PATTERN = "apps2.fortnox.se/app/"

FORTNOX_COOKIE_DOMAINS = [".fortnox.se", "apps.fortnox.se", "apps2.fortnox.se", "id.fortnox.se"]

# Maximum session age before considering it stale (7 days)
MAX_SESSION_AGE_SECONDS = 7 * 24 * 3600


def is_authenticated(page: Page, timeout: int = 10000) -> bool:
    """Check if the current Fortnox session is active.

    Checks the current page URL — if already on apps2, session is live.
    Otherwise navigates to tenant-select which redirects to login if expired.
    """
    try:
        url = page.url

        # Already on the app — session is active
        if FORTNOX_APP_DOMAIN in url:
            logger.info("session_check", authenticated=True, reason="on_app")
            return True

        # Navigate to tenant-select — if session is valid, this loads or redirects to app
        page.goto(
            "https://apps.fortnox.se/login-fortnox-id/tenant-select",
            wait_until="networkidle",
            timeout=timeout,
        )

        url = page.url
        if FORTNOX_APP_DOMAIN in url or "tenant-select" in url:
            logger.info("session_check", authenticated=True, reason="tenant_select_ok")
            return True

        if "id.fortnox.se" in url and "account" not in url:
            logger.info("session_check", authenticated=False, reason="redirected_to_login")
            return False

        # Check for login form elements
        try:
            if page.wait_for_selector("input[type='password']", timeout=2000, state="visible"):
                logger.info("session_check", authenticated=False, reason="login_form_visible")
                return False
        except PlaywrightTimeout:
            pass

        # Not clearly on login — assume authenticated
        logger.info("session_check", authenticated=True, reason="no_login_detected")
        return True

    except Exception as e:
        logger.error("session_check_error", error=str(e))
        return False


def ensure_session(page: Page) -> bool:
    """Verify session is active. Returns True if authenticated."""
    return is_authenticated(page)


def get_session_status(page: Page) -> dict:
    """Return detailed session status for the /health endpoint."""
    try:
        authenticated = is_authenticated(page)
        return {
            "authenticated": authenticated,
            "url": page.url,
        }
    except Exception as e:
        return {
            "authenticated": False,
            "error": str(e),
        }


# --- Cookie persistence ---


def save_session(page: Page, customer_id: str, sessions_dir: str = "data/sessions") -> None:
    """Extract Fortnox cookies and persist to disk."""
    cookies = page.context.cookies()
    filtered = [
        c for c in cookies
        if any(d in c.get("domain", "") for d in FORTNOX_COOKIE_DOMAINS)
    ]

    path = Path(sessions_dir) / customer_id / "cookies.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "customer_id": customer_id,
        "cookies": filtered,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "url": page.url,
    }

    path.write_text(json.dumps(data, indent=2, default=str))
    os.chmod(path, 0o600)

    logger.info("session_saved", customer_id=customer_id, cookie_count=len(filtered))


def load_session(context, customer_id: str, sessions_dir: str = "data/sessions") -> bool:
    """Inject stored cookies into browser context. Returns True if loaded."""
    path = Path(sessions_dir) / customer_id / "cookies.json"
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text())
        cookies = data.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
            logger.info("session_loaded", customer_id=customer_id, cookie_count=len(cookies))
            return True
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("session_load_error", customer_id=customer_id, error=str(e))

    return False


def has_valid_session(customer_id: str, sessions_dir: str = "data/sessions") -> bool:
    """Check if stored session exists and is not too old."""
    path = Path(sessions_dir) / customer_id / "cookies.json"
    if not path.exists():
        return False

    try:
        data = json.loads(path.read_text())
        saved_at = data.get("saved_at", "")
        if saved_at:
            saved_dt = datetime.fromisoformat(saved_at)
            age = (datetime.now(timezone.utc) - saved_dt).total_seconds()
            return age < MAX_SESSION_AGE_SECONDS
    except (json.JSONDecodeError, OSError, ValueError):
        pass

    return False


def clear_session(customer_id: str, sessions_dir: str = "data/sessions") -> None:
    """Remove stored session cookies."""
    path = Path(sessions_dir) / customer_id / "cookies.json"
    if path.exists():
        path.unlink()
        logger.info("session_cleared", customer_id=customer_id)
