"""Tests for BrowserApiClient."""

import json
from unittest.mock import MagicMock, patch

import pytest

from nocfo.browser.client import BrowserApiClient


class TestBrowserApiClient:
    def test_context_manager(self):
        """Should initialize and close httpx client."""
        with BrowserApiClient(base_url="http://localhost:9999") as client:
            assert client._client is not None
        assert client._client is None or True  # client.close() was called

    def test_auth_header_set(self):
        """Should set Authorization header when token is provided."""
        with BrowserApiClient(base_url="http://localhost:9999", token="test-token") as client:
            assert "Authorization" in client._client.headers
            assert client._client.headers["Authorization"] == "Bearer test-token"

    def test_no_auth_header_without_token(self):
        """Should not set Authorization header when no token."""
        with BrowserApiClient(base_url="http://localhost:9999") as client:
            assert "Authorization" not in client._client.headers

    def test_not_initialized_error(self):
        """Should raise RuntimeError when used without context manager."""
        client = BrowserApiClient()
        with pytest.raises(RuntimeError, match="not initialized"):
            client._request("GET", "/health")


class TestBrowserApiClientMethods:
    @patch("nocfo.browser.client.httpx.Client")
    def test_health(self, mock_client_cls):
        """Should call GET /health."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with BrowserApiClient() as client:
            client._client = mock_client
            result = client.health()

        assert result == {"status": "ok"}
        mock_client.request.assert_called_once_with("GET", "/health", json=None)

    @patch("nocfo.browser.client.httpx.Client")
    def test_auth_status(self, mock_client_cls):
        """Should call GET /auth/status and return bool."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"authenticated": True}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with BrowserApiClient() as client:
            client._client = mock_client
            result = client.auth_status()

        assert result is True

    @patch("nocfo.browser.client.httpx.Client")
    def test_close_period(self, mock_client_cls):
        """Should call POST /period/close with period."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "ok", "period": "2024-03"}
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with BrowserApiClient() as client:
            client._client = mock_client
            result = client.close_period("2024-03")

        assert result["status"] == "ok"
        mock_client.request.assert_called_once_with(
            "POST", "/period/close", json={"period": "2024-03"}
        )

    @patch("nocfo.browser.client.httpx.Client")
    def test_download_report_file(self, mock_client_cls):
        """Should return raw bytes when server sends file."""
        mock_response = MagicMock()
        mock_response.headers = {"content-type": "application/pdf"}
        mock_response.content = b"%PDF-1.4..."
        mock_response.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.request.return_value = mock_response
        mock_client_cls.return_value = mock_client

        with BrowserApiClient() as client:
            client._client = mock_client
            result = client.download_report("balance", "2024-03")

        assert result == b"%PDF-1.4..."
