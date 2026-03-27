"""Tests for selector resolution."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeout

from fortnox.web.selectors import (
    _load_selectors,
    _resolve_description,
    _resolve_key,
    find,
)


class TestSelectorLoading:
    def test_load_selectors(self):
        """Should load selectors from YAML file."""
        selectors = _load_selectors()
        assert isinstance(selectors, dict)
        assert "login" in selectors
        assert "reconciliation" in selectors
        assert "reports" in selectors
        assert "rules" in selectors

    def test_resolve_login_bankid_tab(self):
        """Should resolve login.bankid_tab to a list of selectors."""
        result = _resolve_key("login.bankid_tab")
        assert isinstance(result, list)
        assert len(result) > 0
        assert any("BankID" in s for s in result)

    def test_resolve_with_template_vars(self):
        """Should substitute template variables in selectors."""
        result = _resolve_key("settings_page.setting_item", text="Automatkontering")
        assert isinstance(result, list)
        assert any("Automatkontering" in s for s in result)

    def test_resolve_invalid_key(self):
        """Should raise KeyError for unknown keys."""
        with pytest.raises(KeyError):
            _resolve_key("nonexistent.key")

    def test_resolve_nested_key(self):
        """Should resolve deeply nested keys."""
        result = _resolve_key("reconciliation.save_button")
        assert isinstance(result, list)
        assert len(result) > 0


class TestSelectorDescriptions:
    def test_resolve_description(self):
        """Should return the description field from YAML."""
        desc = _resolve_description("login.bankid_tab")
        assert "BankID" in desc

    def test_resolve_description_fallback(self):
        """Should return a derived description for missing keys."""
        desc = _resolve_description("nonexistent.key")
        assert "nonexistent" in desc


class TestThreeStageResolution:
    @pytest.fixture
    def mock_page(self):
        page = MagicMock()
        page.url = "https://apps.fortnox.se"
        page.screenshot.return_value = b"\x89PNG" + b"\x00" * 100
        return page

    def test_stage1_yaml_match(self, mock_page):
        """Stage 1: Returns handle when YAML selector matches."""
        mock_handle = MagicMock()
        mock_page.wait_for_selector.return_value = mock_handle

        result = find(mock_page, "login.bankid_tab", timeout=5000)
        assert result is mock_handle

    def test_stage2_learned_match(self, mock_page, tmp_path):
        """Stage 2: Falls through to learned selectors when YAML fails."""
        from fortnox.web.learned import LearnedSelectors

        # Make YAML selectors fail, learned succeed
        call_count = 0

        def side_effect(selector, timeout=None, state=None):
            nonlocal call_count
            call_count += 1
            if selector == "button.learned-bankid":
                return MagicMock()
            raise PlaywrightTimeout("not found")

        mock_page.wait_for_selector.side_effect = side_effect

        # Set up learned store
        store = LearnedSelectors(path=tmp_path / "learned.json")
        store.save("login.bankid_tab", "button.learned-bankid")

        with patch("fortnox.web.selectors._get_learned", return_value=store):
            result = find(mock_page, "login.bankid_tab", timeout=5000)
            assert result is not None

    def test_stage3_vision_fallback(self, mock_page, tmp_path):
        """Stage 3: Falls through to vision when YAML and learned fail."""
        mock_page.wait_for_selector.side_effect = PlaywrightTimeout("not found")

        mock_handle = MagicMock()
        store = MagicMock()
        store.get.return_value = []

        with (
            patch("fortnox.web.selectors._get_learned", return_value=store),
            patch("fortnox.web.vision.find_element", return_value=mock_handle) as mock_vision,
        ):
            result = find(
                mock_page, "login.bankid_tab", timeout=5000, vision_api_key="sk-test"
            )
            assert result is mock_handle
            mock_vision.assert_called_once()

    def test_raises_when_all_stages_fail(self, mock_page, tmp_path):
        """Raises PlaywrightTimeout when all three stages fail."""
        mock_page.wait_for_selector.side_effect = PlaywrightTimeout("not found")

        store = MagicMock()
        store.get.return_value = []

        with patch("fortnox.web.selectors._get_learned", return_value=store):
            with pytest.raises(PlaywrightTimeout):
                find(mock_page, "login.bankid_tab", timeout=5000)

    def test_learned_pruned_on_failure(self, mock_page, tmp_path):
        """Learned selectors are removed when they fail."""
        from fortnox.web.learned import LearnedSelectors

        mock_page.wait_for_selector.side_effect = PlaywrightTimeout("not found")

        store = LearnedSelectors(path=tmp_path / "learned.json")
        store.save("login.bankid_tab", "button.stale-selector")

        with patch("fortnox.web.selectors._get_learned", return_value=store):
            with pytest.raises(PlaywrightTimeout):
                find(mock_page, "login.bankid_tab", timeout=5000)

        # The stale selector should have been pruned
        assert store.get("login.bankid_tab") == []
