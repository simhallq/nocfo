"""Tests for Browser API handler routing and auth."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

from nocfo.browser.handler import BrowserAPIHandler


def _make_handler(
    method: str = "GET",
    path: str = "/health",
    body: dict | None = None,
    auth_token: str = "",
    request_token: str = "",
) -> BrowserAPIHandler:
    """Create a mock handler for testing."""
    handler = object.__new__(BrowserAPIHandler)

    # Set class-level attributes
    handler.browser = MagicMock()
    handler.browser_lock = MagicMock()
    handler.auth_token = auth_token
    handler.cdp_port = 9222

    # Mock HTTP internals
    handler.path = path
    handler.command = method
    handler.headers = {}
    if request_token:
        handler.headers["Authorization"] = f"Bearer {request_token}"

    # Mock request body
    body_bytes = json.dumps(body).encode() if body else b""
    handler.headers["Content-Length"] = str(len(body_bytes))
    handler.rfile = BytesIO(body_bytes)

    # Mock response writing
    handler.wfile = BytesIO()
    handler._response_code = None
    handler._response_headers = {}

    original_send_response = handler.send_response.__func__ if hasattr(handler.send_response, '__func__') else None

    def mock_send_response(code, message=None):
        handler._response_code = code

    def mock_send_header(key, value):
        handler._response_headers[key] = value

    def mock_end_headers():
        pass

    handler.send_response = mock_send_response
    handler.send_header = mock_send_header
    handler.end_headers = mock_end_headers

    return handler


class TestAuthentication:
    def test_no_token_required(self):
        """Should allow request when no auth token configured."""
        handler = _make_handler(auth_token="")
        assert handler._authenticate() is True

    def test_valid_token(self):
        """Should allow request with correct token."""
        handler = _make_handler(auth_token="secret", request_token="secret")
        assert handler._authenticate() is True

    def test_invalid_token(self):
        """Should reject request with wrong token."""
        handler = _make_handler(auth_token="secret", request_token="wrong")
        result = handler._authenticate()
        assert result is False
        assert handler._response_code == 401

    def test_missing_token(self):
        """Should reject request when token required but not provided."""
        handler = _make_handler(auth_token="secret", request_token="")
        result = handler._authenticate()
        assert result is False
        assert handler._response_code == 401


class TestBodyParsing:
    def test_read_json_body(self):
        """Should parse JSON request body."""
        handler = _make_handler(body={"account": 1930})
        result = handler._read_body()
        assert result == {"account": 1930}

    def test_empty_body(self):
        """Should return empty dict for no body."""
        handler = _make_handler()
        handler.headers["Content-Length"] = "0"
        result = handler._read_body()
        assert result == {}
