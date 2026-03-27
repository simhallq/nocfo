"""Tests for vision fallback module."""

from unittest.mock import MagicMock, patch

import pytest

from fortnox.web.vision import find_element


@pytest.fixture
def mock_page():
    page = MagicMock()
    page.url = "https://apps.fortnox.se/login"
    page.screenshot.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    return page


def _make_mock_client(response_text: str) -> MagicMock:
    """Create a mock anthropic.Anthropic client that returns the given text."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=response_text)]
    mock_client.messages.create.return_value = mock_response
    return mock_client


def _patch_anthropic(mock_client: MagicMock):
    """Patch the anthropic import inside find_element."""
    mock_module = MagicMock()
    mock_module.Anthropic.return_value = mock_client
    return patch.dict("sys.modules", {"anthropic": mock_module})


class TestFindElement:
    def test_returns_none_without_api_key(self, mock_page):
        result = find_element(mock_page, "login.bankid_tab", "BankID button", api_key="")
        assert result is None

    def test_returns_handle_on_success(self, mock_page):
        """When Claude suggests a working selector, returns the element handle."""
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle

        mock_client = _make_mock_client('{"selector": "button.bankid", "confidence": "high"}')

        with _patch_anthropic(mock_client):
            result = find_element(
                mock_page, "login.bankid_tab", "BankID button", api_key="sk-test"
            )

        assert result is mock_handle
        mock_page.wait_for_selector.assert_called_once_with(
            "button.bankid", timeout=5000, state="visible"
        )

    def test_handles_json_in_code_block(self, mock_page):
        """Handles JSON wrapped in ```json ... ``` blocks."""
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle

        mock_client = _make_mock_client(
            'Here is the selector:\n```json\n{"selector": "#login-btn", "confidence": "medium"}\n```'
        )

        with _patch_anthropic(mock_client):
            result = find_element(
                mock_page, "login.bankid_tab", "BankID button", api_key="sk-test"
            )

        assert result is mock_handle

    def test_returns_none_on_selector_timeout(self, mock_page):
        """Returns None when the suggested selector doesn't match."""
        from playwright.sync_api import TimeoutError as PlaywrightTimeout

        mock_page.wait_for_selector.side_effect = PlaywrightTimeout("timeout")

        mock_client = _make_mock_client(
            '{"selector": "button.nonexistent", "confidence": "low"}'
        )

        with _patch_anthropic(mock_client):
            result = find_element(
                mock_page, "login.bankid_tab", "BankID button", api_key="sk-test"
            )

        assert result is None

    def test_returns_none_on_api_error(self, mock_page):
        """Returns None when the Claude API call fails."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        with _patch_anthropic(mock_client):
            result = find_element(
                mock_page, "login.bankid_tab", "BankID button", api_key="sk-test"
            )

        assert result is None

    def test_custom_timeout(self, mock_page):
        """Respects custom timeout parameter."""
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle

        mock_client = _make_mock_client('{"selector": "button.test", "confidence": "high"}')

        with _patch_anthropic(mock_client):
            find_element(
                mock_page,
                "test.key",
                "test element",
                api_key="sk-test",
                timeout=10000,
            )

        mock_page.wait_for_selector.assert_called_once_with(
            "button.test", timeout=10000, state="visible"
        )
