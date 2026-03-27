"""Tests for Chrome launcher and CDP connection."""

import socket
from unittest.mock import MagicMock, patch

from fortnox.browser.chrome import (
    DEFAULT_CDP_PORT,
    find_chrome,
    is_cdp_reachable,
)


class TestFindChrome:
    def test_find_chrome_on_macos(self):
        """Should find Chrome if installed at the standard macOS path."""
        with patch("fortnox.browser.chrome.Path") as mock_path:
            instance = MagicMock()
            instance.exists.return_value = True
            mock_path.return_value = instance
            # find_chrome checks Path(path).exists()
            result = find_chrome()
            assert result  # Should return a non-empty string

    def test_find_chrome_not_found(self):
        """Should raise FileNotFoundError if no Chrome binary found."""
        with patch("fortnox.browser.chrome.Path") as mock_path:
            instance = MagicMock()
            instance.exists.return_value = False
            mock_path.return_value = instance
            with patch("fortnox.browser.chrome.shutil.which", return_value=None):
                try:
                    find_chrome()
                    assert False, "Should have raised FileNotFoundError"
                except FileNotFoundError:
                    pass


class TestCdpReachable:
    def test_reachable_when_connected(self):
        """Should return True when CDP port accepts connections."""
        with patch("fortnox.browser.chrome.socket.create_connection") as mock_conn:
            mock_conn.return_value.__enter__ = MagicMock()
            mock_conn.return_value.__exit__ = MagicMock(return_value=False)
            assert is_cdp_reachable(DEFAULT_CDP_PORT) is True

    def test_not_reachable_when_refused(self):
        """Should return False when connection is refused."""
        with patch(
            "fortnox.browser.chrome.socket.create_connection",
            side_effect=ConnectionRefusedError,
        ):
            assert is_cdp_reachable(DEFAULT_CDP_PORT) is False
