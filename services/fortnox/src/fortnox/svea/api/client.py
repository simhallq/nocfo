"""Async HTTP client for Svea Bank's internal REST API (bankapi.svea.com).

Mirrors the FortnoxClient pattern from fortnox.fortnox.api.client with:
- Sliding window rate limiter (conservative: 10 req/5s until we know Svea's limits)
- Exponential backoff retries for server errors and rate limiting
- Automatic bearer token injection via SveaTokenManager
- Async context manager for clean resource management
"""

import asyncio
import time
from collections import deque
from typing import Any

import httpx
import structlog

from fortnox.config import get_settings
from fortnox.svea.api.auth import SveaTokenManager

logger = structlog.get_logger()


class RateLimiter:
    """Sliding window rate limiter for Svea Bank API.

    Conservative defaults until we discover actual limits from 429 responses.
    """

    def __init__(self, max_requests: int = 10, window_seconds: float = 5.0) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._timestamps and self._timestamps[0] <= now - self._window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(time.monotonic())
                    return

                sleep_time = self._timestamps[0] + self._window_seconds - now

            if sleep_time > 0:
                logger.debug("svea_rate_limit_wait", sleep_seconds=round(sleep_time, 2))
                await asyncio.sleep(sleep_time)


class SveaClient:
    """Async HTTP client for the Svea Bank REST API."""

    def __init__(
        self,
        token_manager: SveaTokenManager | None = None,
        max_retries: int = 3,
    ) -> None:
        self._settings = get_settings()
        self._token_manager = token_manager or SveaTokenManager()
        self._rate_limiter = RateLimiter()
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "SveaClient":
        self._client = httpx.AsyncClient(
            base_url=self._settings.svea_bank_api_url,
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _get_headers(self) -> dict[str, str]:
        """Build request headers with current access token."""
        token = await self._token_manager.get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated API request with rate limiting and retries."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            await self._rate_limiter.acquire()

            try:
                headers = await self._get_headers()
                response = await self._client.request(
                    method,
                    path,
                    headers=headers,
                    params=params,
                    json=json_data,
                )

                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", "5"))
                    logger.warning(
                        "svea_rate_limited",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "svea_server_error",
                        status=response.status_code,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(2**attempt)
                    continue

                response.raise_for_status()
                return response.json()  # type: ignore[no-any-return]

            except httpx.HTTPStatusError as e:
                if (
                    e.response.status_code in (429, 500, 502, 503, 504)
                    and attempt < self._max_retries
                ):
                    last_error = e
                    continue
                raise
            except httpx.TransportError as e:
                if attempt < self._max_retries:
                    last_error = e
                    logger.warning("svea_transport_error", error=str(e), attempt=attempt + 1)
                    await asyncio.sleep(2**attempt)
                    continue
                raise

        raise last_error or RuntimeError("Request failed after all retries")

    async def get(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """GET request."""
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """POST request."""
        return await self.request("POST", path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """PUT request."""
        return await self.request("PUT", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> dict[str, Any]:
        """DELETE request."""
        return await self.request("DELETE", path, **kwargs)

    async def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an authenticated request returning the raw httpx.Response.

        Useful for probing endpoints during discovery or handling non-JSON responses.
        """
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        await self._rate_limiter.acquire()
        headers = await self._get_headers()
        return await self._client.request(
            method,
            path,
            headers=headers,
            params=params,
            json=json_data,
        )
