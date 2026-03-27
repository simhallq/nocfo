"""Tests for learned selectors store."""

import json
from pathlib import Path

import pytest

from fortnox.web.learned import LearnedSelectors


@pytest.fixture
def store(tmp_path):
    """Create a LearnedSelectors with a temporary file."""
    return LearnedSelectors(path=tmp_path / "learned.json")


class TestLearnedSelectors:
    def test_get_empty(self, store):
        assert store.get("login.bankid_tab") == []

    def test_save_and_get(self, store):
        store.save("login.bankid_tab", "button.bankid")
        result = store.get("login.bankid_tab")
        assert result == ["button.bankid"]

    def test_save_deduplicates(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.save("login.bankid_tab", "button.bankid")
        result = store.get("login.bankid_tab")
        assert result == ["button.bankid"]

    def test_save_multiple_selectors(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.save("login.bankid_tab", "#bankid-btn")
        result = store.get("login.bankid_tab")
        assert result == ["button.bankid", "#bankid-btn"]

    def test_remove_selector(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.save("login.bankid_tab", "#bankid-btn")
        store.remove("login.bankid_tab", "button.bankid")
        result = store.get("login.bankid_tab")
        assert result == ["#bankid-btn"]

    def test_remove_last_selector_removes_key(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.remove("login.bankid_tab", "button.bankid")
        assert store.get("login.bankid_tab") == []

    def test_remove_nonexistent_key(self, store):
        # Should not raise
        store.remove("nonexistent", "selector")

    def test_clear_specific_key(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.save("login.qr_image", "canvas")
        store.clear("login.bankid_tab")
        assert store.get("login.bankid_tab") == []
        assert store.get("login.qr_image") == ["canvas"]

    def test_clear_all(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.save("login.qr_image", "canvas")
        store.clear()
        assert store.get("login.bankid_tab") == []
        assert store.get("login.qr_image") == []

    def test_increment_used(self, store):
        store.save("login.bankid_tab", "button.bankid")
        store.increment_used("login.bankid_tab")
        store.increment_used("login.bankid_tab")
        # Read raw data to check counter
        data = json.loads(store._path.read_text())
        assert data["login.bankid_tab"]["times_used"] == 2

    def test_persists_to_disk(self, store):
        store.save("login.bankid_tab", "button.bankid")
        # Create new instance reading same file
        store2 = LearnedSelectors(path=store._path)
        assert store2.get("login.bankid_tab") == ["button.bankid"]

    def test_metadata_saved(self, store):
        store.save("login.bankid_tab", "button.bankid", page_url="https://example.com")
        data = json.loads(store._path.read_text())
        assert data["login.bankid_tab"]["page_url"] == "https://example.com"
        assert "learned_at" in data["login.bankid_tab"]

    def test_creates_parent_dirs(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "learned.json"
        store = LearnedSelectors(path=deep_path)
        store.save("test", "selector")
        assert deep_path.exists()

    def test_handles_corrupt_file(self, tmp_path):
        path = tmp_path / "learned.json"
        path.write_text("not json{{{")
        store = LearnedSelectors(path=path)
        # Should not raise, just start empty
        assert store.get("test") == []
