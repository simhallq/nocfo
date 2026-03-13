"""Fortnox API HTTP client with rate limiting and retries."""

import asyncio
import time
from collections import deque
from typing import Any

import httpx
import structlog

from nocfo.config import get_settings
from nocfo.fortnox.api.auth import TokenManager

logger = structlog.get_logger()


class RateLimiter:
    """Sliding window rate limiter for Fortnox API (25 requests per 5 seconds)."""

    def __init__(self, max_requests: int = 25, window_seconds: float = 5.0) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a request slot is available."""
        while True:
            async with self._lock:
                now = time.monotonic()

                # Remove timestamps outside the window
                while self._timestamps and self._timestamps[0] <= now - self._window_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(time.monotonic())
                    return

                # Compute sleep time but release the lock before sleeping
                sleep_time = self._timestamps[0] + self._window_seconds - now

            if sleep_time > 0:
                logger.debug("rate_limit_wait", sleep_seconds=round(sleep_time, 2))
                await asyncio.sleep(sleep_time)


class FortnoxClient:
    """Async HTTP client for the Fortnox REST API."""

    def __init__(
        self,
        token_manager: TokenManager | None = None,
        max_retries: int = 3,
    ) -> None:
        self._settings = get_settings()
        self._token_manager = token_manager or TokenManager()
        self._rate_limiter = RateLimiter()
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "FortnoxClient":
        self._client = httpx.AsyncClient(
            base_url=self._settings.fortnox_base_url,
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
                        "rate_limited",
                        retry_after=retry_after,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "server_error",
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
                    logger.warning("transport_error", error=str(e), attempt=attempt + 1)
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

    async def upload_file(
        self,
        path: str,
        filename: str,
        file_bytes: bytes,
        content_type: str,
    ) -> dict[str, Any]:
        """Upload a file via multipart form data."""
        if not self._client:
            raise RuntimeError("Client not initialized. Use 'async with' context manager.")

        await self._rate_limiter.acquire()
        token = await self._token_manager.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        response = await self._client.post(
            path,
            headers=headers,
            files={"file": (filename, file_bytes, content_type)},
        )
        response.raise_for_status()
        return response.json()  # type: ignore[no-any-return]

    async def get_all_pages(
        self,
        path: str,
        collection_key: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages of a paginated Fortnox response.

        Fortnox uses @CurrentPage/@TotalPages for pagination.
        """
        all_items: list[dict[str, Any]] = []
        page = 1
        request_params = dict(params or {})

        while True:
            request_params["page"] = page
            data = await self.get(path, params=request_params)

            meta = data.get("MetaInformation", {})
            items = data.get(collection_key, [])
            all_items.extend(items)

            total_pages = meta.get("@TotalPages", 1)
            if page >= total_pages:
                break
            page += 1

        logger.debug("fetched_all_pages", path=path, total_items=len(all_items))
        return all_items
