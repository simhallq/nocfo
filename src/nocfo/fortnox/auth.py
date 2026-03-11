"""Fortnox OAuth2 authentication flow."""

import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import structlog

from nocfo.config import get_settings
from nocfo.storage.tokens import TokenStore

logger = structlog.get_logger()

SCOPES = "bookkeeping supplierinvoice invoice payment settings companyinformation"


def _make_callback_handler(result: dict[str, str | None]):
    """Create an OAuth callback handler that writes into *result* dict."""

    class OAuthCallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)

            if "error" in params:
                result["error"] = params["error"][0]
                self._respond(400, b"<h1>Authorization failed</h1>")
            elif "code" in params:
                result["code"] = params["code"][0]
                result["state"] = params.get("state", [None])[0]
                self._respond(200, b"<h1>Authorization successful!</h1>")
            else:
                self._respond(400, b"<h1>Invalid callback</h1>")

        def _respond(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body + b"<p>You can close this window.</p>")

        def log_message(self, format: str, *args: Any) -> None:
            pass

    return OAuthCallbackHandler


def start_authorization(timeout: int = 300) -> str:
    """Open browser for Fortnox OAuth authorization and capture the code.

    Args:
        timeout: Seconds to wait for the callback before giving up.

    Returns the authorization code.
    """
    settings = get_settings()
    state = secrets.token_urlsafe(32)

    params = {
        "client_id": settings.fortnox_client_id,
        "redirect_uri": settings.oauth_redirect_uri,
        "scope": SCOPES,
        "state": state,
        "response_type": "code",
        "access_type": "offline",
    }
    auth_url = f"{settings.fortnox_auth_url}/auth?{urlencode(params)}"

    logger.info("opening_browser_for_authorization", url=auth_url)
    webbrowser.open(auth_url)

    # Start local server to capture callback
    result: dict[str, str | None] = {"code": None, "state": None, "error": None}
    server = HTTPServer(
        ("localhost", settings.oauth_redirect_port),
        _make_callback_handler(result),
    )
    server.timeout = timeout
    logger.info("waiting_for_oauth_callback", port=settings.oauth_redirect_port)

    server.handle_request()
    server.server_close()

    if result["error"]:
        raise RuntimeError(f"OAuth authorization failed: {result['error']}")

    if result["state"] != state:
        raise RuntimeError("OAuth state mismatch - possible CSRF attack")

    code = result["code"]
    if not code:
        raise RuntimeError("No authorization code received (timed out?)")

    logger.info("authorization_code_received")
    return code


async def exchange_code_for_token(code: str) -> dict[str, Any]:
    """Exchange authorization code for access + refresh tokens."""
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.fortnox_auth_url}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oauth_redirect_uri,
            },
            auth=(settings.fortnox_client_id, settings.fortnox_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        token_data = response.json()

    logger.info("tokens_exchanged", expires_in=token_data.get("expires_in"))
    return token_data


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh the access token using the refresh token.

    Fortnox uses rotating refresh tokens - the response includes a new refresh token.
    """
    settings = get_settings()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.fortnox_auth_url}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(settings.fortnox_client_id, settings.fortnox_client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        token_data = response.json()

    logger.info("token_refreshed", expires_in=token_data.get("expires_in"))
    return token_data


class TokenManager:
    """Manages OAuth tokens with auto-refresh and persistent storage."""

    def __init__(self, token_store: TokenStore | None = None) -> None:
        self._store = token_store or TokenStore()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0

    async def initialize(self) -> None:
        """Load tokens from storage."""
        tokens = self._store.load()
        if tokens:
            self._access_token = tokens.get("access_token")
            self._refresh_token = tokens.get("refresh_token")
            self._expires_at = tokens.get("expires_at", 0)
            logger.info("tokens_loaded_from_storage")

    async def store_tokens(self, token_data: dict[str, Any]) -> None:
        """Store tokens from an OAuth response."""
        import time

        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._expires_at = time.time() + token_data.get("expires_in", 3600)

        self._store.save(
            {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "expires_at": self._expires_at,
            }
        )
        logger.info("tokens_stored")

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        import time

        if not self._access_token or not self._refresh_token:
            raise RuntimeError("No tokens available. Run 'nocfo auth setup' first.")

        # Refresh if token expires within 5 minutes
        if time.time() > self._expires_at - 300:
            await self._refresh()

        return self._access_token  # type: ignore[return-value]

    async def _refresh(self) -> None:
        """Refresh the access token."""
        if not self._refresh_token:
            raise RuntimeError("No refresh token available.")

        token_data = await refresh_access_token(self._refresh_token)
        await self.store_tokens(token_data)
        logger.info("token_auto_refreshed")

    @property
    def is_authenticated(self) -> bool:
        """Check if tokens are available."""
        return bool(self._access_token and self._refresh_token)
