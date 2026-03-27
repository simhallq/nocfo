"""Tests for SveaClient HTTP client."""

import pytest
import respx
from httpx import Response

from fortnox.svea.api.auth import SveaTokenManager
from fortnox.svea.api.client import SveaClient


@pytest.fixture
def mock_token_manager(monkeypatch):
    """SveaTokenManager that returns a fake token."""
    manager = SveaTokenManager.__new__(SveaTokenManager)
    manager._access_token = "test-token-123"
    manager._refresh_token = "test-refresh-456"
    manager._expires_at = 9999999999.0
    manager._id_token = None
    manager._store = None

    async def fake_get_token():
        return "test-token-123"

    monkeypatch.setattr(manager, "get_access_token", fake_get_token)
    return manager


@pytest.fixture
def svea_base_url():
    return "https://bankapi.svea.com"


class TestSveaClient:
    @respx.mock
    async def test_get_request_with_auth(self, mock_token_manager, svea_base_url):
        route = respx.get(f"{svea_base_url}/psu/bank-account").mock(
            return_value=Response(200, json={"bankAccounts": []})
        )

        async with SveaClient(token_manager=mock_token_manager) as client:
            result = await client.get("/psu/bank-account")

        assert route.called
        assert result == {"bankAccounts": []}
        # Verify auth header was sent
        request = route.calls[0].request
        assert request.headers["authorization"] == "Bearer test-token-123"

    @respx.mock
    async def test_post_request(self, mock_token_manager, svea_base_url):
        route = respx.post(f"{svea_base_url}/psu/payment-order").mock(
            return_value=Response(200, json={"status": "created"})
        )

        async with SveaClient(token_manager=mock_token_manager) as client:
            result = await client.post(
                "/psu/payment-order",
                json_data={"amount": 1000, "recipient": "123-4567"},
            )

        assert result["status"] == "created"

    @respx.mock
    async def test_retry_on_server_error(self, mock_token_manager, svea_base_url):
        route = respx.get(f"{svea_base_url}/psu/profile")
        route.side_effect = [
            Response(500, json={"error": "server_error"}),
            Response(200, json={"name": "Test User"}),
        ]

        async with SveaClient(token_manager=mock_token_manager, max_retries=3) as client:
            result = await client.get("/psu/profile")

        assert result["name"] == "Test User"
        assert route.call_count == 2

    @respx.mock
    async def test_retry_on_rate_limit(self, mock_token_manager, svea_base_url):
        route = respx.get(f"{svea_base_url}/psu/bank-account")
        route.side_effect = [
            Response(429, headers={"Retry-After": "0"}),
            Response(200, json={"bankAccounts": []}),
        ]

        async with SveaClient(token_manager=mock_token_manager, max_retries=3) as client:
            result = await client.get("/psu/bank-account")

        assert result == {"bankAccounts": []}
        assert route.call_count == 2

    @respx.mock
    async def test_raises_on_4xx(self, mock_token_manager, svea_base_url):
        respx.get(f"{svea_base_url}/psu/bank-account").mock(
            return_value=Response(403, json={"error": "forbidden"})
        )

        async with SveaClient(token_manager=mock_token_manager) as client:
            with pytest.raises(Exception):
                await client.get("/psu/bank-account")

    async def test_context_manager_required(self, mock_token_manager):
        client = SveaClient(token_manager=mock_token_manager)
        with pytest.raises(RuntimeError, match="not initialized"):
            await client.get("/test")
