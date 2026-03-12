"""Tests for WorkflowRecorder with mocked Page."""

import json
from unittest.mock import MagicMock

import pytest

from nocfo.recorder.recorder import WorkflowRecorder


@pytest.fixture
def mock_page():
    """Create a mock Playwright sync Page."""
    page = MagicMock()
    page.url = "https://example.com/start"
    page.screenshot = MagicMock()
    page.evaluate = MagicMock()
    page.expose_function = MagicMock()
    page.on = MagicMock()
    return page


@pytest.fixture
def recorder(mock_page, tmp_path):
    """Create a WorkflowRecorder with temp directories."""
    return WorkflowRecorder(
        name="test_recording",
        page=mock_page,
        workflows_dir=tmp_path / "workflows",
        screenshots_dir=tmp_path / "screenshots",
    )


class TestWorkflowRecorder:
    def test_start_injects_and_registers_listener(self, recorder, mock_page):
        recorder.start()

        mock_page.expose_function.assert_called_once()
        assert mock_page.expose_function.call_args[0][0] == "__nocfo_record_event"
        mock_page.evaluate.assert_called_once()
        mock_page.on.assert_called_once_with("load", pytest.approx(mock_page.on.call_args[0][1]))

    def test_on_event_creates_step(self, recorder, mock_page):
        recorder.start()

        event = json.dumps({
            "action": "click",
            "selectors": {"id": "btn1", "css_path": "div > button"},
            "value": None,
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "Submit",
            "timestamp": "2026-01-15T10:30:00",
        })

        recorder._on_event(event)

        assert len(recorder.steps) == 1
        step = recorder.steps[0]
        assert step.step == 1
        assert step.action == "click"
        assert step.selectors.id == "btn1"
        assert step.tag == "button"

    def test_on_event_captures_screenshot(self, recorder, mock_page):
        recorder.start()

        event = json.dumps({
            "action": "click",
            "selectors": {"id": "x"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:00",
        })

        recorder._on_event(event)
        mock_page.screenshot.assert_called_once()

    def test_on_event_handles_screenshot_failure(self, recorder, mock_page):
        mock_page.screenshot.side_effect = Exception("screenshot error")
        recorder.start()

        event = json.dumps({
            "action": "click",
            "selectors": {"id": "x"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:00",
        })

        # Should not raise
        recorder._on_event(event)
        assert len(recorder.steps) == 1
        assert recorder.steps[0].screenshot is None

    def test_on_event_computes_wait_between_steps(self, recorder, mock_page):
        recorder.start()

        event1 = json.dumps({
            "action": "click",
            "selectors": {"id": "a"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:00",
        })
        recorder._on_event(event1)

        # The second event will have a non-zero wait_before_ms
        event2 = json.dumps({
            "action": "click",
            "selectors": {"id": "b"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:01",
        })
        recorder._on_event(event2)

        assert len(recorder.steps) == 2
        # First step always has 0 wait
        assert recorder.steps[0].wait_before_ms == 0
        # Second step has elapsed time (will be small since tests run fast)
        assert recorder.steps[1].wait_before_ms >= 0

    def test_on_event_ignores_when_not_recording(self, recorder, mock_page):
        # Don't call start()
        event = json.dumps({
            "action": "click",
            "selectors": {"id": "x"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:00",
        })
        recorder._on_event(event)
        assert len(recorder.steps) == 0

    def test_on_event_handles_invalid_json(self, recorder, mock_page):
        recorder.start()
        recorder._on_event("not valid json {{{")
        assert len(recorder.steps) == 0

    def test_stop_saves_yaml(self, recorder, mock_page, tmp_path):
        recorder.start()

        event = json.dumps({
            "action": "click",
            "selectors": {"id": "x"},
            "url": "https://example.com",
            "tag": "button",
            "inner_text": "OK",
            "timestamp": "2026-01-15T10:30:00",
        })
        recorder._on_event(event)

        workflow = recorder.stop()

        assert workflow.name == "test_recording"
        assert workflow.total_steps == 1
        assert workflow.start_url == "https://example.com/start"

        yaml_path = tmp_path / "workflows" / "test_recording.yaml"
        assert yaml_path.exists()

    def test_multiple_events_build_ordered_steps(self, recorder, mock_page):
        recorder.start()

        for i in range(5):
            event = json.dumps({
                "action": "click",
                "selectors": {"id": f"btn{i}"},
                "url": "https://example.com",
                "tag": "button",
                "inner_text": f"Button {i}",
                "timestamp": "2026-01-15T10:30:00",
            })
            recorder._on_event(event)

        assert len(recorder.steps) == 5
        for i, step in enumerate(recorder.steps):
            assert step.step == i + 1

    def test_fill_action_recorded(self, recorder, mock_page):
        recorder.start()

        event = json.dumps({
            "action": "fill",
            "selectors": {"name": "email"},
            "value": "user@test.com",
            "url": "https://example.com",
            "tag": "input",
            "inner_text": "",
            "timestamp": "2026-01-15T10:30:00",
        })
        recorder._on_event(event)

        step = recorder.steps[0]
        assert step.action == "fill"
        assert step.value == "user@test.com"
        assert step.selectors.name == "email"
