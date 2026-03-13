"""Tests for evidence capture."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nocfo.fortnox.web.evidence import EvidenceCapture


@pytest.fixture
def evidence(tmp_path):
    return EvidenceCapture("test_op", base_dir=tmp_path)


@pytest.fixture
def mock_page():
    page = MagicMock()
    page.screenshot = MagicMock()
    return page


class TestEvidenceCapture:
    def test_capture_creates_file(self, evidence, mock_page, tmp_path):
        path = evidence.capture(mock_page, "step_one")
        mock_page.screenshot.assert_called_once_with(path=str(path))
        assert "001_step_one.png" in str(path)
        assert "test_op" in str(path)

    def test_captures_numbered_sequentially(self, evidence, mock_page):
        p1 = evidence.capture(mock_page, "first")
        p2 = evidence.capture(mock_page, "second")
        p3 = evidence.capture(mock_page, "third")
        assert "001_first.png" in str(p1)
        assert "002_second.png" in str(p2)
        assert "003_third.png" in str(p3)

    def test_creates_parent_directories(self, evidence, mock_page):
        path = evidence.capture(mock_page, "test")
        assert path.parent.exists()

    def test_handles_screenshot_failure(self, evidence, mock_page):
        mock_page.screenshot.side_effect = Exception("browser crashed")
        # Should not raise
        path = evidence.capture(mock_page, "failed")
        assert "001_failed.png" in str(path)

    def test_directory_property(self, evidence):
        assert "test_op" in str(evidence.directory)

    def test_different_operations_have_different_dirs(self, tmp_path, mock_page):
        e1 = EvidenceCapture("auth", base_dir=tmp_path)
        e2 = EvidenceCapture("reports", base_dir=tmp_path)
        p1 = e1.capture(mock_page, "test")
        p2 = e2.capture(mock_page, "test")
        assert "auth" in str(p1)
        assert "reports" in str(p2)
        assert str(p1) != str(p2)
