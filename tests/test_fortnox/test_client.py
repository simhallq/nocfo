"""Tests for Fortnox HTTP client."""

import httpx
import pytest
import respx

from nocfo.fortnox.api.client import FortnoxClient, RateLimiter


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_under_limit(self):
        limiter = RateLimiter(max_requests=5, window_seconds=1.0)
        for _ in range(5):
            await limiter.acquire()

    @pytest.mark.asyncio
    async def test_acquire_at_limit_blocks(self):
        import time

        limiter = RateLimiter(max_requests=2, window_seconds=0.5)
        await limiter.acquire()
        await limiter.acquire()

        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.3


class TestFortnoxClient:
    @pytest.mark.asyncio
    @respx.mock
    async def test_get_request(
        self, mock_settings, fake_token_manager, sample_company_info_response
    ):
        token_manager = fake_token_manager

        respx.get("https://api.fortnox.se/3/companyinformation").mock(
            return_value=httpx.Response(200, json=sample_company_info_response)
        )

        async with FortnoxClient(token_manager=token_manager) as client:
            result = await client.get("/companyinformation")

        assert result["CompanyInformation"]["CompanyName"] == "Test AB"

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_429(self, mock_settings, fake_token_manager):
        token_manager = fake_token_manager

        route = respx.get("https://api.fortnox.se/3/test")
        route.side_effect = [
            httpx.Response(429, headers={"Retry-After": "0.1"}),
            httpx.Response(200, json={"data": "ok"}),
        ]

        async with FortnoxClient(token_manager=token_manager) as client:
            result = await client.get("/test")

        assert result["data"] == "ok"
        assert route.call_count == 2

    @pytest.mark.asyncio
    @respx.mock
    async def test_retry_on_500(self, mock_settings, fake_token_manager):
        token_manager = fake_token_manager

        route = respx.get("https://api.fortnox.se/3/test")
        route.side_effect = [
            httpx.Response(500),
            httpx.Response(200, json={"data": "ok"}),
        ]

        async with FortnoxClient(token_manager=token_manager) as client:
            result = await client.get("/test")

        assert result["data"] == "ok"

    @pytest.mark.asyncio
    @respx.mock
    async def test_pagination(self, mock_settings, fake_token_manager):
        token_manager = fake_token_manager

        respx.get("https://api.fortnox.se/3/items").mock(
            side_effect=[
                httpx.Response(
                    200,
                    json={
                        "MetaInformation": {"@CurrentPage": 1, "@TotalPages": 2},
                        "Items": [{"id": 1}, {"id": 2}],
                    },
                ),
                httpx.Response(
                    200,
                    json={
                        "MetaInformation": {"@CurrentPage": 2, "@TotalPages": 2},
                        "Items": [{"id": 3}],
                    },
                ),
            ]
        )

        async with FortnoxClient(token_manager=token_manager) as client:
            items = await client.get_all_pages("/items", "Items")

        assert len(items) == 3
        assert items[2]["id"] == 3
