"""Tests for Fortnox web session cookie persistence."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nocfo.fortnox.web.session import (
    clear_session,
    has_valid_session,
    load_session,
    save_session,
    MAX_SESSION_AGE_SECONDS,
)


@pytest.fixture
def sessions_dir(tmp_path):
    return str(tmp_path / "sessions")


@pytest.fixture
def mock_page():
    """Mock Playwright page with context.cookies()."""
    from unittest.mock import MagicMock

    page = MagicMock()
    page.url = "https://apps2.fortnox.se/app/12345/common/lobby"
    page.context.cookies.return_value = [
        {"name": "session", "domain": ".fortnox.se", "value": "abc123"},
        {"name": "auth", "domain": "apps2.fortnox.se", "value": "xyz789"},
        {"name": "unrelated", "domain": ".google.com", "value": "skip"},
    ]
    return page


class TestSaveSession:
    def test_saves_cookies_to_disk(self, mock_page, sessions_dir):
        save_session(mock_page, "acme-ab", sessions_dir=sessions_dir)
        path = Path(sessions_dir) / "acme-ab" / "cookies.json"
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["customer_id"] == "acme-ab"
        assert len(data["cookies"]) == 2  # Fortnox cookies only, not google
        assert data["url"] == mock_page.url
        assert "saved_at" in data

    def test_filters_non_fortnox_cookies(self, mock_page, sessions_dir):
        save_session(mock_page, "test", sessions_dir=sessions_dir)
        path = Path(sessions_dir) / "test" / "cookies.json"
        data = json.loads(path.read_text())
        domains = {c["domain"] for c in data["cookies"]}
        assert ".google.com" not in domains

    def test_creates_directories(self, mock_page, sessions_dir):
        save_session(mock_page, "new-customer", sessions_dir=sessions_dir)
        assert Path(sessions_dir).exists()
        assert (Path(sessions_dir) / "new-customer").exists()

    def test_file_permissions(self, mock_page, sessions_dir):
        save_session(mock_page, "test", sessions_dir=sessions_dir)
        path = Path(sessions_dir) / "test" / "cookies.json"
        assert oct(path.stat().st_mode)[-3:] == "600"


class TestLoadSession:
    def test_loads_cookies_into_context(self, mock_page, sessions_dir):
        from unittest.mock import MagicMock

        # First save
        save_session(mock_page, "acme-ab", sessions_dir=sessions_dir)

        # Then load into new context
        context = MagicMock()
        result = load_session(context, "acme-ab", sessions_dir=sessions_dir)
        assert result is True
        context.add_cookies.assert_called_once()
        cookies = context.add_cookies.call_args[0][0]
        assert len(cookies) == 2

    def test_returns_false_for_missing_session(self, sessions_dir):
        from unittest.mock import MagicMock

        context = MagicMock()
        result = load_session(context, "nonexistent", sessions_dir=sessions_dir)
        assert result is False

    def test_returns_false_for_corrupt_file(self, sessions_dir):
        from unittest.mock import MagicMock

        path = Path(sessions_dir) / "corrupt" / "cookies.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json{{{")

        context = MagicMock()
        result = load_session(context, "corrupt", sessions_dir=sessions_dir)
        assert result is False


class TestHasValidSession:
    def test_returns_true_for_recent_session(self, mock_page, sessions_dir):
        save_session(mock_page, "acme-ab", sessions_dir=sessions_dir)
        assert has_valid_session("acme-ab", sessions_dir=sessions_dir) is True

    def test_returns_false_for_missing_session(self, sessions_dir):
        assert has_valid_session("nonexistent", sessions_dir=sessions_dir) is False

    def test_returns_false_for_old_session(self, mock_page, sessions_dir):
        save_session(mock_page, "old", sessions_dir=sessions_dir)
        # Manually make it old
        path = Path(sessions_dir) / "old" / "cookies.json"
        data = json.loads(path.read_text())
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
        data["saved_at"] = old_time
        path.write_text(json.dumps(data))

        assert has_valid_session("old", sessions_dir=sessions_dir) is False


class TestClearSession:
    def test_removes_session_file(self, mock_page, sessions_dir):
        save_session(mock_page, "acme-ab", sessions_dir=sessions_dir)
        path = Path(sessions_dir) / "acme-ab" / "cookies.json"
        assert path.exists()

        clear_session("acme-ab", sessions_dir=sessions_dir)
        assert not path.exists()

    def test_clear_nonexistent_is_noop(self, sessions_dir):
        # Should not raise
        clear_session("nonexistent", sessions_dir=sessions_dir)
