"""Svea Bank OAuth2 + BankID authentication.

Svea Bank uses IdentityServer at auth.svea.com with standard OIDC endpoints
plus custom BankID grant types ('bankid', 'bankidqr') for direct authentication.

Auth flow:
1. Authorization code + PKCE (browser-based, same as SPA)
   OR direct BankID via token endpoint (grant_type=bankidqr)
2. Exchange for access_token + refresh_token
3. Auto-refresh via refresh_token grant
"""

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

from fortnox.config import get_settings
from fortnox.storage.tokens import TokenStore

logger = structlog.get_logger()

# Svea Bank OAuth2 / OIDC configuration (from bank.svea.com SPA config)
SVEA_CLIENT_ID = "svea.sveabank.web"
SVEA_SCOPES = "offline_access openid sveabank core onboarding tenant"
SVEA_REDIRECT_URI = "https://bank.svea.com/sso-login"


def _authority() -> str:
    return get_settings().svea_auth_url


def _token_endpoint() -> str:
    return f"{_authority()}/connect/token"


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorize_url(
    state: str | None = None,
    code_challenge: str | None = None,
) -> tuple[str, str, str]:
    """Build the authorization URL for browser-based OAuth flow.

    Returns (url, state, code_verifier).
    """
    if state is None:
        state = secrets.token_urlsafe(32)

    code_verifier, challenge = generate_pkce()
    if code_challenge is None:
        code_challenge = challenge

    params = {
        "client_id": SVEA_CLIENT_ID,
        "redirect_uri": SVEA_REDIRECT_URI,
        "response_type": "code",
        "scope": SVEA_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    url = f"{_authority()}/connect/authorize?{urlencode(params)}"
    return url, state, code_verifier


async def exchange_code_for_token(
    code: str,
    code_verifier: str,
    redirect_uri: str = SVEA_REDIRECT_URI,
) -> dict[str, Any]:
    """Exchange authorization code for tokens (PKCE flow)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _token_endpoint(),
            data={
                "grant_type": "authorization_code",
                "client_id": SVEA_CLIENT_ID,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
        )
        response.raise_for_status()
        token_data = response.json()
        logger.info("svea_token_exchanged", token_type=token_data.get("token_type"))
        return token_data


async def start_bankid_auth() -> dict[str, Any]:
    """Start BankID authentication via the custom 'bankidqr' grant type.

    This attempts direct BankID auth through the token endpoint,
    bypassing the browser-based OAuth flow. The auth.svea.com OIDC
    discovery lists 'bankid' and 'bankidqr' as supported grant types.

    Returns the initial response which may contain BankID order reference
    and QR data for the user to scan.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _token_endpoint(),
            data={
                "grant_type": "bankidqr",
                "client_id": SVEA_CLIENT_ID,
                "scope": SVEA_SCOPES,
            },
        )
        # Don't raise_for_status — we need to inspect the response
        # even if it's a 400 (might contain BankID order data or error details)
        result = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
        }
        try:
            result["body"] = response.json()
        except Exception:
            result["body_text"] = response.text
        logger.info("svea_bankid_auth_started", status=response.status_code)
        return result


async def poll_bankid_status(order_ref: str) -> dict[str, Any]:
    """Poll BankID status for a pending authentication.

    The exact endpoint and request format depends on the response from
    start_bankid_auth(). This is a placeholder that will be refined
    after the API spike.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Try common BankID polling patterns
        response = await client.post(
            _token_endpoint(),
            data={
                "grant_type": "bankidqr",
                "client_id": SVEA_CLIENT_ID,
                "scope": SVEA_SCOPES,
                "order_ref": order_ref,
            },
        )
        result: dict[str, Any] = {"status_code": response.status_code}
        try:
            result["body"] = response.json()
        except Exception:
            result["body_text"] = response.text
        return result


async def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    """Refresh an expired access token using the refresh token."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _token_endpoint(),
            data={
                "grant_type": "refresh_token",
                "client_id": SVEA_CLIENT_ID,
                "refresh_token": refresh_token,
            },
        )
        response.raise_for_status()
        token_data = response.json()
        logger.info("svea_token_refreshed")
        return token_data


class SveaTokenManager:
    """Manages Svea Bank OAuth tokens with auto-refresh.

    Follows the same pattern as fortnox.api.auth.TokenManager.
    """

    def __init__(self, token_store: TokenStore | None = None) -> None:
        self._store = token_store or TokenStore(get_settings().svea_tokens_path)
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._id_token: str | None = None

    async def initialize(self) -> None:
        """Load tokens from persistent storage."""
        data = self._store.load()
        if data:
            self._access_token = data.get("access_token")
            self._refresh_token = data.get("refresh_token")
            self._expires_at = data.get("expires_at", 0.0)
            self._id_token = data.get("id_token")
            logger.debug("svea_tokens_loaded", has_access=bool(self._access_token))

    async def store_tokens(self, token_data: dict[str, Any]) -> None:
        """Persist token data from an OAuth response."""
        expires_in = token_data.get("expires_in", 3600)
        self._access_token = token_data.get("access_token")
        self._refresh_token = token_data.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + expires_in
        self._id_token = token_data.get("id_token")

        self._store.save({
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
            "id_token": self._id_token,
        })
        logger.info("svea_tokens_stored", expires_in=expires_in)

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if near expiry (5 min buffer)."""
        if not self._access_token or not self._refresh_token:
            raise RuntimeError(
                "No Svea Bank tokens available. Run 'fortnox svea auth' to authenticate."
            )

        if time.time() > self._expires_at - 300:
            await self._refresh()

        return self._access_token

    async def _refresh(self) -> None:
        """Refresh the access token."""
        if not self._refresh_token:
            raise RuntimeError("No refresh token available for Svea Bank.")

        token_data = await refresh_access_token(self._refresh_token)
        await self.store_tokens(token_data)

    @property
    def is_authenticated(self) -> bool:
        """Check if tokens are available (may be expired)."""
        return bool(self._access_token and self._refresh_token)
